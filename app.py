"""
app.py — Modern Web UI Server for Jalal Khan's AI Job Application Agent.

Features:
- REST API & Server-Sent Events (SSE) for live step-by-step progress tracking
- Prerequisites health check & config management
- Base resume viewer/editor
- Generated applications history with instant document downloads
- Windows File Explorer folder launcher
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, send_file
from flask_cors import CORS

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

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
ENV_PATH = BASE_DIR / ".env"
RESUME_PATH = BASE_DIR / "base_resume.json"

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Active background runs & message queues for SSE
active_runs = {}

# In-memory intelligence cache for parsed ATS jobs & Simplify scores
GLOBAL_ANALYSIS_CACHE = {}


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
            for m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    """Check all prerequisites needed to run the agent."""
    env_vars = get_env_vars()

    has_gemini_key = bool(env_vars.get("GEMINI_API_KEY") or env_vars.get("GEMINI_API_KEY_2"))
    has_gemini_backup = bool(env_vars.get("GEMINI_API_KEY_2"))
    has_base_resume = RESUME_PATH.exists()
    has_simplify_email = bool(env_vars.get("SIMPLIFY_EMAIL"))
    has_simplify_password = bool(env_vars.get("SIMPLIFY_PASSWORD"))

    resume_summary = {}
    if has_base_resume:
        try:
            with open(RESUME_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
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
        "output_dir": env_vars.get("OUTPUT_DIR", str(OUTPUT_DIR)),
    })


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.json or {}
        env_vars = get_env_vars()
        env_vars["GEMINI_API_KEY"] = data.get("GEMINI_API_KEY", env_vars.get("GEMINI_API_KEY", ""))
        env_vars["GEMINI_API_KEY_2"] = data.get("GEMINI_API_KEY_2", env_vars.get("GEMINI_API_KEY_2", ""))
        env_vars["SIMPLIFY_EMAIL"] = data.get("SIMPLIFY_EMAIL", env_vars.get("SIMPLIFY_EMAIL", ""))
        env_vars["SIMPLIFY_PASSWORD"] = data.get("SIMPLIFY_PASSWORD", env_vars.get("SIMPLIFY_PASSWORD", ""))
        if data.get("OUTPUT_DIR"):
            env_vars["OUTPUT_DIR"] = data["OUTPUT_DIR"]

        write_env_vars(env_vars)
        return jsonify({"success": True, "message": "Settings saved successfully"})

    env_vars = get_env_vars()
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
        "OUTPUT_DIR": env_vars.get("OUTPUT_DIR", str(OUTPUT_DIR)),
    })


@app.route("/api/resume", methods=["GET", "POST"])
def manage_resume():
    if request.method == "POST":
        try:
            new_data = request.json
            with open(RESUME_PATH, "w", encoding="utf-8") as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)
            return jsonify({"success": True, "message": "Base resume updated"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    if not RESUME_PATH.exists():
        return jsonify({"error": "base_resume.json not found"}), 404

    with open(RESUME_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/upload_resume", methods=["POST"])
def upload_resume():
    """Upload a new Master Resume (PDF / DOCX / JSON)."""
    if "resume_file" not in request.files:
        return jsonify({"success": False, "error": "No file attached"}), 400

    file = request.files["resume_file"]
    if not file.filename:
        return jsonify({"success": False, "error": "Empty filename"}), 400

    filename = file.filename.lower()
    save_path = BASE_DIR / file.filename
    file.save(save_path)

    try:
        if filename.endswith(".json"):
            with open(save_path, "r", encoding="utf-8") as f:
                parsed_json = json.load(f)
        elif filename.endswith(".pdf") or filename.endswith(".docx"):
            from pdf_to_resume import parse_resume_pdf
            parsed_json = parse_resume_pdf(str(save_path))

            # If uploaded file was .docx, save a copy as master_resume_original.docx for template patching
            if filename.endswith(".docx"):
                orig_target = BASE_DIR / "master_resume_original.docx"
                import shutil
                shutil.copy2(save_path, orig_target)
                print(f"[Upload] Saved Canva template copy to: {orig_target}")
        else:
            return jsonify({"success": False, "error": "Unsupported file format. Please upload PDF, DOCX, or JSON."}), 400

        # Remove temp upload file if distinct from master_resume_original
        try:
            if save_path.exists() and save_path.name != "master_resume_original.docx":
                os.remove(save_path)
        except Exception:
            pass

        with open(RESUME_PATH, "w", encoding="utf-8") as f:
            json.dump(parsed_json, f, indent=2, ensure_ascii=False)

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
def delete_resume():
    """Delete the current master resume (base_resume.json) and reset to empty."""
    try:
        # Write an empty sentinel so the UI reverts to the upload prompt
        empty = {"_empty": True, "name": "", "contact": {}, "summary": "",
                 "skills": [], "experience": [], "education": [],
                 "projects": [], "certifications": []}
        with open(RESUME_PATH, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)

        # Also remove the canva docx template if it exists
        orig_docx = BASE_DIR / "master_resume_original.docx"
        if orig_docx.exists():
            try:
                os.remove(orig_docx)
            except Exception:
                pass

        return jsonify({"success": True, "message": "Master resume deleted successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history")
def history():
    """List all previously generated resume applications."""
    logs_dir = OUTPUT_DIR / "logs"
    applications = []

    if logs_dir.exists():
        for log_file in sorted(logs_dir.glob("run_*.json"), reverse=True):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    log_data = json.load(f)
                    output_file = log_data.get("output_file", "")
                    rel_file = ""
                    if output_file and os.path.exists(output_file):
                        rel_file = os.path.relpath(output_file, str(OUTPUT_DIR))

                    log_data["relative_file_path"] = rel_file
                    log_data["log_file_name"] = log_file.name
                    applications.append(log_data)
            except Exception:
                continue

    return jsonify({"applications": applications, "count": len(applications)})


def _delete_single_history_log(filename: str) -> bool:
    """Helper: Delete log file, .docx, .pdf, and application folder."""
    import shutil
    logs_dir = OUTPUT_DIR / "logs"
    log_file = logs_dir / filename
    if not log_file.exists():
        return False

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            log_data = json.load(f)
            output_file = log_data.get("output_file", "")
            if output_file:
                out_path = Path(output_file)
                parent_dir = out_path.parent
                if out_path.exists():
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                pdf_file = out_path.with_suffix(".pdf")
                if pdf_file.exists():
                    try:
                        os.remove(pdf_file)
                    except Exception:
                        pass
                # Remove output subfolder if it exists
                if parent_dir.exists() and parent_dir != OUTPUT_DIR and str(parent_dir).startswith(str(OUTPUT_DIR)):
                    try:
                        shutil.rmtree(parent_dir, ignore_errors=True)
                    except Exception as folder_err:
                        print(f"[Delete Folder Error] {folder_err}")

        os.remove(log_file)
        return True
    except Exception as e:
        print(f"[History Delete Error] {filename}: {e}")
        return False


@app.route("/api/history/<filename>", methods=["DELETE"])
def delete_history_item(filename):
    """Delete a history run entry and its output folder."""
    if _delete_single_history_log(filename):
        return jsonify({"success": True, "message": "History entry and output folder deleted cleanly"})
    return jsonify({"success": False, "error": "Failed to delete history item or file not found"}), 404


@app.route("/api/history/delete_batch", methods=["POST"])
def delete_history_batch():
    """Bulk delete multiple history run entries and their output folders."""
    data = request.json or {}
    filenames = data.get("filenames", [])
    if not filenames or not isinstance(filenames, list):
        return jsonify({"success": False, "error": "No filenames provided for bulk deletion"}), 400

    deleted_count = 0
    for fname in filenames:
        if _delete_single_history_log(fname):
            deleted_count += 1

    return jsonify({
        "success": True,
        "message": f"Successfully deleted {deleted_count} history entries and output folders.",
        "deleted_count": deleted_count
    })


@app.route("/api/download/<path:filepath>")
def download_file(filepath):
    """Download a generated resume .docx, .pdf, or .json file with robust path resolution."""
    import urllib.parse
    clean_fp = urllib.parse.unquote(filepath).replace("\\", "/").strip("/")

    # 1. Direct absolute path check
    target_path = Path(clean_fp)
    if not (target_path.is_absolute() and target_path.exists()):
        target_path = (OUTPUT_DIR / clean_fp).resolve()

    # 2. Check inside BASE_DIR
    if not target_path.exists():
        candidate_base = (BASE_DIR / clean_fp).resolve()
        if candidate_base.exists():
            target_path = candidate_base

    # 3. Check stripped 'output/' prefix
    if not target_path.exists() and "output/" in clean_fp.lower():
        sub = clean_fp.split("output/", 1)[-1]
        candidate_sub = (OUTPUT_DIR / sub).resolve()
        if candidate_sub.exists():
            target_path = candidate_sub

    # 4. Search recursively inside OUTPUT_DIR by exact filename
    if not target_path.exists():
        fname = Path(clean_fp).name
        matches = list(OUTPUT_DIR.rglob(fname))
        if matches:
            # Sort by modification time to get the newest
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = matches[0].resolve()

    # 5. If PDF requested but doesn't exist, search for .docx counterpart and convert on the fly!
    if not target_path.exists() and clean_fp.lower().endswith(".pdf"):
        docx_name = Path(clean_fp).stem + ".docx"
        docx_matches = list(OUTPUT_DIR.rglob(docx_name))
        if docx_matches:
            docx_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            try:
                from resume_builder import convert_to_pdf
                pdf_res = convert_to_pdf(str(docx_matches[0]))
                if pdf_res and Path(pdf_res).exists():
                    target_path = Path(pdf_res).resolve()
            except Exception as e:
                print(f"[Download] On-the-fly PDF conversion error: {e}")

    # 6. If Cover Letter requested with any name, find newest Cover_Letter in output
    if not target_path.exists() and "cover_letter" in clean_fp.lower():
        subfolder = Path(clean_fp).parent
        search_dir = (OUTPUT_DIR / subfolder).resolve() if (OUTPUT_DIR / subfolder).exists() else OUTPUT_DIR
        cl_matches = list(search_dir.rglob("*Cover_Letter*.docx")) or list(OUTPUT_DIR.rglob("*Cover_Letter*.docx"))
        if cl_matches:
            cl_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = cl_matches[0].resolve()

    # 7. If generic resume requested and not found, find the newest generated resume in output
    if not target_path.exists() and "resume" in clean_fp.lower():
        ext = ".pdf" if clean_fp.lower().endswith(".pdf") else ".docx"
        resume_matches = list(OUTPUT_DIR.rglob(f"*Resume*{ext}"))
        if resume_matches:
            resume_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            target_path = resume_matches[0].resolve()

    # 8. Fallback to base_resume.json if json requested
    if not target_path.exists() and clean_fp.lower().endswith(".json"):
        if (BASE_DIR / "base_resume.json").exists():
            target_path = (BASE_DIR / "base_resume.json").resolve()

    if not target_path.exists() or not target_path.is_file():
        return jsonify({"error": f"File '{filepath}' not found"}), 404

    # Determine MIME type
    mimetype = None
    if target_path.suffix.lower() == ".docx":
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif target_path.suffix.lower() == ".pdf":
        mimetype = "application/pdf"
    elif target_path.suffix.lower() == ".json":
        mimetype = "application/json"

    return send_file(
        str(target_path),
        as_attachment=True,
        download_name=target_path.name,
        mimetype=mimetype,
    )



@app.route("/api/analyze", methods=["POST"])
def analyze_job():
    """
    Step 1 Analysis: Scrapes JD text, calls Simplify (or extract_keywords_from_jd),
    cross-checks against base_resume.json, and returns Simplify-style matched vs missing keywords.
    """
    data = request.json or {}
    url = data.get("url", "").strip()
    no_simplify = data.get("no_simplify", False)

    if not url:
        return jsonify({"error": "Please enter a job URL or paste the job description text."}), 400

    # Detect if user pasted direct job description text instead of a URL
    is_direct_text = ("\n" in url) or (" " in url and len(url.split()) > 5) or (not url.startswith(("http://", "https://")) and not ("." in url and "/" in url))

    try:
        import asyncio
        from agent import load_base_resume, extract_keywords_from_jd
        from scraper import scrape_jd, sanitize_jd_url, clean_role_title
        from simplify_reader import read_simplify_score

        base_resume = load_base_resume()

        if is_direct_text:
            print(f"[Analyze] Direct Job Description text detected ({len(url):,} chars). Skipping network scraper.")
            jd_text = url
            company = "Target Company"
            role = "Data Engineer"
            no_simplify = True  # Simplify extension requires a browser URL

            # Try to infer company and role if present
            first_line = jd_text.strip().split("\n")[0][:80]
            if " at " in first_line:
                parts = first_line.split(" at ", 1)
                role = clean_role_title(parts[0].strip())
                company = parts[1].strip()
            elif " - " in first_line:
                parts = first_line.split(" - ", 1)
                role = clean_role_title(parts[0].strip())
                company = parts[1].strip()
            jd_data = {"company": company, "role": role, "jd_text": jd_text}
            jd_len = len(jd_text)
        else:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Dedicated asyncio loop for Flask thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Show the sanitized URL in logs so user can see what's being scraped
            sanitized_url = sanitize_jd_url(url.rstrip("/"))
            print(f"[Analyze] Scraping JD from {sanitized_url}...")

            try:
                jd_data = loop.run_until_complete(scrape_jd(url))
            except RuntimeError as scrape_err:
                err_str = str(scrape_err)
                user_msg = (
                    "⚠️ Could not extract the job description from this URL.\n\n"
                    + err_str.split("\n")[0]
                    + "\n\nWhat to do:\n"
                    "1. Open the job in your browser and copy the direct URL\n"
                    "2. Or paste the full JD text directly into the URL input box and click Analyze"
                )
                print(f"[Analyze] Scrape validation failed: {scrape_err}")
                return jsonify({
                    "success": False,
                    "error": user_msg,
                    "error_type": "scrape_blocked",
                    "jd_length": 0,
                }), 422

            company = jd_data["company"]
            role = clean_role_title(jd_data["role"])
            jd_text = jd_data["jd_text"]
            jd_len  = len(jd_text)
            print(f"[Analyze] Scraped {jd_len} chars for {role} at {company}")

        missing_keywords = []
        matching_keywords = []
        score = 0

        s_data = {}
        # Try Simplify extension reader first if available & not disabled
        if not no_simplify:
            try:
                print(f"[Analyze] Running Simplify extension reader...")
                s_data = loop.run_until_complete(read_simplify_score(url, company, role))
                if s_data.get("success"):
                    score = s_data.get("score") or 75
                    missing_keywords = s_data.get("missing_keywords", [])
                    matching_keywords = s_data.get("matching_keywords", [])
                    print(f"[Analyze] Simplify extension score: {score}%")
            except Exception as e:
                print(f"[Analyze] Simplify read note: {e}")

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
            "source": source,
            "jd_data": jd_data,
            "matrix": res_payload,
        }

        return jsonify(res_payload)

    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        try:
            with open("debug_analyze.log", "w", encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500



@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    """Open specified output directory in Windows File Explorer."""
    data = request.json or {}
    folder_path = data.get("folder_path", str(OUTPUT_DIR))

    target = Path(folder_path).resolve()
    if not target.exists():
        target = OUTPUT_DIR.resolve()
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
def generate_cover_letter_api():
    """Generate a job-specific AI cover letter for the given job URL or role."""
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

        base_resume = load_base_resume()

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
        target_dir = OUTPUT_DIR / folder_name

        res = generate_cover_letter(
            base_resume=base_resume,
            jd_text=jd_text,
            company=company,
            role=role,
            missing_keywords=custom_keywords,
            output_dir=str(target_dir),
        )

        rel_docx = os.path.relpath(res["file_path_docx"], str(OUTPUT_DIR)).replace("\\", "/") if res.get("file_path_docx") else ""

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


@app.route("/api/run", methods=["POST"])
def start_run():
    """Start pipeline generation run and return run_id for streaming."""
    data = request.json or {}
    url = data.get("url", "").strip()
    custom_keywords = data.get("custom_keywords", "")
    custom_bullets = data.get("custom_bullets", "")
    no_simplify = data.get("no_simplify", False)
    passes = int(data.get("passes", 2))
    custom_output = data.get("custom_output", "")
    score_before = data.get("score_before", None)

    if not url:
        return jsonify({"error": "Please enter a job URL or paste the job description text."}), 400

    run_id = f"run_{int(time.time()*1000)}"
    msg_queue = queue.Queue()
    active_runs[run_id] = msg_queue

    # Start background thread for execution
    thread = threading.Thread(
        target=_execute_agent_pipeline,
        args=(run_id, url, custom_keywords, no_simplify, passes, custom_output, msg_queue, score_before, custom_bullets),
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run_id, "status": "started"})


def _execute_agent_pipeline(run_id, url, custom_keywords_str, no_simplify, passes, custom_output, msg_queue, analyze_score_before=None, custom_bullets=""):
    """Execute pipeline in thread and push step logs to SSE queue."""
    # analyze_score_before: real score from Analyze step (Gemini/Simplify) — authoritative before score
    def send_log(step, stage, message, data=None, status="info"):
        msg_queue.put({
            "type": "progress",
            "step": step,
            "stage": stage,
            "message": message,
            "status": status,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        })

    try:
        from dotenv import load_dotenv
        load_dotenv()

        send_log(1, "Initialize", "Loading base resume...", status="working")
        from agent import load_base_resume, extract_keywords_from_jd, _save_run_log
        from scraper import scrape_jd_sync, clean_role_title, get_cached_jd
        from rewriter import rewrite_resume, _check_keyword_coverage
        from ai_detector import run_ai_detection_loop
        from resume_builder import build_resume_docx

        base_resume = load_base_resume()
        send_log(1, "Base Resume", f"Loaded master resume for {base_resume.get('name')}", status="success")

        # Step 2: Scrape JD (checks memory & disk cache first, or uses direct text)
        is_direct_text = ("\n" in url) or (" " in url and len(url.split()) > 5) or (not url.startswith(("http://", "https://")) and not ("." in url and "/" in url))
        
        if is_direct_text:
            jd_text = url
            company = "Target Company"
            role = "Data Engineer"
            first_line = jd_text.strip().split("\n")[0][:80]
            if " at " in first_line:
                parts = first_line.split(" at ", 1)
                role = clean_role_title(parts[0].strip())
                company = parts[1].strip()
            elif " - " in first_line:
                parts = first_line.split(" - ", 1)
                role = clean_role_title(parts[0].strip())
                company = parts[1].strip()
            no_simplify = True
            send_log(2, "Scrape JD", f"Using direct Job Description text ({len(jd_text):,} chars)",
                     data={"company": company, "role": role, "jd_length": len(jd_text)}, status="success")
        else:
            send_log(2, "Scrape JD", f"Extracting job description from {url}...", status="working")
            cached_analysis = GLOBAL_ANALYSIS_CACHE.get(url)
            if cached_analysis and len(cached_analysis.get("jd_text", "")) >= 800:
                company = cached_analysis["company"]
                role = clean_role_title(cached_analysis["role"])
                jd_text = cached_analysis["jd_text"]
                jd_chars = len(jd_text)
                send_log(2, "Scrape JD",
                         f"⚡ Reused verified JD for {role} at {company} ({jd_chars:,} chars, 0 browser popups)",
                         data={"company": company, "role": role, "jd_length": jd_chars},
                         status="success")
            else:
                jd_data = scrape_jd_sync(url)
                company = jd_data["company"]
                role = clean_role_title(jd_data["role"])
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

        # Step 4: Gemini Resume Rewrite (strict keyword injection + custom bullets)
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

        # Step 6b: Real ATS rescore — Gemini re-evaluates the rewritten resume vs JD
        # This replaces the hardcoded "score + 10" formula with a real measurement.
        score_after_real = None
        try:
            send_log(6, "Score Analysis", "Re-scoring rewritten resume against JD (Gemini)...", status="working")
            from llm_matcher import analyze_jd_and_resume_with_gemini
            rescore_result = analyze_jd_and_resume_with_gemini(jd_text, cleaned_resume)
            score_after_real = rescore_result.get("score")
            if score_after_real is not None:
                score_before_display = analyze_score_before if analyze_score_before is not None else simplify_score_before
                delta = (score_after_real - score_before_display) if score_before_display is not None else None
                delta_str = f" (+{delta}pts)" if delta is not None and delta > 0 else (f" ({delta}pts)" if delta is not None else "")
                send_log(6, "Score Analysis",
                         f"ATS Match Score: {score_before_display}% → {score_after_real}%{delta_str}",
                         data={
                             "score_before": score_before_display,
                             "score_after": score_after_real,
                             "delta": delta,
                         },
                         status="success")
        except Exception as rescore_err:
            print(f"[Pipeline] Rescore note: {rescore_err}")
            send_log(6, "Score Analysis", f"Rescore skipped: {rescore_err}", status="warning")

        # Step 7: Build Word Doc (patch original Canva DOCX if available, else build fresh)
        send_log(7, "Word Document", "Generating Word document...", status="working")
        role = clean_role_title(role, company)
        for sec in ("education", "certifications", "contact", "name", "projects"):
            if sec in base_resume and (sec not in cleaned_resume or not cleaned_resume[sec]):
                cleaned_resume[sec] = base_resume[sec]

        orig_docx_path = BASE_DIR / "master_resume_original.docx"
        if orig_docx_path.exists():
            try:
                from docx_patcher import patch_docx_with_rewritten_resume
                send_log(7, "Word Document", "Patching original Canva DOCX template to preserve custom styling...", status="working")
                doc_path = patch_docx_with_rewritten_resume(
                    original_docx_path=str(orig_docx_path),
                    rewritten_resume=cleaned_resume,
                    company=company,
                    role=role,
                    output_dir=custom_output,
                )
                send_log(7, "Word Document", "Patched original Canva template with rewritten content!", status="success")
            except Exception as patch_err:
                print(f"[Pipeline] DOCX patcher error: {patch_err}, falling back to build_resume_docx")
                doc_path = build_resume_docx(
                    resume=cleaned_resume,
                    company=company,
                    role=role,
                    output_dir=custom_output,
                )
        else:
            doc_path = build_resume_docx(
                resume=cleaned_resume,
                company=company,
                role=role,
                output_dir=custom_output,
            )

        # Automatically convert to PDF for instant viewing/download
        try:
            from resume_builder import convert_to_pdf
            pdf_path = convert_to_pdf(doc_path)
            send_log(7, "PDF Builder", "Converted document to PDF successfully!", status="success")
        except Exception as pdf_err:
            print(f"[Pipeline] PDF conversion note: {pdf_err}")

        # Automatically generate recruiter-targeting AI Cover Letter
        cover_letter_text = ""
        try:
            from cover_letter_generator import generate_cover_letter
            target_dir = Path(doc_path).parent
            cl_res = generate_cover_letter(
                base_resume=base_resume,
                jd_text=jd_text,
                company=company,
                role=role,
                missing_keywords=missing_keywords,
                output_dir=str(target_dir),
            )
            cover_letter_text = cl_res.get("cover_letter_text", "")
            send_log(7, "Cover Letter", "Generated high-impact AI Cover Letter!", status="success")
        except Exception as cl_err:
            print(f"[Pipeline] Cover letter note: {cl_err}")

        rel_path = os.path.relpath(doc_path, str(OUTPUT_DIR)).replace("\\", "/")

        # Save log entry
        _save_run_log(
            url, company, role, missing_keywords,
            embedded_keywords, still_missing,
            simplify_data, doc_path, 0
        )

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

        # Final complete message
        msg_queue.put({
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
                "cover_letter_text": cover_letter_text,
                "next_step": "Upload the .docx to your Simplify profile to verify your new score",
            }
        })

    except Exception as e:
        import traceback
        err_msg = str(e)
        traceback.print_exc()
        msg_queue.put({
            "type": "error",
            "status": "failed",
            "message": f"Pipeline Error: {err_msg}",
            "traceback": traceback.format_exc(),
        })


@app.route("/api/stream/<run_id>")
def stream_run_logs(run_id):
    """Server-Sent Events endpoint streaming pipeline progress."""
    def event_stream():
        msg_queue = active_runs.get(run_id)
        if not msg_queue:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Run not found'})}\n\n"
            return

        while True:
            try:
                msg = msg_queue.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") in ("complete", "error"):
                    active_runs.pop(run_id, None)
                    break
            except queue.Empty:
                # Keep-alive ping
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


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
