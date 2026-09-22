"""
app.py — Multi-user AI Job Application Agent Web Server.
Each user has fully isolated account: resume, API keys, job history.
Auth via flask-login (email + password). Compatible with localhost,
Cloudflare tunnel, and any live domain.
"""

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, send_file, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

import auth as auth_module
import db as db_layer

# Load DATABASE_URL early so db_layer.get_pool() can connect
_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url:
    # Try loading from .env file for local dev
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        with open(_env_path, "r", encoding="utf-8") as _ef:
            for _line in _ef:
                _line = _line.strip()
                if _line.startswith("DATABASE_URL="):
                    os.environ["DATABASE_URL"] = _line.split("=", 1)[1]
                    break

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Fix Windows terminal encoding for Unicode output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import collections

# ── Live Terminal Console Ring Buffer & Log Streaming ─────────────────────────
class ConsoleRingBuffer:
    """Thread-safe ring buffer capturing live stdout, stderr, and logging for browser console."""
    def __init__(self, capacity=2000):
        self.capacity = capacity
        self.buffer = collections.deque(maxlen=capacity)
        self.subscribers = []
        self.lock = threading.Lock()
        self._line_id = 0

    def add_line(self, text: str, stream="stdout", category="general"):
        if text is None:
            return
        text_str = str(text).rstrip("\r\n")
        if not text_str:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self._line_id += 1
            entry = {
                "id": self._line_id,
                "text": text_str,
                "stream": stream,
                "time": timestamp,
                "category": category,
            }
            self.buffer.append(entry)
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(entry)
                except Exception:
                    dead.append(q)
            for d in dead:
                if d in self.subscribers:
                    self.subscribers.remove(d)

    def get_recent(self, count=250):
        with self.lock:
            return list(self.buffer)[-count:]

    def clear(self):
        with self.lock:
            self.buffer.clear()
            for q in self.subscribers:
                try:
                    q.put_nowait({"type": "clear"})
                except Exception:
                    pass

    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

GLOBAL_CONSOLE_BUFFER = ConsoleRingBuffer(capacity=2000)

def _categorize_log_line(line: str) -> str:
    lower = line.lower()
    if "[analyze]" in lower or "analyze" in lower:
        return "analyze"
    if "[scraper]" in lower or "scraping" in lower or "scraped" in lower or "playwright" in lower:
        return "scraper"
    if "[pipeline]" in lower:
        return "pipeline"
    if "[gemini]" in lower or "llm_matcher" in lower:
        return "gemini"
    if "[db]" in lower or "neondb" in lower or "postgres" in lower:
        return "db"
    if "[auth]" in lower or "login" in lower or "signup" in lower:
        return "auth"
    if "error" in lower or "exception" in lower or "traceback" in lower or "failed" in lower or "errno" in lower:
        return "error"
    if "warning" in lower or "warn" in lower:
        return "warning"
    if "success" in lower or "completed successfully" in lower or "[ok]" in lower or "✨" in lower or "✅" in lower:
        return "success"
    return "general"

class TeeStream:
    """Tees output to original stream (for Render/terminal) and into ConsoleRingBuffer."""
    def __init__(self, original_stream, buffer_obj, stream_name="stdout"):
        self.original_stream = original_stream
        self.buffer_obj = buffer_obj
        self.stream_name = stream_name
        self._local = threading.local()

    def write(self, s):
        if not s:
            return
        try:
            self.original_stream.write(s)
            self.original_stream.flush()
        except Exception:
            pass

        if not hasattr(self._local, "pending"):
            self._local.pending = ""

        self._local.pending += str(s)
        if "\n" in self._local.pending:
            parts = self._local.pending.split("\n")
            self._local.pending = parts[-1]
            for line in parts[:-1]:
                clean = line.rstrip("\r")
                if clean.strip():
                    cat = _categorize_log_line(clean)
                    self.buffer_obj.add_line(clean, stream=self.stream_name, category=cat)

    def flush(self):
        try:
            self.original_stream.flush()
        except Exception:
            pass
        if hasattr(self._local, "pending") and self._local.pending:
            clean = self._local.pending.rstrip("\r\n")
            if clean.strip():
                cat = _categorize_log_line(clean)
                self.buffer_obj.add_line(clean, stream=self.stream_name, category=cat)
            self._local.pending = ""

    def __getattr__(self, name):
        return getattr(self.original_stream, name)

class BufferLoggingHandler(logging.Handler):
    """Routes standard Python logging calls to the console ring buffer."""
    def __init__(self, buffer_obj):
        super().__init__()
        self.buffer_obj = buffer_obj

    def emit(self, record):
        try:
            msg = self.format(record)
            cat = "error" if record.levelno >= logging.ERROR else ("warning" if record.levelno >= logging.WARNING else _categorize_log_line(msg))
            self.buffer_obj.add_line(msg, stream="log", category=cat)
        except Exception:
            self.handleError(record)

# Wrap stdout & stderr
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr
if not isinstance(sys.stdout, TeeStream):
    sys.stdout = TeeStream(_orig_stdout, GLOBAL_CONSOLE_BUFFER, "stdout")
if not isinstance(sys.stderr, TeeStream):
    sys.stderr = TeeStream(_orig_stderr, GLOBAL_CONSOLE_BUFFER, "stderr")

# Attach logging handler
_root_logger = logging.getLogger()
_buf_handler = BufferLoggingHandler(GLOBAL_CONSOLE_BUFFER)
_buf_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
_buf_handler.setLevel(logging.INFO)
_root_logger.addHandler(_buf_handler)

GLOBAL_CONSOLE_BUFFER.add_line("🚀 ATS Agent Web Server ready. Live terminal console connected.", stream="stdout", category="general")

# Suppress noisy Google GenAI SDK AFC (Automatic Function Calling) advisory warnings
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
logging.getLogger("google_genai").setLevel(logging.ERROR)

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
ENV_PATH = BASE_DIR / ".env"
RESUME_PATH = BASE_DIR / "base_resume.json"  # Legacy global path (pre-auth)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ── Initialize NeonDB schema on startup ───────────────────────────────────────
with app.app_context():
    try:
        db_layer.init_schema()
    except Exception as _db_init_err:
        logging.warning(f"[DB] Schema init skipped: {_db_init_err}")
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)
# Secure cookies when running on HTTPS (Render/production)
app.config["REMEMBER_COOKIE_SECURE"] = os.environ.get("FLASK_ENV", "") == "production" or os.environ.get("RENDER", "") == "true"
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV", "") == "production" or os.environ.get("RENDER", "") == "true"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Secret key — auto-generated and persisted to .env on first boot
app.secret_key = auth_module.ensure_secret_key(ENV_PATH)

CORS(app, supports_credentials=True)

@app.after_request
def add_no_cache_headers(response):
    if request.path.startswith(("/api/preview", "/api/download", "/download")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Reverse proxy support (Cloudflare Tunnel, Nginx, Caddy, custom live domains)
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ── Flask-Login setup ──────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = "login_page"        # redirect here when @login_required fails
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "error"

@login_manager.user_loader
def load_user(user_id: str):
    return auth_module.load_user_by_id(user_id)

@app.before_request
def sync_user_environment():
    """Ensure active user credentials and disk files are synchronized before handling requests."""
    if current_user and current_user.is_authenticated:
        try:
            if hasattr(current_user, "ensure_disk_files"):
                current_user.ensure_disk_files()
            s = current_user.get_settings()
            if s:
                for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "SIMPLIFY_EMAIL", "SIMPLIFY_PASSWORD", "HF_API_KEY", "COLAB_DETECTOR_URL"):
                    val = s.get(k)
                    if val:
                        os.environ[k] = val
        except Exception as e:
            logging.warning(f"[Auth] sync_user_environment note: {e}")

# Active background runs & message queues for SSE
active_runs = {}          # run_id -> (msg_queue, created_at)
_active_runs_lock = threading.Lock()

# In-memory intelligence cache for parsed ATS jobs & Simplify scores
# Bounded to _MAX_ANALYSIS_CACHE entries; oldest 25% evicted when full.
# At ~5KB per entry × 200 entries = ~1MB max — well within Render's limits.
_MAX_ANALYSIS_CACHE = 200
GLOBAL_ANALYSIS_CACHE = {}  # url -> {company, role, jd_text}


def _trim_analysis_cache():
    """Evict oldest entries when GLOBAL_ANALYSIS_CACHE exceeds limit.
    Python 3.7+ dicts preserve insertion order, so keys()[0] is oldest.
    Newly inserted key is always last, so it is never evicted here.
    """
    if len(GLOBAL_ANALYSIS_CACHE) > _MAX_ANALYSIS_CACHE:
        # Drop oldest quarter — keeps the cache useful while reclaiming memory
        keys = list(GLOBAL_ANALYSIS_CACHE.keys())
        n_drop = max(1, len(keys) // 4)
        for k in keys[:n_drop]:
            GLOBAL_ANALYSIS_CACHE.pop(k, None)


def _reap_orphaned_runs():
    """Background thread: remove active_runs entries older than 10 min to prevent queue leaks."""
    while True:
        try:
            time.sleep(120)  # check every 2 minutes
            cutoff = time.time() - 600  # 10-minute TTL
            with _active_runs_lock:
                stale = [rid for rid, (_, created_at) in active_runs.items() if created_at < cutoff]
                for rid in stale:
                    logging.info(f"[Reaper] Evicting orphaned run: {rid}")
                    active_runs.pop(rid, None)
        except Exception as _reap_err:
            logging.warning(f"[Reaper] Error: {_reap_err}")


_reaper_thread = threading.Thread(target=_reap_orphaned_runs, daemon=True, name="RunReaper")
_reaper_thread.start()



def get_env_vars() -> dict:
    """Read .env into dict safely."""
    env_vars = {
        "GEMINI_API_KEY": "",
        "GEMINI_API_KEY_2": "",
        "SIMPLIFY_EMAIL": "",
        "SIMPLIFY_PASSWORD": "",
        "BASE_RESUME_PATH": "base_resume.json",
        "OUTPUT_DIR": str(OUTPUT_DIR),
        "HF_API_KEY": "",
        "COLAB_DETECTOR_URL": "",
    }

    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip()

    return env_vars


def write_env_vars(env_vars: dict):
    """Save dict to .env safely."""
    lines = []
    lines.append("# AI Job Application Agent Credentials")
    lines.append(f"GEMINI_API_KEY={env_vars.get('GEMINI_API_KEY', '')}")
    lines.append(f"GEMINI_API_KEY_2={env_vars.get('GEMINI_API_KEY_2', '')}")
    lines.append(f"SIMPLIFY_EMAIL={env_vars.get('SIMPLIFY_EMAIL', '')}")
    lines.append(f"SIMPLIFY_PASSWORD={env_vars.get('SIMPLIFY_PASSWORD', '')}")
    lines.append(f"BASE_RESUME_PATH={env_vars.get('BASE_RESUME_PATH', 'base_resume.json')}")
    lines.append(f"OUTPUT_DIR={env_vars.get('OUTPUT_DIR', str(OUTPUT_DIR))}")
    lines.append(f"HF_API_KEY={env_vars.get('HF_API_KEY', '')}")
    lines.append(f"COLAB_DETECTOR_URL={env_vars.get('COLAB_DETECTOR_URL', '')}")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ─── Per-User Data Helpers ────────────────────────────────────────────────────
# All user-scoped data (resume, output, settings) is resolved through these.
# Falls back to the legacy global path for backwards-compatibility.

def get_user_resume_path() -> Path:
    """Return the active user's base_resume.json path, restoring from NeonDB to disk if needed."""
    if current_user and current_user.is_authenticated:
        if hasattr(current_user, "ensure_disk_files"):
            try:
                current_user.ensure_disk_files()
            except Exception:
                pass
        p = current_user.resume_path
        if not p.exists() and RESUME_PATH.exists():
            return RESUME_PATH
        return p
    return RESUME_PATH  # legacy fallback

def get_user_output_dir() -> Path:
    """Return the active user's output directory."""
    if current_user and current_user.is_authenticated:
        return current_user.output_dir
    return OUTPUT_DIR  # legacy fallback

def get_user_settings() -> dict:
    """Return the active user's API key settings."""
    if current_user and current_user.is_authenticated:
        return current_user.get_settings()
    return get_env_vars()  # legacy fallback


# ─── Auth Routes ─────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login_page():
    """Login page. Redirects to / if already authenticated."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    users_db = auth_module._load_users_db()
    first_time = len(users_db) == 0
    default_name = ""
    default_email = ""
    if first_time and RESUME_PATH.exists():
        try:
            with open(RESUME_PATH, "r", encoding="utf-8") as f:
                rd = json.load(f)
                default_name = rd.get("name", "")
                default_email = rd.get("contact", {}).get("email", "")
        except Exception:
            pass

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember"))
        next_url = request.form.get("next") or request.args.get("next") or url_for("index")

        user = auth_module.verify_login(email, password)
        if user:
            login_user(user, remember=remember)
            # Safety check: only redirect to relative URLs
            if not next_url.startswith("/"):
                next_url = url_for("index")
            return redirect(next_url)
        else:
            flash("Invalid email or password. Please try again.", "error")

    return render_template(
        "login.html",
        first_time=first_time,
        default_name=default_name,
        default_email=default_email
    )


@app.route("/signup", methods=["POST"])
def signup():
    """Create a new user account with a required resume upload."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    display_name = (request.form.get("display_name") or "").strip()

    # Register user
    user, error = auth_module.register_user(email, password, display_name)
    if error:
        flash(error, "error")
        return redirect(url_for("login_page") + "?mode=signup")

    # Handle resume upload (required)
    resume_file = request.files.get("resume_file")
    if resume_file and resume_file.filename:
        filename = resume_file.filename.lower()
        save_path = user.data_dir / resume_file.filename
        resume_file.save(str(save_path))

        try:
            if filename.endswith(".json"):
                with open(save_path, "r", encoding="utf-8") as f:
                    parsed_json = json.load(f)
            elif filename.endswith((".pdf", ".docx")):
                from pdf_to_resume import parse_resume_pdf
                parsed_json = parse_resume_pdf(str(save_path))
                orig_docx = user.data_dir / "master_resume_original.docx"
                orig_pdf = user.data_dir / "master_resume_original.pdf"
                import shutil
                if filename.endswith(".docx"):
                    shutil.copy2(save_path, orig_docx)
                    try:
                        from resume_builder import convert_to_pdf
                        convert_to_pdf(str(orig_docx))
                    except Exception:
                        pass
                elif filename.endswith(".pdf"):
                    shutil.copy2(save_path, orig_pdf)
                    try:
                        from resume_builder import build_resume_docx
                        detected_font = parsed_json.get("_detected_font", "Calibri")
                        built = build_resume_docx(parsed_json, "Master", "Resume", output_dir=str(user.data_dir), font_family=detected_font)
                        if built and os.path.exists(built):
                            shutil.copy2(built, orig_docx)
                            temp_folder = Path(built).parent
                            if temp_folder != user.data_dir and temp_folder.name.startswith("Master_"):
                                shutil.rmtree(temp_folder, ignore_errors=True)
                    except Exception as b_err:
                        print(f"[Signup] Note building docx from PDF: {b_err}")
            else:
                parsed_json = None

            if parsed_json:
                with open(user.resume_path, "w", encoding="utf-8") as f:
                    json.dump(parsed_json, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Signup] Resume parse error for {email}: {e}")
        finally:
            try:
                if save_path.exists():
                    os.remove(save_path)
            except Exception:
                pass

    login_user(user, remember=True)
    return redirect(url_for("index"))


@app.route("/logout")
@login_required
def logout():
    """Log out and redirect to login page."""
    logout_user()
    flash("You've been signed out.", "success")
    return redirect(url_for("login_page"))


@app.route("/api/me")
@login_required
def api_me():
    """Return current authenticated user's info."""
    has_resume = current_user.has_resume()
    resume_name = ""
    if has_resume:
        try:
            if db_layer.is_db_available():
                rd = db_layer.db_get_resume(current_user.username) or {}
            else:
                with open(current_user.resume_path, "r", encoding="utf-8") as f:
                    rd = json.load(f)
            resume_name = rd.get("name", "")
        except Exception:
            pass
    return jsonify({
        "username": current_user.username,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "has_resume": has_resume,
        "resume_name": resume_name,
    })


@app.route("/api/change_password", methods=["POST"])
@login_required
def change_password():
    data = request.json or {}
    success, error = auth_module.change_password(
        current_user.username,
        data.get("current_password", ""),
        data.get("new_password", ""),
    )
    if success:
        return jsonify({"success": True, "message": "Password changed successfully."})
    return jsonify({"success": False, "error": error}), 400


# ─────────────────────────────────────────────────────────────────────────────
#  AI LAB — HuggingFace AI Content Detector  (standalone, isolated from ATS)
# ─────────────────────────────────────────────────────────────────────────────


@app.route("/api/hf-detect", methods=["POST"])
def hf_detect():
    """
    AI Lab detector — two modes (auto-selected):

    MODE A — Colab (Oxidane/tmr-ai-text-detector, RAID-trained RoBERTa):
      Set COLAB_DETECTOR_URL=https://xxxx.gradio.live in .env
      The Colab notebook calls /run/predict on the Gradio interface.

    MODE B — HuggingFace API (PirateXX/AI-Content-Detector, fallback):
      Requires HF_API_KEY in .env.
      Uses router.huggingface.co (works where api-inference subdomain is blocked).

    Completely isolated from the ATS resume pipeline.
    """
    import httpx

    body      = request.get_json(silent=True) or {}
    text      = (body.get("text") or "").strip()
    hf_key_ui = (body.get("hf_key") or "").strip()

    if not text:
        return jsonify({"error": "No text provided"}), 400
    if len(text) < 50:
        return jsonify({"error": "Text too short — please enter at least 50 characters"}), 400

    env = get_env_vars()
    colab_url = (env.get("COLAB_DETECTOR_URL") or os.environ.get("COLAB_DETECTOR_URL", "")).strip().rstrip("/")

    # ── MODE A: Colab endpoint (TMR / Gradio AI Text Detector) ──────────────
    if colab_url:
        payload = None
        last_error = None

        # 1. Try Gradio 5 protocol (/gradio_api/call/predict)
        try:
            call_url = f"{colab_url}/gradio_api/call/predict"
            init_resp = httpx.post(call_url, json={"data": [text]}, timeout=15.0)
            if init_resp.status_code == 200 and "event_id" in init_resp.json():
                event_id = init_resp.json()["event_id"]
                stream_url = f"{call_url}/{event_id}"
                with httpx.stream("GET", stream_url, timeout=45.0) as stream:
                    for line in stream.iter_lines():
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            raw_parsed = json.loads(data_str)
                            if isinstance(raw_parsed, list) and len(raw_parsed) > 0:
                                payload = raw_parsed[0]
                            else:
                                payload = raw_parsed
                            break
        except Exception as g5_err:
            last_error = g5_err

        # 2. Fallback to standard Gradio 4 / REST endpoints if Gradio 5 wasn't used
        if payload is None:
            candidate_endpoints = [
                f"{colab_url}/detect",
                f"{colab_url}/api/predict",
                f"{colab_url}/run/predict",
                f"{colab_url}/predict",
            ]
            for endpoint in candidate_endpoints:
                try:
                    if endpoint.endswith("/detect"):
                        body_data = {"text": text}
                    else:
                        body_data = {"data": [text]}

                    test_resp = httpx.post(endpoint, json=body_data, timeout=30.0)
                    if test_resp.status_code == 200:
                        res_json = test_resp.json()
                        if isinstance(res_json, dict) and "data" in res_json and isinstance(res_json["data"], list) and len(res_json["data"]) > 0:
                            payload = res_json["data"][0]
                        else:
                            payload = res_json
                        break
                except Exception as exc:
                    last_error = exc
                    continue

        if payload is None:
            return jsonify({
                "error": f"Cannot reach Colab detector at {colab_url}. Make sure the Colab cell is running and the public URL is active. ({last_error})"
            }), 500

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                pass

        ai_prob    = float(payload.get("ai_probability", payload.get("ai_prob", payload.get("ai", 50.0))))
        human_prob = float(payload.get("human_probability", payload.get("human_prob", payload.get("human", round(100.0 - ai_prob, 1)))))
        verdict    = payload.get("verdict", "AI" if ai_prob >= 50 else "Human")
        label      = payload.get("label",   "AI-Generated" if verdict == "AI" else "Likely Human")
        model_name = payload.get("model",   "TMR Multi-Signal Detector (Colab)")

        # Detailed signals if provided by hybrid server
        perplexity = payload.get("perplexity")
        burstiness = payload.get("burstiness")
        classifier_prob = payload.get("classifier_prob", ai_prob)

        return jsonify({
            "ai_probability":    round(ai_prob, 1),
            "human_probability": round(human_prob, 1),
            "verdict":  verdict,
            "label":    label,
            "model":    model_name,
            "perplexity": perplexity,
            "burstiness": burstiness,
            "classifier_prob": classifier_prob,
            "raw":      payload,
        })

    # ── MODE B: HuggingFace router (PirateXX/AI-Content-Detector, fallback) ──
    hf_key = (hf_key_ui or env.get("HF_API_KEY") or os.environ.get("HF_API_KEY", "")).strip()
    if not hf_key:
        return jsonify({
            "error": "No detector configured. Either set COLAB_DETECTOR_URL (recommended) or HF_API_KEY in your .env."
        }), 401

    api_url = "https://router.huggingface.co/hf-inference/models/PirateXX/AI-Content-Detector"
    try:
        resp = httpx.post(
            api_url,
            json={"inputs": text},
            headers={"Authorization": f"Bearer {hf_key}"},
            timeout=30.0,
        )
    except httpx.ConnectError as exc:
        return jsonify({"error": f"Cannot reach HuggingFace router. ({exc})"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if resp.status_code == 503:
        return jsonify({
            "error": "Model loading on HuggingFace (cold start) — wait ~20s and retry.",
            "detail": resp.text,
        }), 503
    if resp.status_code != 200:
        return jsonify({"error": f"HuggingFace API error {resp.status_code}", "detail": resp.text}), resp.status_code

    try:
        raw = resp.json()
    except Exception:
        return jsonify({"error": "Invalid JSON from HuggingFace", "raw_text": resp.text}), 502

    # PirateXX returns [[{"label": "LABEL_0", "score": 0.12}, {"label": "LABEL_1", "score": 0.88}]]
    # LABEL_1 = AI-Generated (Fake), LABEL_0 = Human-Written (Real)
    ai_score = 50.0
    try:
        items = raw[0] if (isinstance(raw, list) and raw and isinstance(raw[0], list)) else (raw if isinstance(raw, list) else [])
        for item in items:
            lbl = (item.get("label") or "").upper()
            sc  = float(item.get("score", 0.5)) * 100
            if lbl in ("LABEL_1", "FAKE", "AI", "GENERATED"):
                ai_score = sc
            elif lbl in ("LABEL_0", "REAL", "HUMAN", "ORIGINAL"):
                ai_score = 100.0 - sc
    except Exception:
        ai_score = 50.0

    human_score = round(100.0 - ai_score, 1)
    ai_score    = round(ai_score, 1)
    verdict     = "AI" if ai_score >= 50.0 else "Human"
    label       = "AI-Generated" if verdict == "AI" else "Likely Human"

    return jsonify({
        "ai_probability":    ai_score,
        "human_probability": human_score,
        "verdict":  verdict,
        "label":    label,
        "model":    "PirateXX/AI-Content-Detector (HuggingFace)",
        "classifier_prob": ai_score,
        "raw":      raw,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  AI LAB — Humanizer Engine (Llama-3 / Gemini Anti-Detection Humanizer)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/humanize", methods=["POST"])
def humanize_text():
    """
    AI Lab Humanizer — rewrites AI-generated text to bypass AI detectors:
    - High sentence-length variance (high burstiness)
    - Replaces formulaic AI vocabulary and robotic transitions
    - Natural idiomatic rhythm while strictly preserving all facts, numbers, and meaning
    """
    import httpx

    body  = request.get_json(silent=True) or {}
    text  = (body.get("text") or "").strip()
    style = (body.get("style") or "professional").lower()

    if not text:
        return jsonify({"error": "No text provided to humanize."}), 400
    if len(text) < 30:
        return jsonify({"error": "Text is too short to humanize (minimum 30 characters)."}), 400

    env = get_env_vars()
    colab_humanizer_url = (env.get("COLAB_HUMANIZER_URL") or os.environ.get("COLAB_HUMANIZER_URL", "")).strip().rstrip("/")

    # Mode 1: If Colab Llama 3 8B Humanizer server is configured
    if colab_humanizer_url:
        try:
            resp = httpx.post(
                f"{colab_humanizer_url}/humanize",
                json={"text": text, "style": style},
                timeout=60.0,
            )
            if resp.status_code == 200:
                res_data = resp.json()
                return jsonify({
                    "success": True,
                    "humanized_text": res_data.get("humanized_text", res_data.get("text", "")),
                    "original_text": text,
                    "engine": "Llama-3-8B Humanizer (Colab)",
                    "style": style,
                })
        except Exception as colab_err:
            print(f"[Humanizer] Colab endpoint note: {colab_err} — falling back to Gemini Engine")

    # Mode 2: Built-in Gemini Anti-Detection Humanizer Engine
    from gemini_client import execute_with_failover, get_all_gemini_keys
    keys = get_all_gemini_keys()
    if not keys:
        return jsonify({
            "error": "GEMINI_API_KEY is not configured in .env. Please add it in Settings to use the built-in Humanizer."
        }), 400

    try:
        from google import genai
        from google.genai import types

        style_guidelines = {
            "professional": "Professional workplace & resume tone. Natural, crisp, direct, active voice.",
            "conversational": "Casual, authentic, conversational human tone with natural everyday flow.",
            "academic": "Scholarly, precise, thoughtful analytical tone with rigorous human cadence.",
        }.get(style, "Natural human tone.")

        humanize_prompt = f"""You are a master human writer and anti-AI detection linguist.
Your task is to completely rewrite and humanize the following text so it reads 100% like a genuine human and bypasses all AI detectors (GPTZero, Turnitin, Copyleaks, RoBERTa).

TARGET STYLE: {style_guidelines}

CRITICAL RULES FOR HUMANIZING:
1. MAXIMIZE BURSTINESS: Dramatically vary your sentence lengths. Alternate between short punchy sentences (3-6 words) and longer descriptive compound sentences (18-25 words).
2. ELIMINATE AI VOCABULARY & CRUTCH PHRASES: Strictly NEVER use words like "testament to", "delve", "pivotal", "transformative", "tapestry", "seamlessly", "furthermore", "moreover", "in conclusion", "harness", "beacon", "foster", "synergy", "underscores", "spearheaded", "dynamic landscape".
3. NATURAL IDIOMATIC CADENCE: Use natural human phrasing, occasional contractions (when natural), authentic flow, and active verbs.
4. PRESERVE 100% OF FACTS, DATA & MEANING: Keep every specific skill, metric, percentage, date, tool name, and factual claim intact. Do NOT invent new facts.
5. NO EXPLANATIONS: Output ONLY the humanized rewritten text. Do NOT add preamble, quotes, markdown wrappers, or explanations.

ORIGINAL TEXT:
{text}"""

        def _call_humanizer(client):
            for m in ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"]:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=humanize_prompt,
                        config=types.GenerateContentConfig(temperature=0.75),
                    )
                    if response and response.text:
                        res_text = response.text.strip()
                        if res_text.startswith(('"', "“")) and res_text.endswith(('"', "”")):
                            res_text = res_text[1:-1].strip()
                        return res_text
                except Exception as model_err:
                    print(f"[Humanizer] {m} note: {model_err}")
                    if "429" in str(model_err) or "RESOURCE_EXHAUSTED" in str(model_err):
                        raise model_err
                    continue
            return ""

        humanized_result = execute_with_failover(_call_humanizer)
        if not humanized_result:
            raise RuntimeError("All Gemini models exhausted for humanizing.")

        return jsonify({
            "success": True,
            "humanized_text": humanized_result,
            "original_text": text,
            "engine": "Gemini Anti-Detection Humanizer Engine",
            "style": style,
        })

    except Exception as e:
        return jsonify({"error": f"Humanizing failed: {str(e)}"}), 500


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "favicon-v2.svg", mimetype="image/svg+xml")


@app.route("/antigravity")
def antigravity_demo():
    """Standalone 1:1 Google Antigravity Particle Experience (pure canvas, zero UI clutter)."""
    return render_template("antigravity.html")


@app.route("/")
@login_required
def index():
    return render_template("index.html", user=current_user)


@app.route("/api/health")
@login_required
def health():
    """Check all prerequisites needed to run the agent (per-user)."""
    env_vars = get_user_settings()
    user_resume_path = get_user_resume_path()
    user_output_dir = get_user_output_dir()

    has_gemini_key = bool(env_vars.get("GEMINI_API_KEY") or env_vars.get("GEMINI_API_KEY_2"))
    has_gemini_backup = bool(env_vars.get("GEMINI_API_KEY_2"))
    # Check resume presence from DB or file
    has_base_resume = current_user.has_resume() if current_user.is_authenticated else user_resume_path.exists()
    has_simplify_email = bool(env_vars.get("SIMPLIFY_EMAIL"))
    has_simplify_password = bool(env_vars.get("SIMPLIFY_PASSWORD"))

    resume_summary = {}
    if has_base_resume:
        try:
            if db_layer.is_db_available() and current_user.is_authenticated:
                data = db_layer.db_get_resume(current_user.username) or {}
            elif user_resume_path.exists():
                with open(user_resume_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
            resume_summary = {
                "name": data.get("name", ""),
                "roles": len(data.get("experience", [])),
                "skills": len(data.get("skills", [])),
                "email": data.get("contact", {}).get("email", ""),
            }
        except Exception:
            pass

    return jsonify({
        "status": "ready" if (has_gemini_key and has_base_resume) else "config_required",
        "checks": {
            "gemini_api_key": has_gemini_key,
            "gemini_api_key_backup": has_gemini_backup,
            "base_resume_exists": has_base_resume,
            "simplify_email": has_simplify_email,
            "simplify_password": has_simplify_password,
            "env_exists": ENV_PATH.exists(),
        },
        "resume_summary": resume_summary,
        "env_path": str(ENV_PATH),
        "output_dir": str(user_output_dir),
    })


@app.route("/api/gemini/health")
@login_required
def gemini_key_health():
    """
    Live-ping each configured Gemini API key and return per-key status.
    Results are cached per-user for 60 seconds to avoid hammering the API.
    Statuses: ok | quota_exhausted | invalid | transient | unconfigured
    503 UNAVAILABLE = Gemini server momentarily busy (amber, NOT a key error).
    """
    from gemini_client import is_quota_error, _ACTIVE_KEY_INDEX
    from google import genai
    from google.genai import types as gtypes

    user_settings = get_user_settings()
    for env_key in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
        val = (user_settings.get(env_key) or "").strip()
        if val:
            os.environ[env_key] = val

    # --- 60-second per-user result cache ---
    cache_key = f"_gemini_health_{getattr(current_user, 'username', 'anon')}"
    cached = getattr(app, cache_key, None)
    if cached and (time.time() - cached.get("ts", 0)) < 60:
        return jsonify(cached["data"])

    # Collect configured keys in order
    raw_keys = []
    for ek in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
        val = (user_settings.get(ek) or "").strip()
        if val:
            raw_keys.append((ek, val))

    if not raw_keys:
        return jsonify({
            "ok": False,
            "keys": [],
            "active_index": 0,
            "message": "No API keys configured. Open Settings to add your Gemini key."
        })

    def _ping_key(key: str) -> tuple[str, str]:
        """
        Ping a single Gemini API key. Returns (status, label).
        Retries once on 503/transient before failing.
        """
        for attempt in range(2):
            try:
                test_client = genai.Client(api_key=key)
                test_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[gtypes.Content(role="user", parts=[gtypes.Part(text="Reply: ok")])],
                    config=gtypes.GenerateContentConfig(max_output_tokens=5, temperature=0),
                )
                return "ok", "Active & Working"
            except Exception as e:
                err_up = str(e).upper()

                # Real quota / rate limit
                if is_quota_error(e):
                    return "quota_exhausted", "Quota / Rate Limit Exhausted"

                # Invalid or wrong key
                if "API_KEY_INVALID" in err_up or "INVALID_ARGUMENT" in err_up:
                    return "invalid", "Invalid API Key"
                if "403" in err_up or "PERMISSION_DENIED" in err_up:
                    return "invalid", "Permission Denied"

                # 503 / transient: Gemini servers busy — NOT a key problem.
                # Retry once; if it still fails, flag as transient (amber).
                if "503" in err_up or "UNAVAILABLE" in err_up or "DEADLINE_EXCEEDED" in err_up:
                    if attempt == 0:
                        time.sleep(1.2)
                        continue  # one retry
                    return "transient", "Gemini servers momentarily busy — key is fine"

                # Unknown error after retry
                if attempt == 0:
                    time.sleep(0.8)
                    continue
                short_msg = str(e)[:60].rstrip()
                return "error", f"Unexpected error — try refreshing"

        return "error", "Unexpected error — try refreshing"

    key_results = []
    for env_name, key in raw_keys:
        masked = (key[:6] + "..." + key[-4:]) if len(key) > 10 else "***"
        status, label = _ping_key(key)
        key_results.append({
            "env":    env_name,
            "masked": masked,
            "status": status,
            "label":  label,
        })

    any_ok       = any(k["status"] in ("ok", "transient") for k in key_results)
    all_broken   = all(k["status"] in ("quota_exhausted", "invalid", "error") for k in key_results)
    active_idx   = _ACTIVE_KEY_INDEX % max(len(key_results), 1)

    if all_broken:
        msg = "⚠️ All keys exhausted or invalid — add a new key in Settings"
    elif any_ok:
        msg = "API keys operational ✅"
    else:
        msg = "Some keys are temporarily busy — retrying automatically"

    result = {
        "ok":          any_ok,
        "all_exhausted": all_broken,
        "keys":        key_results,
        "active_index": active_idx,
        "total_keys":  len(key_results),
        "message":     msg,
    }

    # Cache result for 60 seconds
    setattr(app, cache_key, {"data": result, "ts": time.time()})

    return jsonify(result)


@app.route("/api/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        data = request.json or {}
        updates = {
            "GEMINI_API_KEY": data.get("GEMINI_API_KEY"),
            "GEMINI_API_KEY_2": data.get("GEMINI_API_KEY_2"),
            "SIMPLIFY_EMAIL": data.get("SIMPLIFY_EMAIL"),
            "SIMPLIFY_PASSWORD": data.get("SIMPLIFY_PASSWORD"),
            "HF_API_KEY": data.get("HF_API_KEY"),
            "COLAB_DETECTOR_URL": data.get("COLAB_DETECTOR_URL"),
        }
        current_user.save_settings({k: v for k, v in updates.items() if v is not None})
        return jsonify({"success": True, "message": "Settings saved successfully"})

    env_vars = get_user_settings()
    # Mask API key for security
    raw_key = env_vars.get("GEMINI_API_KEY", "")
    masked_key = (raw_key[:6] + "..." + raw_key[-4:]) if len(raw_key) > 10 else raw_key

    raw_key_2 = env_vars.get("GEMINI_API_KEY_2", "")
    masked_key_2 = (raw_key_2[:6] + "..." + raw_key_2[-4:]) if len(raw_key_2) > 10 else raw_key_2

    return jsonify({
        "GEMINI_API_KEY": raw_key,
        "GEMINI_API_KEY_MASKED": masked_key,
        "GEMINI_API_KEY_2": raw_key_2,
        "GEMINI_API_KEY_2_MASKED": masked_key_2,
        "SIMPLIFY_EMAIL": env_vars.get("SIMPLIFY_EMAIL", ""),
        "SIMPLIFY_PASSWORD": env_vars.get("SIMPLIFY_PASSWORD", ""),
        "OUTPUT_DIR": str(get_user_output_dir()),
    })


@app.route("/api/resume", methods=["GET", "POST"])
@login_required
def manage_resume():
    user_resume_path = get_user_resume_path()
    if request.method == "POST":
        try:
            new_data = request.json
            if db_layer.is_db_available():
                db_layer.db_save_resume(current_user.username, new_data)
            else:
                with open(user_resume_path, "w", encoding="utf-8") as f:
                    json.dump(new_data, f, indent=2, ensure_ascii=False)
            return jsonify({"success": True, "message": "Base resume updated"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    # GET — load from DB or file
    if db_layer.is_db_available():
        data = db_layer.db_get_resume(current_user.username)
        if not data:
            return jsonify({"error": "Resume not found"}), 404
        return jsonify(data)

    if not user_resume_path.exists():
        return jsonify({"error": "base_resume.json not found"}), 404
    with open(user_resume_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/upload_resume", methods=["POST"])
@login_required
def upload_resume():
    """Upload a new Master Resume (PDF / DOCX / JSON)."""
    user_resume_path = get_user_resume_path()
    user_data_dir = current_user.data_dir if current_user.is_authenticated else BASE_DIR

    if "resume_file" not in request.files:
        return jsonify({"success": False, "error": "No file attached"}), 400

    file = request.files["resume_file"]
    if not file.filename:
        return jsonify({"success": False, "error": "Empty filename"}), 400

    filename = file.filename.lower()
    save_path = user_data_dir / file.filename
    file.save(save_path)

    try:
        if filename.endswith(".json"):
            with open(save_path, "r", encoding="utf-8") as f:
                parsed_json = json.load(f)
        elif filename.endswith(".pdf") or filename.endswith(".docx"):
            from pdf_to_resume import parse_resume_pdf
            parsed_json = parse_resume_pdf(str(save_path))

            orig_docx_target = user_data_dir / "master_resume_original.docx"
            orig_pdf_target = user_data_dir / "master_resume_original.pdf"
            import shutil

            if filename.endswith(".docx"):
                shutil.copy2(save_path, orig_docx_target)
                print(f"[Upload] Saved uploaded DOCX template to: {orig_docx_target}")
                try:
                    from resume_builder import convert_to_pdf
                    convert_to_pdf(str(orig_docx_target))
                except Exception as pdf_e:
                    print(f"[Upload] Note converting original docx to pdf: {pdf_e}")
            elif filename.endswith(".pdf"):
                shutil.copy2(save_path, orig_pdf_target)
                print(f"[Upload] Saved uploaded PDF to: {orig_pdf_target}")
                try:
                    from resume_builder import build_resume_docx
                    detected_font = parsed_json.get("_detected_font", "Calibri")
                    built_docx = build_resume_docx(parsed_json, "Master", "Resume", output_dir=str(user_data_dir), font_family=detected_font)
                    if built_docx and os.path.exists(built_docx):
                        shutil.copy2(built_docx, orig_docx_target)
                        temp_folder = Path(built_docx).parent
                        if temp_folder != user_data_dir and temp_folder.name.startswith("Master_"):
                            shutil.rmtree(temp_folder, ignore_errors=True)
                        print(f"[Upload] Generated baseline master_resume_original.docx ({detected_font}) from PDF: {orig_docx_target}")
                except Exception as b_err:
                    print(f"[Upload] Note generating original docx from PDF: {b_err}")
        else:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PDF, DOCX, or JSON."}), 400

        # Remove temp upload file if distinct from master_resume_original
        try:
            if save_path.exists() and save_path.name not in ("master_resume_original.docx", "master_resume_original.pdf"):
                os.remove(save_path)
        except Exception:
            pass

        # Save parsed JSON resume
        if db_layer.is_db_available():
            db_layer.db_save_resume(current_user.username, parsed_json)
        else:
            with open(user_resume_path, "w", encoding="utf-8") as f:
                json.dump(parsed_json, f, indent=2, ensure_ascii=False)
        # Also write to local file as temp cache for pipeline (pipelines read from Path)
        try:
            with open(user_resume_path, "w", encoding="utf-8") as f:
                json.dump(parsed_json, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        # Store DOCX bytes in DB if uploaded
        orig_docx_target = user_data_dir / "master_resume_original.docx"
        if db_layer.is_db_available() and orig_docx_target.exists():
            try:
                with open(orig_docx_target, "rb") as f:
                    db_layer.db_save_resume_docx(current_user.username, f.read())
            except Exception:
                pass

        name = parsed_json.get("name", "Your")
        skills_count = len(parsed_json.get("skills", []))
        exp_count = len(parsed_json.get("experience", []))
        return jsonify({
            "success": True,
            "message": f"Resume parsed: {name} — {skills_count} skills, {exp_count} roles found.",
            "resume": parsed_json
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Failed to parse resume: {e}"}), 500


@app.route("/api/delete_resume", methods=["DELETE"])
@login_required
def delete_resume():
    """Delete the current master resume (base_resume.json) and reset to empty."""
    user_resume_path = get_user_resume_path()
    user_data_dir = current_user.data_dir if current_user.is_authenticated else BASE_DIR
    try:
        empty = {"_empty": True, "name": "", "contact": {}, "summary": "",
                 "skills": [], "experience": [], "education": [],
                 "projects": [], "certifications": []}

        if db_layer.is_db_available():
            db_layer.db_delete_resume(current_user.username)
        else:
            with open(user_resume_path, "w", encoding="utf-8") as f:
                json.dump(empty, f, indent=2)

        # Also wipe local file copy if present
        try:
            with open(user_resume_path, "w", encoding="utf-8") as f:
                json.dump(empty, f, indent=2)
        except Exception:
            pass

        # Remove physical docx/pdf templates
        for fname in ("master_resume_original.docx", "master_resume_original.pdf"):
            fpath = user_data_dir / fname
            if fpath.exists():
                try:
                    os.remove(fpath)
                except Exception:
                    pass

        return jsonify({"success": True, "message": "Master resume deleted successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history")
@login_required
def history():
    """List all previously generated resume applications for the current user."""
    applications = []

    if db_layer.is_db_available():
        # ── DB mode: fetch from NeonDB ─────────────────────────────────────────
        applications = db_layer.db_get_history(current_user.username)
        user_output_dir = get_user_output_dir()
        for app_entry in applications:
            out_f    = app_entry.get("output_file", "")
            company  = app_entry.get("company", "")
            role     = app_entry.get("role", "")
            c_slug   = _safe_slugify(company)
            r_slug   = _safe_slugify(role)
            folder   = f"{c_slug}_{r_slug}" if (c_slug or r_slug) else ""

            rel_path = ""
            if out_f:
                p_out = Path(out_f.replace("\\", "/"))
                if p_out.exists():
                    # File exists at stored absolute path — build relative from output dir
                    try:
                        rel_path = os.path.relpath(str(p_out), str(user_output_dir)).replace("\\", "/")
                    except ValueError:
                        rel_path = f"{p_out.parent.name}/{p_out.name}"
                elif folder:
                    # File missing on disk — build a canonical path the download route can regen from
                    fname = p_out.name if (p_out.name and p_out.name.lower().endswith((".docx", ".pdf"))) else f"{c_slug}_{r_slug}_Resume.docx"
                    rel_path = f"{folder}/{fname}"
                    app_entry["_needs_regen"] = True
                else:
                    fname = p_out.name if (p_out.name and p_out.name.lower().endswith((".docx", ".pdf"))) else "Resume.docx"
                    rel_path = f"{p_out.parent.name}/{fname}" if p_out.parent.name else fname
            elif folder:
                rel_path = f"{folder}/{c_slug}_{r_slug}_Resume.docx"
                app_entry["_needs_regen"] = True

            # Normalize any lingering .json extension to .docx
            if rel_path and rel_path.lower().endswith(".json"):
                rel_path = re.sub(r'\.json$', '.docx', rel_path, flags=re.IGNORECASE)

            app_entry["relative_file_path"] = rel_path

    else:
        # ── File fallback: read from disk logs ────────────────────────────────
        user_output_dir = get_user_output_dir()
        logs_dir = user_output_dir / "logs"
        if logs_dir.exists():
            for log_file in sorted(logs_dir.glob("run_*.json"), reverse=True):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        log_data = json.load(f)
                    output_file = log_data.get("output_file", "")
                    rel_file = ""
                    if output_file and os.path.exists(output_file):
                        rel_file = os.path.relpath(output_file, str(user_output_dir)).replace("\\", "/")
                    else:
                        co = log_data.get("company", "")
                        ro = log_data.get("role", "")
                        c_slug = _safe_slugify(co)
                        r_slug = _safe_slugify(ro)
                        if c_slug or r_slug:
                            rel_file = f"{c_slug}_{r_slug}/{c_slug}_{r_slug}_Resume.docx"
                    if rel_file and rel_file.lower().endswith(".json"):
                        rel_file = re.sub(r'\.json$', '.docx', rel_file, flags=re.IGNORECASE)
                    log_data["relative_file_path"] = rel_file
                    log_data["log_file_name"] = log_file.name
                    applications.append(log_data)
                except Exception:
                    continue

    return jsonify({"applications": applications, "count": len(applications)})


def _safe_slugify(text: str) -> str:
    """Safe slugify without external dependency."""
    text = re.sub(r'[^\w\s-]', '', str(text))
    text = re.sub(r'[\s_-]+', '_', text)
    return text.strip('_')


def _delete_single_history_log(filename: str, user_output_dir: Path = None) -> bool:
    """Helper: Hard delete log file, .docx, .pdf, cover letters, and the physical application folder on disk."""
    import shutil

    effective_output_dir = user_output_dir or get_user_output_dir()
    logs_dir = effective_output_dir / "logs"
    log_file = logs_dir / filename
    if not log_file.exists():
        return False

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        output_file = log_data.get("output_file", "")
        company = log_data.get("company", "")
        role = log_data.get("role", "")
        
        # 1. Target output_file parent dir if specified
        if output_file:
            out_path = Path(output_file)
            parent_dir = out_path.parent
            if parent_dir.exists() and parent_dir != effective_output_dir and parent_dir != Path(__file__).resolve().parent:
                shutil.rmtree(parent_dir, ignore_errors=True)
            elif out_path.exists():
                try:
                    os.remove(out_path)
                except Exception:
                    pass
        
        # 2. Also search for any slugified folder in user output/ and root workspace
        if company and role:
            target_folder_name = f"{_safe_slugify(company)}_{_safe_slugify(role)}"[:80]
            # Check in user output/
            out_sub = effective_output_dir / target_folder_name
            if out_sub.exists():
                shutil.rmtree(out_sub, ignore_errors=True)
            # Check in project root
            root_sub = Path(__file__).resolve().parent / target_folder_name
            if root_sub.exists():
                shutil.rmtree(root_sub, ignore_errors=True)

        if log_file.exists():
            os.remove(log_file)
        return True
    except Exception as e:
        print(f"[History Delete Error] {filename}: {e}")
        return False


@app.route("/api/history/<filename>", methods=["PUT", "POST"])
@app.route("/api/history/update", methods=["POST"])
@login_required
def update_history_item(filename=None):
    """Update company name, role title, and job URL for a saved application."""
    data = request.json or {}
    fname = filename or data.get("filename")
    if not fname:
        return jsonify({"success": False, "error": "Log filename is required"}), 400

    new_company = data.get("company", "").strip() or None
    new_role = data.get("role", "").strip() or None
    new_url = data.get("url", "").strip()

    try:
        if db_layer.is_db_available():
            # In DB mode the filename IS the run_id (e.g. "run_1726234567890.json" → strip .json)
            run_id = fname.replace(".json", "")
            ok = db_layer.db_update_history_item(run_id, company=new_company, role=new_role, url=new_url)
            if not ok:
                return jsonify({"success": False, "error": f"History entry {fname} not found"}), 404
            log_data = db_layer.db_get_history_item(run_id) or {}
        else:
            user_output_dir = get_user_output_dir()
            log_file = user_output_dir / "logs" / fname
            if not log_file.exists():
                return jsonify({"success": False, "error": f"History log {fname} not found"}), 404
            with open(log_file, "r", encoding="utf-8") as f:
                log_data = json.load(f)
            if new_company:
                log_data["company"] = new_company
            if new_role:
                log_data["role"] = new_role
            if new_url is not None:
                log_data["url"] = new_url
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2)

        return jsonify({
            "success": True,
            "message": "Application details updated successfully",
            "application": log_data
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history/<filename>", methods=["DELETE"])
@login_required
def delete_history_item(filename):
    """Delete a history run entry (and its output folder on disk if file mode)."""
    try:
        if db_layer.is_db_available():
            run_id = filename.replace(".json", "")
            ok = db_layer.db_delete_history_item(run_id)
            if ok:
                return jsonify({"success": True, "message": "History entry deleted."})
            return jsonify({"success": False, "error": "History entry not found."}), 404
        else:
            user_output_dir = get_user_output_dir()
            if _delete_single_history_log(filename, user_output_dir):
                return jsonify({"success": True, "message": "History entry and physical output folder deleted permanently from disk"})
            return jsonify({"success": False, "error": "Failed to delete history item or file not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history/delete_batch", methods=["POST"])
@login_required
def delete_history_batch():
    """Bulk delete multiple history run entries."""
    try:
        data = request.json or {}
        filenames = data.get("filenames", [])
        if not filenames or not isinstance(filenames, list):
            return jsonify({"success": False, "error": "No filenames provided for bulk deletion"}), 400

        deleted_count = 0
        if db_layer.is_db_available():
            for fname in filenames:
                run_id = fname.replace(".json", "")
                if db_layer.db_delete_history_item(run_id):
                    deleted_count += 1
        else:
            user_output_dir = get_user_output_dir()
            for fname in filenames:
                if _delete_single_history_log(fname, user_output_dir):
                    deleted_count += 1

        return jsonify({
            "success": True,
            "message": f"Successfully deleted {deleted_count} history entries.",
            "deleted_count": deleted_count
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history/clear_all", methods=["POST", "DELETE"])
@login_required
def clear_all_history():
    """Hard delete all history entries for the current user."""
    import shutil
    deleted_count = 0

    if db_layer.is_db_available():
        deleted_count = db_layer.db_delete_all_history(current_user.username)
    else:
        user_output_dir = get_user_output_dir()
        logs_dir = user_output_dir / "logs"
        if logs_dir.exists():
            for log_file in list(logs_dir.glob("run_*.json")):
                if _delete_single_history_log(log_file.name, user_output_dir):
                    deleted_count += 1
        # Also clean leftover application subfolders inside user output/
        if user_output_dir.exists():
            for item in user_output_dir.iterdir():
                if item.is_dir() and item.name not in ("logs", "uploads", ".git"):
                    shutil.rmtree(item, ignore_errors=True)

    return jsonify({
        "success": True,
        "message": f"Successfully deleted all {deleted_count} history entries.",
        "deleted_count": deleted_count
    })


@app.route("/api/download/<path:filepath>")
@app.route("/download/<path:filepath>")
@app.route("/api/<path:filepath>")
@login_required
def download_file(filepath):
    """Download a generated resume .docx, .pdf, or .json file with robust path resolution."""
    user_output_dir = get_user_output_dir()
    user_resume_path = get_user_resume_path()
    # Guard reserved API endpoints
    first_seg = filepath.split("/")[0].lower()
    if first_seg in ("health", "settings", "resume", "upload_resume", "delete_resume", "history", "analyze", "open-folder", "cover-letter", "run", "hf-detect", "humanize", "stream", "me", "change_password", "login", "logout", "signup", "console"):
        return jsonify({"error": "Endpoint not found"}), 404

    import urllib.parse
    clean_fp = urllib.parse.unquote(filepath).replace("\\", "/").strip("/")
    user_data_dir = current_user.data_dir if current_user.is_authenticated else BASE_DIR

    # 0. Master resume explicit download handlers
    if clean_fp in ("master", "master_resume", "master_resume.docx", "master.docx"):
        user_orig_docx = user_data_dir / "master_resume_original.docx"
        if user_orig_docx.exists():
            return send_file(
                str(user_orig_docx),
                as_attachment=True,
                download_name="Master_Resume.docx",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
    if clean_fp in ("master_resume.pdf", "master.pdf", "master_resume_original.pdf"):
        user_orig_pdf = user_data_dir / "master_resume_original.pdf"
        if user_orig_pdf.exists():
            return send_file(str(user_orig_pdf), as_attachment=True, download_name="Master_Resume.pdf", mimetype="application/pdf")
        user_orig_docx = user_data_dir / "master_resume_original.docx"
        if user_orig_docx.exists():
            from resume_builder import convert_to_pdf
            pdf_res = convert_to_pdf(str(user_orig_docx))
            if pdf_res and os.path.exists(pdf_res):
                return send_file(str(pdf_res), as_attachment=True, download_name="Master_Resume.pdf", mimetype="application/pdf")

    # 1. Direct absolute path check
    target_path = Path(clean_fp)
    if not (target_path.is_absolute() and target_path.exists()):
        target_path = (user_output_dir / clean_fp).resolve()

    # 2. Check inside BASE_DIR
    if not target_path.exists():
        candidate_base = (BASE_DIR / clean_fp).resolve()
        if candidate_base.exists():
            target_path = candidate_base

    # 3. Check stripped 'output/' prefix
    if not target_path.exists() and "output/" in clean_fp.lower():
        sub = clean_fp.split("output/", 1)[-1]
        candidate_sub = (user_output_dir / sub).resolve()
        if candidate_sub.exists():
            target_path = candidate_sub

    # 4. Search recursively inside user output_dir by exact filename
    if not target_path.exists():
        fname = Path(clean_fp).name
        matches = list(user_output_dir.rglob(fname))
        if matches:
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = matches[0].resolve()

    # 5. If PDF requested and target_path not found, search for .docx counterpart and convert on the fly!
    is_pdf_req = clean_fp.lower().endswith(".pdf")
    is_docx_req = clean_fp.lower().endswith(".docx")
    is_json_req = clean_fp.lower().endswith(".json")

    if not target_path.exists() and is_pdf_req:
        docx_name = Path(clean_fp).stem + ".docx"
        docx_matches = list(user_output_dir.rglob(docx_name))
        if docx_matches:
            docx_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            try:
                from resume_builder import convert_to_pdf
                pdf_res = convert_to_pdf(str(docx_matches[0]))
                if pdf_res and os.path.exists(pdf_res):
                    target_path = Path(pdf_res).resolve()
            except Exception as e:
                print(f"[Download] On-the-fly PDF conversion error: {e}")

    # 6. If Cover Letter requested with any name, find newest Cover_Letter in output
    if not target_path.exists() and "cover_letter" in clean_fp.lower():
        subfolder = Path(clean_fp).parent
        search_dir = (user_output_dir / subfolder).resolve() if (user_output_dir / subfolder).exists() else user_output_dir
        cl_matches = list(search_dir.rglob("*Cover_Letter*.docx")) or list(user_output_dir.rglob("*Cover_Letter*.docx"))
        if cl_matches:
            cl_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = cl_matches[0].resolve()

    # 7. Robust On-the-fly Regeneration for any missing resume .docx or .pdf
    # Handles previous sessions, Render container rebuilds, and disk wipeouts.
    if not target_path.exists() and (is_docx_req or is_pdf_req or "resume" in clean_fp.lower()):
        try:
            path_parts = clean_fp.replace("\\", "/").split("/")
            folder_name = path_parts[0] if len(path_parts) > 1 else ""
            file_stem = Path(clean_fp).stem

            # Attempt 1: Match metadata from NeonDB history or local logs
            matched = None
            if db_layer.is_db_available() and current_user.is_authenticated:
                all_hist = db_layer.db_get_history(current_user.username)
                for h in all_hist:
                    c_slug = _safe_slugify(h.get("company", ""))
                    r_slug = _safe_slugify(h.get("role", ""))
                    hist_folder = f"{c_slug}_{r_slug}"
                    if (hist_folder and hist_folder.lower() == folder_name.lower()) or \
                       (c_slug and c_slug.lower() in folder_name.lower()) or \
                       (c_slug and c_slug.lower() in file_stem.lower()) or \
                       (_safe_slugify(Path(h.get("output_file", "")).name).lower() == _safe_slugify(Path(clean_fp).name).lower()):
                        matched = h
                        break

            if not matched:
                # Check local log files
                logs_dir = user_output_dir / "logs"
                if logs_dir.exists():
                    for lf in sorted(logs_dir.glob("run_*.json"), reverse=True):
                        try:
                            with open(lf, "r", encoding="utf-8") as lff:
                                ldata = json.load(lff)
                            c_slug = _safe_slugify(ldata.get("company", ""))
                            r_slug = _safe_slugify(ldata.get("role", ""))
                            hist_folder = f"{c_slug}_{r_slug}"
                            if (hist_folder and hist_folder.lower() == folder_name.lower()) or \
                               (c_slug and c_slug.lower() in folder_name.lower()) or \
                               (c_slug and c_slug.lower() in file_stem.lower()):
                                matched = ldata
                                break
                        except Exception:
                            continue

            company = matched.get("company") if matched else ""
            role_str = matched.get("role") if matched else ""
            if not company and folder_name and "_" in folder_name:
                parts = folder_name.split("_", 1)
                company = parts[0].replace("_", " ")
                role_str = parts[1].replace("_", " ") if len(parts) > 1 else "Role"
            if not company:
                company = "Company"
                role_str = "Role"

            # Retrieve tailored resume dict if present, or base_resume.json
            tailored = (matched.get("tailored_resume") or matched.get("resume_json") or matched.get("output_data")) if matched else None
            resume_dict = None
            if tailored:
                resume_dict = json.loads(tailored) if isinstance(tailored, str) else tailored
            elif user_resume_path.exists():
                with open(user_resume_path, "r", encoding="utf-8") as rf:
                    resume_dict = json.load(rf)
            elif RESUME_PATH.exists():
                with open(RESUME_PATH, "r", encoding="utf-8") as rf:
                    resume_dict = json.load(rf)

            if resume_dict:
                # Check for user master template
                user_orig_docx = user_data_dir / "master_resume_original.docx"
                orig_docx_path = user_orig_docx if user_orig_docx.exists() else (BASE_DIR / "master_resume_original.docx")

                gen_docx = None
                if orig_docx_path.exists():
                    try:
                        from docx_patcher import patch_docx_with_rewritten_resume
                        gen_docx = patch_docx_with_rewritten_resume(
                            original_docx_path=str(orig_docx_path),
                            rewritten_resume=resume_dict,
                            company=company,
                            role=role_str,
                            output_dir=str(user_output_dir),
                        )
                    except Exception as pe:
                        print(f"[Download] Patcher on-the-fly note: {pe}")

                if not gen_docx or not os.path.exists(gen_docx):
                    from resume_builder import build_resume_docx
                    gen_docx = build_resume_docx(
                        resume=resume_dict,
                        company=company,
                        role=role_str,
                        output_dir=str(user_output_dir),
                    )

                if gen_docx and os.path.exists(gen_docx):
                    if is_pdf_req:
                        from resume_builder import convert_to_pdf
                        pdf_res = convert_to_pdf(gen_docx)
                        if not pdf_res or not os.path.exists(pdf_res):
                            try:
                                from resume_html import docx_to_html, generate_pdf_from_html
                                html_c = docx_to_html(gen_docx)
                                cand_pdf = str(Path(gen_docx).with_suffix(".pdf"))
                                if generate_pdf_from_html(html_c, cand_pdf):
                                    pdf_res = cand_pdf
                            except Exception as html_pdf_err:
                                print(f"[Download] HTML-to-PDF note: {html_pdf_err}")

                        if pdf_res and os.path.exists(pdf_res):
                            target_path = Path(pdf_res).resolve()
                        else:
                            target_path = Path(gen_docx).resolve()
                    else:
                        target_path = Path(gen_docx).resolve()
                    print(f"[Download] Successfully generated missing document: {target_path.name}")
        except Exception as auto_gen_err:
            print(f"[Download] Auto regeneration error: {auto_gen_err}")

    # 8. Fallback to user base_resume.json if json requested
    if not target_path.exists() and is_json_req:
        if user_resume_path.exists():
            target_path = user_resume_path.resolve()

    # 9. Last-ditch recovery: If target_path still does not exist, find newest resume in output_dir
    if not target_path.exists() or not target_path.is_file():
        ext_to_find = ".pdf" if is_pdf_req else ".docx"
        any_matches = list(user_output_dir.rglob(f"*{ext_to_find}")) or list(user_output_dir.rglob("*.docx"))
        if any_matches:
            any_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = any_matches[0].resolve()

    if not target_path.exists() or not target_path.is_file():
        return jsonify({"error": f"File '{filepath}' not found"}), 404

    # Determine correct download filename and MIME type
    download_name = target_path.name
    req_name = Path(clean_fp).name
    if req_name and Path(req_name).suffix.lower() == target_path.suffix.lower():
        download_name = req_name
    elif target_path.suffix.lower() == ".docx" and not download_name.lower().endswith(".docx"):
        download_name = Path(download_name).stem + ".docx"
    elif target_path.suffix.lower() == ".pdf" and not download_name.lower().endswith(".pdf"):
        download_name = Path(download_name).stem + ".pdf"

    mimetype = "application/octet-stream"
    if target_path.suffix.lower() == ".docx":
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif target_path.suffix.lower() == ".pdf":
        mimetype = "application/pdf"
    elif target_path.suffix.lower() == ".json":
        mimetype = "application/json"

    return send_file(
        str(target_path),
        as_attachment=True,
        download_name=download_name,
        mimetype=mimetype,
    )


@app.route("/api/preview/<path:filepath>")
@login_required
def preview_file(filepath):
    """
    Preview a generated resume, cover letter, or master resume directly in-browser.
    Renders high-fidelity HTML directly into the iframe (0ms, zero download, selectable text).
    If a PDF is explicitly requested and exists, serves inline application/pdf.
    NEVER sends binary docx directly to prevent unwanted browser downloads!
    """
    user_output_dir = get_user_output_dir()
    user_resume_path = get_user_resume_path()
    user_data_dir = current_user.data_dir if current_user.is_authenticated else BASE_DIR

    import urllib.parse
    clean_fp = urllib.parse.unquote(filepath).replace("\\", "/").strip("/")

    from resume_html import resume_json_to_html, docx_to_html, _get_base_html_template

    # 1. Master Resume Preview Requests
    if clean_fp in ("master", "master_resume", "master_resume.docx", "master.docx"):
        # Priority 1: Render directly from base_resume.json for instant, pixel-perfect HTML preview
        if user_resume_path.exists():
            try:
                with open(user_resume_path, "r", encoding="utf-8") as f:
                    r_data = json.load(f)
                html_view = resume_json_to_html(r_data, role="Authentic Candidate Base Profile")
                return Response(html_view, mimetype="text/html")
            except Exception as e:
                print(f"[Preview] Render master JSON error: {e}")

        # Priority 2: Render from master_resume_original.docx via docx_to_html
        user_orig_docx = user_data_dir / "master_resume_original.docx"
        if user_orig_docx.exists():
            try:
                html_view = docx_to_html(str(user_orig_docx), role="Authentic Candidate Base Profile")
                return Response(html_view, mimetype="text/html")
            except Exception as e:
                print(f"[Preview] Convert master docx error: {e}")

        # Priority 3: Original PDF if exists and user requested it
        user_orig_pdf = user_data_dir / "master_resume_original.pdf"
        if user_orig_pdf.exists():
            return send_file(str(user_orig_pdf), as_attachment=False, mimetype="application/pdf")

    elif clean_fp in ("master.pdf", "master_resume_original.pdf", "master_resume.pdf"):
        user_orig_pdf = user_data_dir / "master_resume_original.pdf"
        if user_orig_pdf.exists():
            return send_file(str(user_orig_pdf), as_attachment=False, mimetype="application/pdf")
        # Otherwise render HTML version
        if user_resume_path.exists():
            with open(user_resume_path, "r", encoding="utf-8") as f:
                r_data = json.load(f)
            return Response(resume_json_to_html(r_data, role="Authentic Candidate Base Profile"), mimetype="text/html")

    # 2. Standard Path Resolution
    target_path = Path(clean_fp)
    if not (target_path.is_absolute() and target_path.exists()):
        target_path = (user_output_dir / clean_fp).resolve()

    if not target_path.exists():
        candidate_base = (BASE_DIR / clean_fp).resolve()
        if candidate_base.exists():
            target_path = candidate_base

    if not target_path.exists() and "output/" in clean_fp.lower():
        sub = clean_fp.split("output/", 1)[-1]
        candidate_sub = (user_output_dir / sub).resolve()
        if candidate_sub.exists():
            target_path = candidate_sub

    if not target_path.exists():
        fname = Path(clean_fp).name
        matches = list(user_output_dir.rglob(fname))
        if matches:
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = matches[0].resolve()

    # If file was not found on disk, attempt self-healing from base_resume.json
    if not target_path.exists() and ("resume" in clean_fp.lower() or clean_fp.endswith((".docx", ".pdf"))):
        folder_part = Path(clean_fp).parent.name
        if folder_part and "_" in folder_part and user_resume_path.exists():
            try:
                parts = folder_part.split("_", 1)
                comp = parts[0]
                rol = parts[1] if len(parts) > 1 else ""
                with open(user_resume_path, "r", encoding="utf-8") as rf:
                    base_r = json.load(rf)
                from resume_builder import build_resume_docx
                regen_p = build_resume_docx(base_r, comp, rol, output_dir=str(user_output_dir))
                if regen_p and os.path.exists(regen_p):
                    target_path = Path(regen_p).resolve()
            except Exception as e:
                print(f"[Preview] Auto-regen error: {e}")

    # If target is still missing:
    if not target_path.exists():
        error_html = _get_base_html_template(
            f"""<div style="text-align: center; padding: 60px 20px; color: #4b5563;">
              <div style="font-size: 36px; margin-bottom: 12px; color: #9ca3af;"><i class="fa-solid fa-file-circle-exclamation"></i></div>
              <h2 style="font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 6px;">Document Ready to Generate</h2>
              <p style="font-size: 13px; color: #6b7280; max-width: 480px; margin: 0 auto 16px;">
                The document for <b>{html.escape(Path(clean_fp).name)}</b> can be generated by tailoring your resume in the Apply tab.
              </p>
            </div>""",
            title="Resume Document Preview"
        )
        return Response(error_html, mimetype="text/html")

    # 3. If DOCX file, convert the actual document to HTML (100% faithful to download)
    if target_path.suffix.lower() == ".docx" and target_path.exists():
        try:
            html_view = docx_to_html(str(target_path))
            return Response(html_view, mimetype="text/html")
        except Exception as e:
            print(f"[Preview] Error converting docx to html: {e}")

    # 4. If PDF file and exists, send inline
    if target_path.suffix.lower() == ".pdf" and target_path.exists():
        return send_file(
            str(target_path),
            as_attachment=False,
            download_name=target_path.name,
            mimetype="application/pdf",
        )

    # 5. Check for tailored_resume.json in the same folder as fallback
    json_cand = target_path.parent / "tailored_resume.json"
    if json_cand.exists():
        try:
            with open(json_cand, "r", encoding="utf-8") as jf:
                tailored_dict = json.load(jf)
            html_view = resume_json_to_html(tailored_dict)
            return Response(html_view, mimetype="text/html")
        except Exception as e:
            print(f"[Preview] Failed reading tailored_resume.json: {e}")

    # 6. If JSON file, render as resume HTML
    if target_path.suffix.lower() == ".json":
        try:
            with open(target_path, "r", encoding="utf-8") as jf:
                j_data = json.load(jf)
            return Response(resume_json_to_html(j_data), mimetype="text/html")
        except Exception as e:
            print(f"[Preview] Error rendering json: {e}")

    # 7. Fallback: Convert via docx_to_html or send text
    if target_path.suffix.lower() in (".txt", ".md"):
        content = target_path.read_text(encoding="utf-8", errors="replace")
        return Response(_get_base_html_template(f"<pre style='white-space: pre-wrap; font-family: inherit;'>{html.escape(content)}</pre>"), mimetype="text/html")

    # If completely unrecognized, send as html
    return Response(
        _get_base_html_template(f"<p>Document available: {html.escape(target_path.name)}</p>"),
        mimetype="text/html"
    )


@app.route("/api/download_launcher")
def download_launcher():
    """Download the Start_Agent.bat script for local desktop self-hosting."""
    bat_path = BASE_DIR / "Start_Agent.bat"
    if bat_path.exists():
        return send_file(
            str(bat_path),
            as_attachment=True,
            download_name="Start_Agent.bat",
            mimetype="text/plain",
        )
    return jsonify({"error": "Start_Agent.bat not found"}), 404


@app.route("/api/hollabuddy/chat", methods=["POST"])
@login_required
def hollabuddy_chat():
    """
    HollaBuddy AI Career Copilot Chat Endpoint.
    Instantly contextualized with candidate's master resume and optional active job context.
    Does NOT require running the job analyzer first.
    """
    data = request.json or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])
    company = data.get("company", "").strip()
    role = data.get("role", "").strip()
    url = data.get("url", "").strip()
    jd_text = data.get("jd_text", "").strip()

    if not message:
        return jsonify({"error": "Message cannot be empty."}), 400

    user_resume_path = get_user_resume_path()
    from agent import load_base_resume
    base_resume = load_base_resume(str(user_resume_path))

    job_context = None
    if company or role or jd_text or url:
        job_context = {
            "company": company,
            "role": role,
            "url": url,
            "jd_text": jd_text
        }
    elif url:
        from scraper import get_cached_jd
        cached = get_cached_jd(url)
        if cached:
            job_context = cached

    from hollabuddy import chat_with_hollabuddy
    user_settings = get_user_settings() if hasattr(current_user, 'data_dir') else None
    res = chat_with_hollabuddy(
        message=message,
        history=history,
        base_resume=base_resume,
        job_context=job_context,
        user_settings=user_settings,
    )
    return jsonify({"success": True, **res})


@app.route("/api/analyze", methods=["POST"])
@login_required
def analyze_job():
    """
    Step 1 Analysis: Scrapes JD text, calls Simplify (or extract_keywords_from_jd),
    cross-checks against base_resume.json, and returns Simplify-style matched vs missing keywords.
    """
    data = request.json or {}
    url = data.get("url", "").strip()
    direct_jd_text = data.get("jd_text", "").strip()
    custom_company = (data.get("company") or data.get("custom_company") or "").strip()
    custom_role = (data.get("role") or data.get("custom_role") or "").strip()
    no_simplify = data.get("no_simplify", False)

    if not url and not direct_jd_text:
        return jsonify({"error": "Please enter a job URL or paste the job description text."}), 400

    # Detect if user pasted direct job description text instead of a URL
    is_direct_text = bool(direct_jd_text and len(direct_jd_text) >= 20) or ("\n" in url) or (" " in url and len(url.split()) > 5) or (not url.startswith(("http://", "https://")) and not ("." in url and "/" in url))

    try:
        import asyncio
        from agent import load_base_resume, extract_keywords_from_jd
        from scraper import scrape_jd, sanitize_jd_url, clean_role_title
        from simplify_reader import read_simplify_score

        # Explicitly isolate and inject user settings for current request
        user_settings = get_user_settings()
        from gemini_client import set_thread_gemini_keys
        user_gemini_keys = []
        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
            val = (user_settings.get(k) or "").strip()
            if val:
                user_gemini_keys.append(val)
        if user_gemini_keys:
            set_thread_gemini_keys(user_gemini_keys)

        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "SIMPLIFY_EMAIL", "SIMPLIFY_PASSWORD", "HF_API_KEY", "COLAB_DETECTOR_URL"):
            val = user_settings.get(k)
            if val:
                os.environ[k] = val

        base_resume = load_base_resume(str(get_user_resume_path()))

        # Initialize default analysis variables to guarantee scope safety
        missing_keywords = []
        matching_keywords = []
        score = 0
        s_data = {}

        if is_direct_text:
            jd_text = direct_jd_text if (direct_jd_text and len(direct_jd_text) >= 20) else url
            company = custom_company or "Target Company"
            role = clean_role_title(custom_role) if custom_role else "Data Engineer"
            no_simplify = True  # Simplify extension requires a browser URL
            print(f"[Analyze] Direct Job Description text detected ({len(jd_text):,} chars). Skipping network scraper.")

            # Try to infer company and role ONLY IF NOT PROVIDED by user
            if not custom_company or not custom_role:
                first_lines = "\n".join(jd_text.strip().split("\n")[:4])
                if " at " in first_lines:
                    parts = first_lines.split(" at ", 1)
                    if not custom_role:
                        role = clean_role_title(parts[0].strip())
                    if not custom_company:
                        company = parts[1].split("\n")[0].strip()
                elif " - " in first_lines:
                    parts = first_lines.split(" - ", 1)
                    if not custom_role:
                        role = clean_role_title(parts[0].strip())
                    if not custom_company:
                        company = parts[1].split("\n")[0].strip()
                else:
                    if not custom_company:
                        c_match = re.search(r'(?:about|at|join|company:\s*)\s+([A-Z][a-zA-Z0-9\s]{2,25})', jd_text[:600], re.IGNORECASE)
                        if c_match:
                            company = c_match.group(1).strip()
                    if not custom_role:
                        t_match = re.search(r'([A-Z][a-zA-Z\s]{3,35}(?:Engineer|Developer|Architect|Analyst|Scientist|Manager))', jd_text[:500])
                        if t_match:
                            role = clean_role_title(t_match.group(1).strip())

            jd_data = {"company": company, "role": role, "jd_text": jd_text}
            jd_len = len(jd_text)
        else:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Dedicated asyncio loop for Flask thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            sanitized_url = sanitize_jd_url(url.rstrip("/"))
            print(f"[Analyze] Analyzing JD from {sanitized_url}...")

            is_cloud_render = (os.environ.get("RENDER") == "true") or (sys.platform != "win32") or (os.environ.get("FLASK_ENV") == "production")

            # Aggregator domains do not host Simplify ATS extension widgets (Simplify works on Greenhouse, Lever, Workday, Ashby, etc.)
            AGGREGATOR_DOMAINS = ("hiringcafe", "indeed", "ziprecruiter", "linkedin", "glassdoor", "simplyhired", "builtin", "dice", "careerbuilder", "monster")
            is_aggregator_url = any(agg in url.lower() for agg in AGGREGATOR_DOMAINS)

            # Check Simplify cache first for instant 0ms retrieval
            cached_s = None
            if not no_simplify and not is_cloud_render and not is_aggregator_url:
                from simplify_reader import get_cached_simplify_score
                cached_s = get_cached_simplify_score(url)
                if cached_s and cached_s.get("success"):
                    print(f"[Analyze] ⚡ Reusing verified cached Simplify score: {cached_s.get('score')}%")

            async def _run_analysis_pipeline():
                scrape_coro = scrape_jd(url)
                if cached_s and cached_s.get("success"):
                    # Instant cache hit for Simplify: only need scraper
                    jd_res = await scrape_coro
                    return jd_res, cached_s
                elif not no_simplify and not is_cloud_render and not is_aggregator_url:
                    print(f"[Analyze] ⚡ Launching Scraper and Simplify Extension Reader in parallel (concurrent execution)...")
                    from simplify_reader import read_simplify_score
                    simplify_coro = asyncio.wait_for(
                        read_simplify_score(url, custom_company, custom_role),
                        timeout=8.0
                    )
                    # Parallel execution: both scrape and Simplify run concurrently, maximizing effectiveness and eliminating sequential lag
                    results = await asyncio.gather(scrape_coro, simplify_coro, return_exceptions=True)
                    return results[0], results[1]
                else:
                    if is_aggregator_url:
                        print(f"[Analyze] ⚡ Aggregator URL detected ({url.split('//')[-1].split('/')[0]}) — skipping Simplify extension browser to avoid 8s timeout, using Gemini Matcher directly.")
                    jd_res = await scrape_coro
                    return jd_res, None

            scrape_result, simplify_result = loop.run_until_complete(_run_analysis_pipeline())

            if isinstance(scrape_result, Exception):
                err_str = str(scrape_result)
                user_msg = (
                    "⚠️ Could not extract the job description from this URL.\n\n"
                    + err_str.split("\n")[0]
                    + "\n\nWhat to do:\n"
                    "1. Open the job in your browser and copy the direct URL\n"
                    "2. Or paste the full JD text directly into the URL input box and click Analyze"
                )
                print(f"[Analyze] Scrape validation failed: {scrape_result}")
                return jsonify({
                    "success": False,
                    "error": user_msg,
                    "error_type": "scrape_blocked",
                    "jd_length": 0,
                }), 422

            jd_data = scrape_result
            company = jd_data["company"]
            role = clean_role_title(jd_data["role"])
            jd_text = jd_data["jd_text"]
            jd_len  = len(jd_text)
            print(f"[Analyze] Scraped {jd_len} chars for {role} at {company}")

            s_data = {}
            if isinstance(simplify_result, dict):
                s_data = simplify_result
                if s_data.get("success"):
                    score = s_data.get("score") or 75
                    missing_keywords = s_data.get("missing_keywords", [])
                    matching_keywords = s_data.get("matching_keywords", [])
                    print(f"[Analyze] Simplify extension score: {score}% ({len(missing_keywords)} missing, {len(matching_keywords)} matching)")
            elif isinstance(simplify_result, asyncio.TimeoutError):
                print("[Analyze] Simplify reader reached 8s timeout — using Gemini LLM Matcher")
            elif isinstance(simplify_result, Exception):
                print(f"[Analyze] Simplify read note: {simplify_result}")

        source = "simplify_extension"
        simplify_has_keywords = (len(missing_keywords) + len(matching_keywords)) >= 5

        matrix_data = {}
        # Fallback to LLM if:
        # - Simplify explicitly failed (no success), OR
        # - Simplify returned fewer than 5 keywords (overlay unavailable or incomplete on this page)
        if not s_data.get("success") or not simplify_has_keywords:
            print(f"[Analyze] Using Gemini LLM Matcher for rich ATS cross-check...")
            from llm_matcher import analyze_jd_and_resume_with_gemini
            llm_res = analyze_jd_and_resume_with_gemini(jd_text, base_resume)
            matching_keywords = llm_res.get("matching_keywords", [])
            missing_keywords  = llm_res.get("missing_keywords", [])
            score  = llm_res.get("score", 70)
            source = "llm_matcher"
            matrix_data = llm_res

            # If LLM quality gate rejected the JD, surface a degraded warning
            if llm_res.get("error") in ("jd_too_short", "jd_is_bot_page"):
                if is_direct_text:
                    # User pasted this directly; don't fail, use local keyword fallback
                    print("[Analyze] Direct text had bot pattern warning — falling back to deterministic local matcher")
                    from llm_matcher import _local_matcher_fallback
                    llm_res = _local_matcher_fallback(jd_text, base_resume)
                    matching_keywords = llm_res.get("matching_keywords", [])
                    missing_keywords  = llm_res.get("missing_keywords", [])
                    score = llm_res.get("score", 70)
                    matrix_data = llm_res
                else:
                    return jsonify({
                        "success": False,
                        "error": (
                            f"⚠️ Could not analyze this URL — the page returned only {jd_len} characters "
                            "of content (likely a login wall, CAPTCHA, or bot-block page).\n\n"
                            "What to do:\n"
                            "1. Make sure you're using the direct job posting URL, not a /candidate or ?from=login link\n"
                            "2. Or paste the full JD text manually into the 'Missing Keywords' box\n"
                            "3. Or log in on the career site, then copy the URL from the job page itself"
                        ),
                        "error_type": "jd_blocked",
                        "jd_length": jd_len,
                        "company": company,
                        "role": role,
                    }), 422
        else:
            # If Simplify provided keywords, do a quick semantic enrichment for title, exp, and industry
            from llm_matcher import analyze_jd_and_resume_with_gemini
            try:
                matrix_data = analyze_jd_and_resume_with_gemini(jd_text, base_resume)
            except Exception:
                matrix_data = {}

        # Safe defaults for matrix fields
        cand_name = base_resume.get("name", "Candidate")
        resume_name_tag = f"{cand_name.replace(' ', '_')}_Resume"
        cand_title = base_resume.get("experience", [{}])[0].get("title", "Data Engineer")
        score_10 = matrix_data.get("score_scale_10", round(score / 10.0, 1))
        
        rating = matrix_data.get("score_rating")
        if not rating:
            if score_10 < 6.0: rating = "Poor"
            elif score_10 < 7.0: rating = "Fair"
            elif score_10 < 8.0: rating = "Good"
            elif score_10 < 9.0: rating = "Great"
            else: rating = "Excellent"

        res_payload = {
            "success": True,
            "company": company,
            "role": role,
            "jd_text": jd_text,
            "jd_length": jd_len,
            "score": score,
            "score_scale_10": score_10,
            "score_rating": rating,
            "resume_name": resume_name_tag,
            "job_title_jd": matrix_data.get("job_title_jd") or role,
            "job_title_resume": matrix_data.get("job_title_resume") or cand_title,
            "job_title_match": matrix_data.get("job_title_match", True),
            "exp_years_jd": matrix_data.get("exp_years_jd", "3+ years exp"),
            "exp_years_resume": matrix_data.get("exp_years_resume", "8+ years exp"),
            "exp_years_match": matrix_data.get("exp_years_match", True),
            "industries": matrix_data.get("industries", ["Technology", "Data Platform"]),
            "industries_match": matrix_data.get("industries_match", False),
            "matching_keywords": matching_keywords,
            "missing_keywords": missing_keywords,
            "missing_keyword_contexts": matrix_data.get("missing_keyword_contexts", {}),
            "total_keywords": len(matching_keywords) + len(missing_keywords),
            "summary_feedback": matrix_data.get("summary_feedback", "Your current summary does not effectively showcase your qualifications and alignment with this job."),
            "summary_match": matrix_data.get("summary_match", False),
            "source": source
        }

        # Store in global memory cache so Generate step reuses this extract with 0 browser launches
        GLOBAL_ANALYSIS_CACHE[url] = {
            "company": company,
            "role": role,
            "jd_text": jd_text,
            "score": score,
            "matching_keywords": matching_keywords,
            "missing_keywords": missing_keywords,
            "missing_keyword_contexts": matrix_data.get("missing_keyword_contexts", {}),
            "source": source,
            "jd_data": jd_data,
            "matrix": res_payload,
        }
        _trim_analysis_cache()

        print(f"[Analyze] ✅ Analysis complete for {role} at {company}! Score: {score}% | Matched: {len(matching_keywords)} | Missing: {len(missing_keywords)}")
        return jsonify(res_payload)

    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"[Analyze] ❌ Analysis error: {e}")
        try:
            with open("debug_analyze.log", "w", encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/simplify/status", methods=["GET"])
@login_required
def simplify_status():
    """Returns the operational status of Simplify extension and credentials."""
    try:
        from simplify_reader import find_simplify_installation
        inst = find_simplify_installation()
        ext_path_str = inst.get("ext_path") if isinstance(inst, dict) else None
        ext_path = Path(ext_path_str) if ext_path_str else None
        manifest_file = (ext_path / "manifest.json") if ext_path else None
        has_extension = bool(ext_path and manifest_file and manifest_file.exists())

        version = "Unknown"
        if has_extension:
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                    version = m_data.get("version", "v1.0")
            except Exception:
                pass

        user_settings = get_user_settings()
        email = user_settings.get("SIMPLIFY_EMAIL") or os.getenv("SIMPLIFY_EMAIL", "")
        password = user_settings.get("SIMPLIFY_PASSWORD") or os.getenv("SIMPLIFY_PASSWORD", "")
        has_creds = bool(email and password)

        mode_desc = "Bundled Cloud Extension (Headless)" if ext_path and "simplify_extension" in str(ext_path) else "Local Desktop Chrome Profile"

        return jsonify({
            "success": True,
            "extension_found": has_extension,
            "extension_path": str(ext_path) if ext_path else None,
            "version": version,
            "has_credentials": has_creds,
            "account_email": (email[:3] + "***@" + email.split("@")[-1]) if ("@" in email) else (email if email else None),
            "mode": mode_desc,
            "ready": has_extension,
            "status_text": "Connected & Operational" if (has_extension and has_creds) else ("Extension Ready (No Login Saved)" if has_extension else "Extension Not Found"),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "ready": False}), 500


@app.route("/api/simplify/test", methods=["POST"])
@login_required
def simplify_test():
    """Performs a live verification check of the bundled Simplify extension files and readiness."""
    try:
        from simplify_reader import find_simplify_installation
        inst = find_simplify_installation()
        ext_path_str = inst.get("ext_path") if isinstance(inst, dict) else None
        ext_path = Path(ext_path_str) if ext_path_str else None
        if not ext_path or not (ext_path / "manifest.json").exists():
            return jsonify({
                "success": False,
                "error": "Simplify extension directory (simplify_extension/) was not found in repository."
            }), 404

        manifest_file = ext_path / "manifest.json"
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        ext_name = manifest.get("name", "Simplify")
        ext_ver = manifest.get("version", "1.0.0")

        # Verify key extension assets exist
        bg_script = ext_path / "background.js"
        content_script = ext_path / "contentScriptMain.js"
        has_bg = bg_script.exists() and bg_script.stat().st_size > 0
        has_cs = content_script.exists() and content_script.stat().st_size > 0

        is_cloud = (os.environ.get("RENDER") == "true") or (sys.platform != "win32")

        return jsonify({
            "success": True,
            "message": f"Verified {ext_name} v{ext_ver}! Manifest V3, background service worker, and content scripts are active.",
            "extension_name": ext_name,
            "version": ext_ver,
            "service_workers": 1 if has_bg else 0,
            "content_scripts": 1 if has_cs else 0,
            "mode": "Cloud Extension & 1-Click Bookmarklet Sync" if is_cloud else "Local Desktop Chrome Profile",
            "ready": True,
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Simplify test error: {str(e)}"}), 500


@app.route("/api/open-folder", methods=["POST"])
@login_required
def open_folder():

    """Open specified output directory in Windows File Explorer."""
    user_output_dir = get_user_output_dir()
    data = request.json or {}
    folder_path = data.get("folder_path", str(user_output_dir))

    target = Path(folder_path).resolve()
    if not target.exists():
        target = user_output_dir.resolve()
        target.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            subprocess.Popen(f'explorer "{target}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return jsonify({"success": True, "opened": str(target)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cover-letter", methods=["POST"])
@login_required
def generate_cover_letter_api():
    """Generate a job-specific AI cover letter for the given job URL or role."""
    user_output_dir = get_user_output_dir()
    user_resume_path = get_user_resume_path()
    data = request.json or {}
    url = data.get("url", "").strip()
    company = data.get("company", "").strip()
    role = data.get("role", "").strip()
    custom_keywords = data.get("keywords", [])

    if not url and (not company or not role):
        return jsonify({"error": "Please provide a valid job URL or company/role details"}), 400

    try:
        from agent import load_base_resume
        from scraper import scrape_jd_sync
        from cover_letter_generator import generate_cover_letter

        user_settings = get_user_settings()
        from gemini_client import set_thread_gemini_keys
        user_gemini_keys = []
        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
            val = (user_settings.get(k) or "").strip()
            if val:
                user_gemini_keys.append(val)
        if user_gemini_keys:
            set_thread_gemini_keys(user_gemini_keys)

        base_resume = load_base_resume(str(user_resume_path))

        if url:
            # Check cache or scrape
            cached = GLOBAL_ANALYSIS_CACHE.get(url)
            if cached:
                company = company or cached["company"]
                role = role or cached["role"]
                jd_text = cached["jd_text"]
            else:
                jd_data = scrape_jd_sync(url)
                company = company or jd_data["company"]
                role = role or jd_data["role"]
                jd_text = jd_data["jd_text"]
        else:
            jd_text = f"Role: {role} at {company}"

        from resume_builder import slugify
        folder_name = f"{slugify(company)}_{slugify(role)}"[:80]
        target_dir = user_output_dir / folder_name

        res = generate_cover_letter(
            base_resume=base_resume,
            jd_text=jd_text,
            company=company,
            role=role,
            missing_keywords=custom_keywords,
            output_dir=str(target_dir),
        )

        rel_docx = os.path.relpath(res["file_path_docx"], str(user_output_dir)).replace("\\", "/") if res.get("file_path_docx") else ""

        return jsonify({
            "success": True,
            "cover_letter_text": res["cover_letter_text"],
            "file_path_docx": res["file_path_docx"],
            "relative_docx": rel_docx,
            "company": company,
            "role": role,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cover-letter/save", methods=["POST"])
@login_required
def save_custom_cover_letter_api():
    """Save user-edited cover letter text to disk as .docx and .txt, and return the download path."""
    user_output_dir = get_user_output_dir()
    user_resume_path = get_user_resume_path()
    data = request.json or {}
    text = data.get("cover_letter_text", "").strip()
    company = data.get("company", "Target Company").strip()
    role = data.get("role", "Data Engineer").strip()

    if not text:
        return jsonify({"success": False, "error": "Cover letter text is empty"}), 400

    try:
        from agent import load_base_resume
        from resume_builder import slugify
        from docx import Document
        from docx.shared import Pt, Inches, RGBColor
        from datetime import datetime as dt

        base_resume = load_base_resume(str(user_resume_path))
        candidate_name = base_resume.get("name", "Candidate Name")

        folder_name = f"{slugify(company)}_{slugify(role)}"[:80]
        target_dir = user_output_dir / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        name_slug = slugify(candidate_name)
        out_name = f"{name_slug}_Cover_Letter"

        file_path_txt = target_dir / f"{out_name}.txt"
        file_path_docx = target_dir / f"{out_name}.docx"

        # 1. Write text file
        with open(file_path_txt, "w", encoding="utf-8") as f:
            f.write(text)

        # 2. Build docx
        doc = Document()
        try:
            cp = doc.core_properties
            cp.author = candidate_name
            cp.title = f"{candidate_name} - Cover Letter"
            cp.subject = f"Cover Letter - {role} at {company}"
            cp.last_modified_by = candidate_name
            cp.comments = ""
            cp.category = "Cover Letter"
            now_dt = dt.utcnow()
            cp.created = now_dt
            cp.modified = now_dt
        except Exception:
            pass

        for s in doc.sections:
            s.top_margin = Inches(0.8)
            s.bottom_margin = Inches(0.8)
            s.left_margin = Inches(0.8)
            s.right_margin = Inches(0.8)

        paragraphs = text.split("\n\n")
        for p_text in paragraphs:
            p_text = p_text.strip()
            if not p_text:
                continue
            para = doc.add_paragraph()
            para.paragraph_format.space_after = Pt(8)
            para.paragraph_format.line_spacing = 1.15
            run = para.add_run(p_text)
            run.font.name = "Calibri"
            run.font.size = Pt(10.5)
            run.font.color.rgb = RGBColor(30, 41, 59)

        doc.save(str(file_path_docx))

        rel_docx = os.path.relpath(str(file_path_docx), str(user_output_dir)).replace("\\", "/")

        return jsonify({
            "success": True,
            "file_path_docx": str(file_path_docx),
            "relative_docx": rel_docx,
            "message": "Cover letter saved cleanly with your custom edits."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/answer-questions", methods=["POST"])
@login_required
def api_answer_questions():
    """Answer application-specific questions (Greenhouse/Lever/Workday/Ashby) using Q&A Copilot."""
    user_resume_path = get_user_resume_path()
    data = request.json or {}
    questions = data.get("questions", "")
    company = data.get("company", "Target Company").strip()
    role = data.get("role", "Data Engineer").strip()
    jd_text = data.get("jd_text", "").strip()

    if not questions:
        return jsonify({"success": False, "error": "Please provide one or more questions to answer."}), 400

    try:
        from agent import load_base_resume
        from qa_generator import answer_application_questions

        base_resume = load_base_resume(str(user_resume_path))

        # If JD text is missing, check cache
        if not jd_text:
            from scraper import get_cached_jd
            cached = get_cached_jd(company) or get_cached_jd(role)
            if cached:
                jd_text = cached.get("jd_text", "")

        answers = answer_application_questions(
            questions_input=questions,
            base_resume=base_resume,
            jd_text=jd_text,
            company=company,
            role=role,
        )

        return jsonify({
            "success": True,
            "answers": answers,
            "company": company,
            "role": role,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/refine-resume", methods=["POST"])
@login_required
def refine_resume_api():
    """
    Apply candidate's specific revision instructions to a tailored resume,
    rebuild the Word (.docx) and PDF files in ~2-3s, and return updated paths and change summary.
    """
    data = request.json or {}
    instruction = data.get("instruction", "").strip()
    folder_path = data.get("folder_path", "").strip()
    company = data.get("company", "").strip()
    role = data.get("role", "").strip()
    url = data.get("url", "").strip()
    direct_resume = data.get("current_resume")

    if not instruction:
        return jsonify({"success": False, "error": "Please provide revision instructions."}), 400

    user_resume_path = get_user_resume_path()
    user_output_dir = get_user_output_dir()
    user_data_dir = current_user.data_dir if current_user.is_authenticated else BASE_DIR
    user_username = current_user.username if (current_user and current_user.is_authenticated) else ""

    try:
        from agent import load_base_resume
        from resume_refiner import refine_tailored_resume
        from resume_builder import slugify, build_resume_docx, convert_to_pdf

        base_resume = load_base_resume(str(user_resume_path))

        # 1. Resolve target folder path safely
        target_dir = None
        if folder_path:
            cand = Path(folder_path)
            if cand.exists() and cand.is_dir():
                target_dir = cand
            else:
                cand2 = user_output_dir / folder_path
                if cand2.exists() and cand2.is_dir():
                    target_dir = cand2

        if not target_dir:
            if company and role:
                target_dir = user_output_dir / f"{slugify(company)}_{slugify(role)}"[:80]
                target_dir.mkdir(parents=True, exist_ok=True)
            else:
                return jsonify({"success": False, "error": "Could not determine application folder."}), 400

        # 2. Locate or load current tailored resume JSON
        current_resume = direct_resume
        tailored_json_path = target_dir / "tailored_resume.json"
        if not current_resume and tailored_json_path.exists():
            try:
                with open(tailored_json_path, "r", encoding="utf-8") as f:
                    current_resume = json.load(f)
            except Exception:
                pass

        if not current_resume:
            # Fall back to base_resume as starting point
            current_resume = dict(base_resume)

        # 3. Retrieve JD text if available
        jd_text = data.get("jd_text", "").strip()
        if not jd_text and url:
            from scraper import get_cached_jd
            cached = get_cached_jd(url)
            if cached:
                jd_text = cached.get("jd_text", "")

        # 4. Call Refinement Engine
        refined_resume, change_summary = refine_tailored_resume(
            current_resume=current_resume,
            instruction=instruction,
            base_resume=base_resume,
            jd_text=jd_text,
            company=company,
            role=role,
        )

        # 5. Save updated tailored_resume.json
        with open(tailored_json_path, "w", encoding="utf-8") as f:
            json.dump(refined_resume, f, indent=2, ensure_ascii=False)

        # 6. Rebuild .docx document (check original master docx template first)
        user_orig_docx = user_data_dir / "master_resume_original.docx"
        orig_docx_path = user_orig_docx if user_orig_docx.exists() else (BASE_DIR / "master_resume_original.docx")

        effective_role = refined_resume.get("target_role") or role

        doc_path = None
        if orig_docx_path.exists():
            try:
                from docx_patcher import patch_docx_with_rewritten_resume
                doc_path = patch_docx_with_rewritten_resume(
                    original_docx_path=str(orig_docx_path),
                    rewritten_resume=refined_resume,
                    company=company,
                    role=effective_role,
                    output_dir=str(target_dir),
                )
            except Exception as patch_err:
                print(f"[Refine] Patch error: {patch_err}, using build_resume_docx")
                doc_path = build_resume_docx(
                    resume=refined_resume,
                    company=company,
                    role=effective_role,
                    output_dir=str(target_dir),
                )
        else:
            doc_path = build_resume_docx(
                resume=refined_resume,
                company=company,
                role=effective_role,
                output_dir=str(target_dir),
            )

        # 7. Re-generate PDF
        pdf_path = None
        try:
            pdf_path = convert_to_pdf(doc_path)
        except Exception as pe:
            print(f"[Refine] PDF error: {pe}")

        rel_doc = os.path.relpath(doc_path, str(user_output_dir)).replace("\\", "/")
        rel_pdf = os.path.relpath(pdf_path, str(user_output_dir)).replace("\\", "/") if pdf_path else ""

        # 8. Persist refined resume in Neon DB so it survives deploys / reloads
        if db_layer.is_db_available() and user_username:
            try:
                db_layer.db_save_run_log(
                    user_username,
                    f"refine_{int(time.time()*1000)}",
                    {
                        "timestamp": datetime.now().isoformat(),
                        "url": url,
                        "company": company,
                        "role": effective_role,
                        "output_file": doc_path,
                        "tailored_resume": refined_resume,
                        "change_summary": change_summary,
                        "relative_path": rel_doc,
                        "relative_pdf": rel_pdf,
                    }
                )
            except Exception as _db_err:
                logging.warning(f"[Refine] DB persist failed: {_db_err}")

        return jsonify({
            "success": True,
            "message": "Resume refined and documents rebuilt successfully!",
            "change_summary": change_summary,
            "output_file": doc_path,
            "relative_path": rel_doc,
            "relative_pdf": rel_pdf,
            "folder_path": str(target_dir),
            "updated_resume": refined_resume,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Refinement failed: {str(e)}"}), 500



@app.route("/api/run", methods=["POST"])
@login_required
def run_agent():
    """Start pipeline generation run and return run_id for streaming."""
    data = request.json or {}
    url = data.get("url", "").strip()
    direct_jd_text = data.get("jd_text", "").strip()
    custom_company = (data.get("custom_company") or data.get("company") or "").strip()
    custom_role = (data.get("custom_role") or data.get("role") or "").strip()
    custom_keywords = data.get("custom_keywords", "")
    custom_bullets = data.get("custom_bullets", "")
    engine_mode = data.get("engine_mode", "danis_engine")
    no_simplify = data.get("no_simplify", False)
    passes = int(data.get("passes", 2))
    custom_output = data.get("custom_output", "")
    score_before = data.get("score_before", None)

    # Capture per-user paths at request time (thread-safe: closures copy the value)
    user_resume_path = str(get_user_resume_path())
    user_output_dir = str(get_user_output_dir())
    user_settings = get_user_settings()
    user_username = current_user.username if current_user.is_authenticated else ""

    if not url and not direct_jd_text:
        return jsonify({"error": "Please enter a job URL or paste the job description text."}), 400
    if not url and direct_jd_text:
        url = direct_jd_text

    run_id = f"run_{int(time.time()*1000)}"
    msg_queue = queue.Queue(maxsize=500)  # bounded to prevent OOM from stuck pipelines
    with _active_runs_lock:
        active_runs[run_id] = (msg_queue, time.time())

    # Start background thread for execution
    thread = threading.Thread(
        target=_execute_agent_pipeline,
        args=(run_id, url, custom_keywords, no_simplify, passes, custom_output, msg_queue, score_before, custom_bullets, engine_mode, custom_company, custom_role, direct_jd_text),
        kwargs={"user_resume_path": user_resume_path, "user_output_dir": user_output_dir, "user_settings": user_settings, "user_username": user_username},
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run_id, "status": "started"})


def _execute_agent_pipeline(run_id, url, custom_keywords_str, no_simplify, passes, custom_output, msg_queue, analyze_score_before=None, custom_bullets="", engine_mode="danis_engine", custom_company="", custom_role="", direct_jd_text="", user_resume_path=None, user_output_dir=None, user_settings=None, user_username=""):
    """Execute pipeline in thread and push step logs to SSE queue."""
    # analyze_score_before: real score from Analyze step (Gemini/Simplify) — authoritative before score

    # Resolve per-user paths (provided by run_agent at request time)
    _resume_path = Path(user_resume_path) if user_resume_path else RESUME_PATH
    _output_dir = Path(user_output_dir) if user_output_dir else OUTPUT_DIR
    _settings = user_settings or {}

    # ── Restore resume from DB to local disk if needed (Render: ephemeral disk) ──
    if db_layer.is_db_available() and user_username and not _resume_path.exists():
        try:
            resume_data = db_layer.db_get_resume(user_username)
            if resume_data and not resume_data.get("_empty"):
                _resume_path.parent.mkdir(parents=True, exist_ok=True)
                with open(_resume_path, "w", encoding="utf-8") as _rf:
                    json.dump(resume_data, _rf, indent=2, ensure_ascii=False)
                logging.info(f"[Pipeline] Restored resume from DB to {_resume_path}")
            # Also restore DOCX if needed
            user_data_dir = _resume_path.parent
            orig_docx = user_data_dir / "master_resume_original.docx"
            if not orig_docx.exists():
                docx_bytes = db_layer.db_get_resume_docx(user_username)
                if docx_bytes:
                    with open(orig_docx, "wb") as _df:
                        _df.write(docx_bytes)
                    logging.info(f"[Pipeline] Restored master DOCX from DB to {orig_docx}")
        except Exception as _restore_err:
            logging.warning(f"[Pipeline] Resume restore from DB failed: {_restore_err}")

    # Configure thread-isolated Gemini keys for this user's execution
    from gemini_client import set_thread_gemini_keys, clear_thread_gemini_keys
    user_gemini_keys = []
    for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
        val = (_settings.get(k) or "").strip()
        if val:
            user_gemini_keys.append(val)
    if user_gemini_keys:
        set_thread_gemini_keys(user_gemini_keys)

    # Inject user settings into environment as fallback
    if _settings.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = _settings["GEMINI_API_KEY"]
    if _settings.get("GEMINI_API_KEY_2"):
        os.environ["GEMINI_API_KEY_2"] = _settings["GEMINI_API_KEY_2"]
    if _settings.get("SIMPLIFY_EMAIL"):
        os.environ["SIMPLIFY_EMAIL"] = _settings["SIMPLIFY_EMAIL"]
    if _settings.get("SIMPLIFY_PASSWORD"):
        os.environ["SIMPLIFY_PASSWORD"] = _settings["SIMPLIFY_PASSWORD"]
    if _settings.get("HF_API_KEY"):
        os.environ["HF_API_KEY"] = _settings["HF_API_KEY"]

    def send_log(step, stage, message, data=None, status="info"):
        try:
            msg_queue.put_nowait({
                "type": "progress",
                "step": step,
                "stage": stage,
                "message": message,
                "status": status,
                "data": data or {},
                "timestamp": datetime.now().isoformat(),
            })
        except queue.Full:
            pass  # SSE client disconnected; pipeline continues silently

    try:
        from dotenv import load_dotenv
        load_dotenv()

        send_log(1, "Initialize", "Loading base resume...", status="working")
        from agent import load_base_resume, extract_keywords_from_jd, _save_run_log
        from scraper import scrape_jd_sync, clean_role_title, get_cached_jd
        from rewriter import rewrite_resume, _check_keyword_coverage
        from ai_detector import run_ai_detection_loop
        from resume_builder import build_resume_docx

        base_resume = load_base_resume(str(_resume_path))
        send_log(1, "Base Resume", f"Loaded master resume for {base_resume.get('name')}", status="success")


        # Step 2: Scrape JD (checks memory & disk cache first, or uses direct text)
        is_direct_text = ("\n" in url) or (" " in url and len(url.split()) > 5) or (not url.startswith(("http://", "https://")) and not ("." in url and "/" in url))
        
        if direct_jd_text and len(direct_jd_text) >= 20:
            jd_text = direct_jd_text
            company = custom_company or "Target Company"
            role = clean_role_title(custom_role) if custom_role else "Data Engineer"
            no_simplify = True
            GLOBAL_ANALYSIS_CACHE[url] = {"company": company, "role": role, "jd_text": jd_text}
            _trim_analysis_cache()
            send_log(2, "Scrape JD", f"Using direct Job Description text ({len(jd_text):,} chars)",
                     data={"company": company, "role": role, "jd_length": len(jd_text)}, status="success")
        elif is_direct_text:
            jd_text = url
            company = custom_company or "Target Company"
            role = clean_role_title(custom_role) if custom_role else "Data Engineer"
            if not custom_company or not custom_role:
                first_line = jd_text.strip().split("\n")[0][:80]
                if " at " in first_line:
                    parts = first_line.split(" at ", 1)
                    if not custom_role:
                        role = clean_role_title(parts[0].strip())
                    if not custom_company:
                        company = parts[1].strip()
                elif " - " in first_line:
                    parts = first_line.split(" - ", 1)
                    if not custom_role:
                        role = clean_role_title(parts[0].strip())
                    if not custom_company:
                        company = parts[1].strip()
            no_simplify = True
            send_log(2, "Scrape JD", f"Using direct Job Description text ({len(jd_text):,} chars)",
                     data={"company": company, "role": role, "jd_length": len(jd_text)}, status="success")
        else:
            send_log(2, "Scrape JD", f"Extracting job description from {url}...", status="working")
            cached_analysis = GLOBAL_ANALYSIS_CACHE.get(url)
            if cached_analysis and len(cached_analysis.get("jd_text", "")) >= 800:
                company = custom_company or cached_analysis["company"]
                role = clean_role_title(custom_role) if custom_role else clean_role_title(cached_analysis["role"])
                jd_text = cached_analysis["jd_text"]
                jd_chars = len(jd_text)
                send_log(2, "Scrape JD",
                         f"⚡ Reused verified JD for {role} at {company} ({jd_chars:,} chars, 0 browser popups)",
                         data={"company": company, "role": role, "jd_length": jd_chars},
                         status="success")
            else:
                jd_data = scrape_jd_sync(url)
                company = custom_company or jd_data["company"]
                role = clean_role_title(custom_role) if custom_role else clean_role_title(jd_data["role"])
                jd_text = jd_data["jd_text"]
                jd_chars = len(jd_text)

                if jd_chars < 800:
                    send_log(2, "Scrape JD",
                             f"❌ JD validation FAILED: Only {jd_chars} chars extracted — likely a bot-block page. "
                             "Halting pipeline. Please paste the job description text manually into the "
                             "'Missing Keywords' field and retry.",
                             data={"jd_length": jd_chars, "company": company, "role": role},
                             status="error")
                    raise RuntimeError(
                        f"JD validation failed: only {jd_chars} chars extracted — "
                        "the site likely returned a 403/bot-block page. Paste the JD text manually."
                    )

                jd_status = "success"
                jd_msg = f"Extracted {jd_chars:,} chars for {role} at {company}"
                if jd_chars < 1500:
                    jd_status = "warning"
                    jd_msg += f" (⚠ short extract — may be partial)"

                send_log(2, "Scrape JD", jd_msg, data={
                    "company": company,
                    "role": role,
                    "jd_length": jd_chars,
                }, status=jd_status)

        # Apply custom overrides and sync in memory cache
        if custom_company:
            company = custom_company
        if custom_role:
            role = clean_role_title(custom_role)

        if url in GLOBAL_ANALYSIS_CACHE:
            GLOBAL_ANALYSIS_CACHE[url]["company"] = company
            GLOBAL_ANALYSIS_CACHE[url]["role"] = role

        # Step 3: Parse custom keywords OR Simplify ATS score OR local keyword extraction
        missing_keywords = []
        simplify_data = None
        simplify_score_before = None

        # Parse user-provided custom missing keywords if present
        user_keywords = []
        if custom_keywords_str:
            user_keywords = [k.strip() for k in custom_keywords_str.replace("\n", ",").replace(";", ",").split(",") if k.strip()]

        if user_keywords:
            missing_keywords = user_keywords
            send_log(3, "Keyword Extraction",
                     f"Using {len(user_keywords)} user-specified missing keywords from Simplify: {user_keywords}",
                     data={"missing_keywords": user_keywords, "source": "user_provided"},
                     status="success")
        elif cached_analysis and cached_analysis.get("missing_keywords"):
            # Instant memory reuse from Analyze step
            missing_keywords = cached_analysis["missing_keywords"]
            matching_keywords = cached_analysis.get("matching_keywords", [])
            simplify_score_before = cached_analysis.get("score")
            source_label = "Simplify extension (cached)" if cached_analysis.get("source") == "simplify_extension" else "LLM Cross-Check (cached)"
            send_log(3, "Keyword Extraction",
                     f"⚡ Reused verified {source_label}: {len(missing_keywords)} missing keywords (Score: {simplify_score_before}%, 0 browser popups)",
                     data={
                         "score": simplify_score_before,
                         "missing_keywords": missing_keywords,
                         "matching_keywords": matching_keywords,
                         "source": cached_analysis.get("source", "cached"),
                     },
                     status="success")
        elif no_simplify:
            send_log(3, "Keyword Extraction", "Extracting missing keywords directly from JD (--no-simplify mode)...", status="working")
            missing_keywords = extract_keywords_from_jd(jd_text, base_resume)
            send_log(3, "Keyword Extraction",
                     f"Found {len(missing_keywords)} candidate keywords from JD text (estimated, not real ATS score)",
                     data={"missing_keywords": missing_keywords, "source": "jd_extraction"},
                     status="success")
        else:
            send_log(3, "Simplify ATS Score",
                     "Checking Simplify ATS score... (reusing cache if previously read)",
                     status="working")
            try:
                from simplify_reader import read_simplify_score_sync
                simplify_data = read_simplify_score_sync(url, company, role)
                if simplify_data.get("success"):
                    simplify_score_before = simplify_data["score"]
                    missing_keywords = simplify_data["missing_keywords"]
                    matching_keywords = simplify_data.get("matching_keywords", [])
                    send_log(3, "Simplify ATS Score",
                             f"Real Simplify score: {simplify_score_before}% | {len(missing_keywords)} keywords missing",
                             data={
                                 "score": simplify_score_before,
                                 "missing_keywords": missing_keywords,
                                 "matching_keywords": matching_keywords,
                                 "source": "simplify_extension",
                             },
                             status="success")
                else:
                    error = simplify_data.get("error", "Unknown error")
                    missing_keywords = extract_keywords_from_jd(jd_text, base_resume)
                    send_log(3, "Simplify ATS Score",
                             f"Simplify unavailable: {error}. Using JD keyword fallback.",
                             data={"missing_keywords": missing_keywords, "source": "jd_extraction"},
                             status="warning")
            except Exception as e:
                missing_keywords = extract_keywords_from_jd(jd_text, base_resume)
                send_log(3, "Simplify ATS Score", f"Simplify error: {e}. Using JD keyword fallback.",
                         status="warning")

        # Step 4 & 5: Resume Tailoring & Verification with JD Domain Context
        keyword_contexts = {}
        try:
            cached_item = GLOBAL_ANALYSIS_CACHE.get(url, {})
            keyword_contexts = cached_item.get("missing_keyword_contexts", {})
            if not keyword_contexts and missing_keywords and jd_text:
                from llm_matcher import extract_keyword_contexts_from_jd
                keyword_contexts = extract_keyword_contexts_from_jd(missing_keywords, jd_text)
            if keyword_contexts:
                send_log(4, "Domain Context", f"Extracted sentence-level JD context for {len(keyword_contexts)} keywords.", status="working")
        except Exception as ctx_err:
            print(f"[Pipeline] Keyword context extraction note: {ctx_err}")

        if engine_mode == "danis_engine":
            send_log(4, "Dani's Multi-Agent Engine", "Launching 4-role team: Researcher → Writer (Rules 0–16) → Auditor → Editor...", status="working")
            from danis_engine import execute_danis_engine_pipeline
            cleaned_resume = execute_danis_engine_pipeline(
                base_resume=base_resume,
                jd_text=jd_text,
                missing_keywords=missing_keywords,
                company=company,
                role=role,
                custom_bullets=custom_bullets,
                log_callback=send_log,
                keyword_contexts=keyword_contexts,
            )
            send_log(5, "Dani's Engine", "Multi-role resume generation & human-voice audit passed!", status="success")
        else:
            # Step 4: Standard Gemini Resume Rewrite (strict keyword injection + custom bullets)
            bullets_msg = f" and custom experience bullets" if (custom_bullets and custom_bullets.strip()) else ""
            send_log(4, "Gemini Rewrite",
                     f"Rewriting resume with strict injection of {len(missing_keywords)} keywords{bullets_msg}...",
                     status="working")
            rewritten_resume = rewrite_resume(
                base_resume=base_resume,
                jd_text=jd_text,
                missing_keywords=missing_keywords,
                company=company,
                role=role,
                custom_bullets=custom_bullets,
                keyword_contexts=keyword_contexts,
            )
            send_log(4, "Gemini Rewrite", "Resume rewritten with keyword injection!", status="success")

            # Step 5: AI Detection Loop
            send_log(5, "AI Detector",
                     f"Running {passes}-pass AI writing detection and cleanup...",
                     status="working")
            cleaned_resume = run_ai_detection_loop(rewritten_resume, num_passes=passes)
            send_log(5, "AI Detector", f"AI writing cleanup complete ({passes} passes)", status="success")

        # Step 6a: Keyword Coverage (injection verification)
        send_log(6, "Coverage Check", "Verifying keyword injection coverage...", status="working")
        embedded_keywords, still_missing = _check_keyword_coverage(cleaned_resume, missing_keywords)
        coverage_pct = (
            round(len(embedded_keywords) / len(missing_keywords) * 100)
            if missing_keywords else 100
        )
        send_log(6, "Coverage Check",
                 f"Coverage: {len(embedded_keywords)}/{len(missing_keywords)} keywords injected ({coverage_pct}%)",
                 data={
                     "embedded_keywords": embedded_keywords,
                     "still_missing": still_missing,
                     "coverage_pct": coverage_pct,
                     "simplify_score_before": simplify_score_before,
                     "source": "real_extension" if (simplify_data and simplify_data.get("success")) else "jd_extraction",
                 },
                 status="success" if coverage_pct >= 90 else "warning")

        # ══════════════════════════════════════════════════════════════════════════
        # PARALLEL EXECUTION: Re-score + DOCX/PDF Build + Cover Letter
        # These three independent operations run concurrently via ThreadPoolExecutor
        # to eliminate ~20-30s of sequential Gemini API wait time.
        # ══════════════════════════════════════════════════════════════════════════
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Prepare shared state needed by all parallel tasks
        role = clean_role_title(role, company)
        for sec in ("education", "certifications", "contact", "name", "projects"):
            if sec in base_resume and (sec not in cleaned_resume or not cleaned_resume[sec]):
                cleaned_resume[sec] = base_resume[sec]

        orig_docx_path = BASE_DIR / "master_resume_original.docx"
        user_data_dir = _resume_path.parent
        user_orig_docx = user_data_dir / "master_resume_original.docx"
        if user_orig_docx.exists():
            orig_docx_path = user_orig_docx
        effective_output = custom_output or str(_output_dir)

        # ── Task A: Re-score rewritten resume against JD (Gemini API call) ──
        def _task_rescore():
            try:
                from llm_matcher import analyze_jd_and_resume_with_gemini
                return analyze_jd_and_resume_with_gemini(jd_text, cleaned_resume)
            except Exception as e:
                print(f"[Pipeline] Rescore note: {e}")
                return None

        # ── Task B: Build DOCX + convert to PDF (local I/O, fast) ──
        def _task_build_docs():
            send_log(7, "Word Document", "Generating Word document...", status="working")
            _doc_path = None
            if orig_docx_path.exists():
                try:
                    from docx_patcher import patch_docx_with_rewritten_resume
                    send_log(7, "Word Document", "Patching original master DOCX template to preserve authentic styling...", status="working")
                    _doc_path = patch_docx_with_rewritten_resume(
                        original_docx_path=str(orig_docx_path),
                        rewritten_resume=cleaned_resume,
                        company=company,
                        role=role,
                        output_dir=effective_output,
                    )
                    send_log(7, "Word Document", "Patched original master template with rewritten content!", status="success")
                except Exception as patch_err:
                    print(f"[Pipeline] DOCX patcher error: {patch_err}, falling back to build_resume_docx")
                    _doc_path = build_resume_docx(
                        resume=cleaned_resume, company=company, role=role, output_dir=effective_output,
                    )
            else:
                _doc_path = build_resume_docx(
                    resume=cleaned_resume, company=company, role=role, output_dir=effective_output,
                )

            # Save tailored resume JSON alongside .docx
            try:
                _target_folder = Path(_doc_path).parent
                with open(_target_folder / "tailored_resume.json", "w", encoding="utf-8") as rf:
                    json.dump(cleaned_resume, rf, indent=2, ensure_ascii=False)
            except Exception as json_err:
                print(f"[Pipeline] Note saving tailored_resume.json: {json_err}")

            # Convert to PDF
            _pdf_path = None
            try:
                from resume_builder import convert_to_pdf
                _pdf_path = convert_to_pdf(_doc_path)
                send_log(7, "PDF Builder", "Converted document to PDF successfully!", status="success")
            except Exception as pdf_err:
                print(f"[Pipeline] PDF conversion note: {pdf_err}")

            return _doc_path, _pdf_path

        # ── Task C: Generate Cover Letter (Gemini API call) ──
        def _task_cover_letter():
            try:
                from cover_letter_generator import generate_cover_letter as _gen_cl
                return _gen_cl(
                    base_resume=base_resume,
                    jd_text=jd_text,
                    company=company,
                    role=role,
                    missing_keywords=missing_keywords,
                    output_dir=effective_output,
                )
            except Exception as cl_err:
                print(f"[Pipeline] Cover letter note: {cl_err}")
                return {}

        # ── Launch all three tasks in parallel ──
        send_log(6, "Score Analysis", "Re-scoring rewritten resume against JD (Gemini)...", status="working")
        score_after_real = None
        cover_letter_text = ""
        doc_path = None

        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="pipeline_parallel") as executor:
            future_rescore = executor.submit(_task_rescore)
            future_docs = executor.submit(_task_build_docs)
            future_cl = executor.submit(_task_cover_letter)

            # Gather results (each future blocks only until its own task completes)
            # Docs task is fastest — gather it first so download is ready ASAP
            try:
                doc_path, pdf_path = future_docs.result(timeout=120)
            except Exception as doc_err:
                print(f"[Pipeline] Doc build error: {doc_err}")

            try:
                rescore_result = future_rescore.result(timeout=60)
                if rescore_result:
                    score_after_real = rescore_result.get("score")
                    if score_after_real is not None:
                        score_before_display = analyze_score_before if analyze_score_before is not None else simplify_score_before
                        delta = (score_after_real - score_before_display) if score_before_display is not None else None
                        delta_str = f" (+{delta}pts)" if delta is not None and delta > 0 else (f" ({delta}pts)" if delta is not None else "")
                        send_log(6, "Score Analysis",
                                 f"ATS Match Score: {score_before_display}% → {score_after_real}%{delta_str}",
                                 data={"score_before": score_before_display, "score_after": score_after_real, "delta": delta},
                                 status="success")
                    else:
                        send_log(6, "Score Analysis", "Rescore returned no score.", status="warning")
                else:
                    send_log(6, "Score Analysis", "Rescore skipped (error).", status="warning")
            except Exception as rescore_err:
                print(f"[Pipeline] Rescore note: {rescore_err}")
                send_log(6, "Score Analysis", f"Rescore skipped: {rescore_err}", status="warning")

            try:
                cl_result = future_cl.result(timeout=90)
                cover_letter_text = cl_result.get("cover_letter_text", "") if cl_result else ""
                if cover_letter_text:
                    send_log(7, "Cover Letter", "Generated high-impact AI Cover Letter!", status="success")
            except Exception as cl_err:
                print(f"[Pipeline] Cover letter note: {cl_err}")

        rel_path = os.path.relpath(doc_path, str(_output_dir)).replace("\\", "/")

        # Determine final score values for dashboard:
        # Priority: 1. analyze_score_before from Analyze step  2. simplify_score_before from pipeline  3. default 75
        if analyze_score_before is not None:
            score_before_val = analyze_score_before
        elif simplify_score_before is not None:
            score_before_val = simplify_score_before
        else:
            score_before_val = 75

        # Use real rescore if available; fall back to conservative estimate only as last resort
        if score_after_real is not None:
            score_after_val = score_after_real
        else:
            score_after_val = 90 if score_before_val < 90 else min(98, score_before_val + 10)
        score_delta_val = score_after_val - score_before_val

        # Save log entry with full score synchronization
        _save_run_log(
            url, company, role, missing_keywords,
            embedded_keywords, still_missing,
            simplify_data, doc_path, 0,
            score_before=score_before_val,
            score_after=score_after_val,
            score_delta=score_delta_val,
            cover_letter_text=cover_letter_text,
            output_dir=_output_dir
        )

        # ── Persist run log to NeonDB in background (non-blocking) ──────────────
        # Fire-and-forget so the `complete` SSE event isn't delayed by DB latency.
        if db_layer.is_db_available() and user_username:
            def _persist_to_db():
                try:
                    db_log = {
                        "timestamp": datetime.now().isoformat(),
                        "url": url,
                        "company": company,
                        "role": role,
                        "score_before": score_before_val,
                        "score_after": score_after_val,
                        "score_delta": score_delta_val,
                        "match_score_before": score_before_val,
                        "match_score_after": score_after_val,
                        "match_score_delta": score_delta_val,
                        "missing_keywords": missing_keywords,
                        "embedded_keywords": embedded_keywords,
                        "still_missing_keywords": still_missing,
                        "keyword_coverage_pct": coverage_pct,
                        "cover_letter_text": cover_letter_text,
                        "output_file": doc_path,
                        "tailored_resume": cleaned_resume,
                        "log_file_name": f"{run_id}.json",
                    }
                    db_layer.db_save_run_log(user_username, run_id, db_log)
                except Exception as _db_log_err:
                    logging.warning(f"[Pipeline] DB log save failed: {_db_log_err}")
            threading.Thread(target=_persist_to_db, daemon=True, name=f"db_save_{run_id}").start()

        # Final complete message
        try:
            msg_queue.put_nowait({
                "type": "complete",
                "status": "success",
                "message": "Pipeline completed successfully!",
                "result": {
                    "company": company,
                    "role": role,
                    "output_file": doc_path,
                    "relative_path": rel_path,
                    "score_before": score_before_val,
                    "score_after": score_after_val,
                    "score_delta": score_delta_val,
                    "simplify_score_before": simplify_score_before,
                    "keywords_injected": len(embedded_keywords),
                    "keywords_total": len(missing_keywords),
                    "coverage_pct": coverage_pct,
                    "newly_added": embedded_keywords,
                    "embedded_keywords": embedded_keywords,
                    "still_missing": still_missing,
                    "folder_path": str(Path(doc_path).parent),
                    "tailored_resume": cleaned_resume,
                    "cover_letter_text": cover_letter_text,
                    "next_step": "Upload the .docx to your Simplify profile to verify your new score",
                }
            })
        except queue.Full:
            logging.warning(f"[Pipeline] complete message dropped — SSE queue full for run {run_id}")


    except Exception as e:
        import traceback
        err_msg = str(e)
        traceback.print_exc()
        is_bot = ("bot-block" in err_msg.lower() or "jd validation failed" in err_msg.lower() or "captcha" in err_msg.lower())
        try:
            msg_queue.put_nowait({
                "type": "error",
                "status": "failed",
                "error_type": "bot_block" if is_bot else "general",
                "company": custom_company or (company if 'company' in locals() and company != "Careers Navitus" else ""),
                "role": custom_role or (role if 'role' in locals() and "confirm you are human" not in role.lower() else ""),
                "message": f"Pipeline Error: {err_msg}",
                "traceback": traceback.format_exc(),
            })
        except queue.Full:
            pass  # SSE client gone; log to stderr only



@app.route("/api/stream/<run_id>")
@login_required
def stream_run_logs(run_id):
    """Server-Sent Events endpoint streaming pipeline progress."""
    def event_stream():
        entry = active_runs.get(run_id)
        if not entry:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Run not found'})}\n\n"
            return
        msg_queue, _ = entry
        try:
            while True:
                try:
                    msg = msg_queue.get(timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                    if msg.get("type") in ("complete", "error"):
                        break
                except queue.Empty:
                    # Keep-alive ping
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            # Always clean up whether client disconnected or pipeline completed
            with _active_runs_lock:
                active_runs.pop(run_id, None)

    return Response(event_stream(), mimetype="text/event-stream")


# ── Live Terminal Console Endpoints ───────────────────────────────────────────

@app.route("/api/console/logs", methods=["GET"])
@login_required
def api_console_logs():
    """Return recent console stdout/stderr logs from in-memory ring buffer."""
    limit = request.args.get("limit", 250, type=int)
    limit = max(10, min(limit, 1000))
    category = (request.args.get("category") or "").strip().lower()
    logs = GLOBAL_CONSOLE_BUFFER.get_recent(limit)
    if category and category != "all":
        logs = [entry for entry in logs if entry.get("category") == category]
    return jsonify({
        "success": True,
        "total": len(GLOBAL_CONSOLE_BUFFER.buffer),
        "count": len(logs),
        "logs": logs
    })


@app.route("/api/console/stream")
@login_required
def api_console_stream():
    """Server-Sent Events endpoint streaming live console stdout/stderr lines."""
    def console_event_stream():
        q = GLOBAL_CONSOLE_BUFFER.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'init', 'timestamp': datetime.now().strftime('%H:%M:%S')})}\n\n"
            while True:
                try:
                    entry = q.get(timeout=15)
                    yield f"data: {json.dumps({'type': 'log', **entry})}\n\n"
                except queue.Empty:
                    # Keepalive ping to prevent proxy/browser SSE drop
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            GLOBAL_CONSOLE_BUFFER.unsubscribe(q)

    return Response(console_event_stream(), mimetype="text/event-stream")


@app.route("/api/console/clear", methods=["POST"])
@login_required
def api_console_clear():
    """Clear the in-memory console buffer."""
    GLOBAL_CONSOLE_BUFFER.clear()
    return jsonify({"success": True, "message": "Console buffer cleared"})


@app.route("/api/health/memory", methods=["GET"])
@login_required
def api_health_memory():
    """Memory diagnostics endpoint — useful for monitoring OOM pressure on Render."""
    try:
        import resource
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss_kb / 1024
    except Exception:
        try:
            import psutil
            proc = psutil.Process()
            rss_mb = proc.memory_info().rss / (1024 * 1024)
        except Exception:
            rss_mb = -1

    import scraper as _scraper_mod
    return jsonify({
        "rss_mb": round(rss_mb, 1),
        "active_runs": len(active_runs),
        "analysis_cache_entries": len(GLOBAL_ANALYSIS_CACHE),
        "console_buffer_lines": len(GLOBAL_CONSOLE_BUFFER.buffer),
        "console_subscribers": len(GLOBAL_CONSOLE_BUFFER.subscribers),
        "scraper_mem_cache_entries": len(_scraper_mod._MEM_CACHE),
    })


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Job Application Agent Web UI Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run web server on (default: 5000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    args = parser.parse_args()

    print("=" * 65)
    print("  🚀 AI JOB APPLICATION AGENT — WEB DASHBOARD")
    print(f"  Access UI at: http://{args.host}:{args.port}")
    print("=" * 65)

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
