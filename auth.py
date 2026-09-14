"""
auth.py — Multi-user authentication for ATS Agent.
Each user has fully isolated data: resume, settings/API keys, and job history.
Uses werkzeug password hashing + flask-login sessions.

Storage: NeonDB PostgreSQL when DATABASE_URL is set; falls back to local
JSON files for local development without a database.

Compatible with localhost, Cloudflare tunnel, Render.com, and live domains.
"""

import json
import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

import db as db_layer

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "users"
USERS_DB = BASE_DIR / "data" / "users.json"

# Ensure base data directories exist (used in file-fallback mode)
DATA_DIR.mkdir(parents=True, exist_ok=True)


import logging

logger = logging.getLogger(__name__)

# ─── User Model ───────────────────────────────────────────────────────────────

class User(UserMixin):
    """
    Represents an authenticated user.
    id = username (slug, lowercase, alphanumeric + underscore/hyphen)
    """

    def __init__(self, username: str, email: str, display_name: str = ""):
        self.id = username
        self.username = username
        self.email = email
        self.display_name = display_name or username

    @property
    def data_dir(self) -> Path:
        """User-specific data folder: data/users/{username}/"""
        d = DATA_DIR / self.username
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_disk_files(self):
        """
        Ensure user's base_resume.json and master_resume_original.docx exist on local disk.
        Essential for Render/container environments where disk is ephemeral and data is in NeonDB.
        """
        if not db_layer.is_db_available():
            return

        r_path = self.data_dir / "base_resume.json"
        if not r_path.exists():
            try:
                rdata = db_layer.db_get_resume(self.username)
                if rdata and not rdata.get("_empty"):
                    with open(r_path, "w", encoding="utf-8") as f:
                        json.dump(rdata, f, indent=2, ensure_ascii=False)
                    logger.info(f"[Auth] Restored base_resume.json from NeonDB for {self.username}")
            except Exception as e:
                logger.warning(f"[Auth] Could not restore base_resume.json for {self.username}: {e}")

        d_path = self.data_dir / "master_resume_original.docx"
        if not d_path.exists():
            try:
                dbytes = db_layer.db_get_resume_docx(self.username)
                if dbytes:
                    with open(d_path, "wb") as f:
                        f.write(dbytes)
                    logger.info(f"[Auth] Restored master_resume_original.docx from NeonDB for {self.username}")
            except Exception as e:
                logger.warning(f"[Auth] Could not restore master_resume_original.docx for {self.username}: {e}")

    @property
    def resume_path(self) -> Path:
        self.ensure_disk_files()
        return self.data_dir / "base_resume.json"

    @property
    def output_dir(self) -> Path:
        d = self.data_dir / "output"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def get_settings(self) -> dict:
        """Read user-specific API keys and preferences."""
        # ── DB mode ───────────────────────────────────────────────────────────
        if db_layer.is_db_available():
            return db_layer.db_get_settings(self.username)

        # ── File fallback ─────────────────────────────────────────────────────
        defaults = {
            "GEMINI_API_KEY": "",
            "GEMINI_API_KEY_2": "",
            "SIMPLIFY_EMAIL": "",
            "SIMPLIFY_PASSWORD": "",
            "HF_API_KEY": "",
            "COLAB_DETECTOR_URL": "",
        }
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    defaults.update(saved)
            except Exception:
                pass
        return defaults

    def save_settings(self, updates: dict):
        """Persist user API keys / settings."""
        # ── DB mode ───────────────────────────────────────────────────────────
        if db_layer.is_db_available():
            current = self.get_settings()
            current.update({k: v for k, v in updates.items() if v is not None})
            db_layer.db_save_settings(self.username, current)
            return

        # ── File fallback ─────────────────────────────────────────────────────
        current = self.get_settings()
        current.update({k: v for k, v in updates.items() if v is not None})
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)

    def has_resume(self) -> bool:
        """Returns True if user has a non-empty resume uploaded."""
        # ── DB mode ───────────────────────────────────────────────────────────
        if db_layer.is_db_available():
            return db_layer.db_has_resume(self.username)

        # ── File fallback ─────────────────────────────────────────────────────
        if not self.resume_path.exists():
            return False
        try:
            with open(self.resume_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return not data.get("_empty", False) and bool(data.get("name", "").strip())
        except Exception:
            return False

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
        }


# ─── Users Database ───────────────────────────────────────────────────────────

def _load_users_db() -> dict:
    """Load the users registry JSON (file-fallback mode only)."""
    if not USERS_DB.exists():
        return {}
    try:
        with open(USERS_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users_db(db: dict):
    """Save users registry JSON (file-fallback mode only)."""
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_DB, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)


def load_user_by_id(username: str):
    """Flask-Login callback: load user from session ID (username)."""
    # ── DB mode ───────────────────────────────────────────────────────────────
    if db_layer.is_db_available():
        entry = db_layer.db_get_user_by_username(username)
        if not entry:
            return None
        u = User(
            username=entry["username"],
            email=entry["email"],
            display_name=entry.get("display_name", username),
        )
        u.ensure_disk_files()
        return u

    # ── File fallback ─────────────────────────────────────────────────────────
    db = _load_users_db()
    if username not in db:
        return None
    entry = db[username]
    return User(
        username=username,
        email=entry.get("email", ""),
        display_name=entry.get("display_name", username),
    )


def get_user_by_email(email: str):
    """Find user record by email address (for login).
    Returns (username, entry_dict) or (None, None).
    """
    email_lower = email.strip().lower()

    # ── DB mode ───────────────────────────────────────────────────────────────
    if db_layer.is_db_available():
        entry = db_layer.db_get_user_by_email(email_lower)
        if entry:
            return entry["username"], entry
        return None, None

    # ── File fallback ─────────────────────────────────────────────────────────
    db = _load_users_db()
    for username, entry in db.items():
        if entry.get("email", "").lower() == email_lower:
            return username, entry
    return None, None


def verify_login(email: str, password: str):
    """
    Validate email + password. Returns User object on success, None on failure.
    """
    username, entry = get_user_by_email(email)
    if not entry:
        return None
    if not check_password_hash(entry.get("password_hash", ""), password):
        return None
    u = User(
        username=username,
        email=entry.get("email", ""),
        display_name=entry.get("display_name", username),
    )
    u.ensure_disk_files()
    return u


def register_user(email: str, password: str, display_name: str = "") -> tuple:
    """
    Create a new user account.
    Returns (User, error_message). On success, error_message is None.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return None, "Please enter a valid email address."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    # Check duplicate
    existing_username, _ = get_user_by_email(email)
    if existing_username:
        return None, "An account with this email already exists. Please log in."

    # Create username slug from email prefix
    username_base = email.split("@")[0]
    username = _make_unique_username(username_base)

    display_name = display_name.strip() or username
    password_hash = generate_password_hash(password)

    # ── DB mode ───────────────────────────────────────────────────────────────
    if db_layer.is_db_available():
        success = db_layer.db_create_user(username, email, password_hash, display_name)
        if not success:
            return None, "Account creation failed. Please try again."
        user = User(username=username, email=email, display_name=display_name)
        # Ensure local dirs still exist (for temp file operations like docx builds)
        user.data_dir.mkdir(parents=True, exist_ok=True)
        user.output_dir.mkdir(parents=True, exist_ok=True)
        _handle_first_user_migration(user)
        return user, None

    # ── File fallback ─────────────────────────────────────────────────────────
    db = _load_users_db()
    is_first_user = len(db) == 0

    db[username] = {
        "email": email,
        "password_hash": password_hash,
        "display_name": display_name,
        "created_at": datetime.utcnow().isoformat(),
    }
    _save_users_db(db)

    user = User(username=username, email=email, display_name=display_name)
    user.data_dir.mkdir(parents=True, exist_ok=True)
    user.output_dir.mkdir(parents=True, exist_ok=True)

    if is_first_user:
        _handle_first_user_migration(user)

    return user, None


def _handle_first_user_migration(user: User):
    """
    On first registered account, migrate any legacy root-level data files
    (base_resume.json, master_resume_original.docx, .env credentials, old logs)
    into the new user's data directory.
    """
    # Only apply if this is actually the first account
    if db_layer.is_db_available():
        if db_layer.db_count_users() > 1:
            return
    else:
        db = _load_users_db()
        if len(db) > 1:
            return

    # Migrate base_resume.json
    root_resume = BASE_DIR / "base_resume.json"
    if root_resume.exists():
        if db_layer.is_db_available():
            try:
                with open(root_resume, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                if not db_layer.db_has_resume(user.username):
                    db_layer.db_save_resume(user.username, parsed)
                    print(f"[Auth] Migrated root base_resume.json to DB for {user.username}")
            except Exception as e:
                print(f"[Auth] Note on resume migration: {e}")
        elif not user.resume_path.exists():
            try:
                shutil.copy2(root_resume, user.resume_path)
                print(f"[Auth] Migrated root base_resume.json to {user.username}")
            except Exception as e:
                print(f"[Auth] Note on resume migration: {e}")

    # Migrate master docx
    root_docx = BASE_DIR / "master_resume_original.docx"
    if root_docx.exists():
        if db_layer.is_db_available():
            try:
                with open(root_docx, "rb") as f:
                    docx_bytes = f.read()
                db_layer.db_save_resume_docx(user.username, docx_bytes)
                print(f"[Auth] Migrated master_resume_original.docx to DB for {user.username}")
            except Exception as e:
                print(f"[Auth] Note on docx migration: {e}")
        else:
            try:
                shutil.copy2(root_docx, user.data_dir / "master_resume_original.docx")
            except Exception:
                pass

    # Migrate .env credentials to settings
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            env_settings = {}
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_settings[k.strip()] = v.strip()
            user.save_settings(env_settings)
            print(f"[Auth] Migrated .env credentials for {user.username}")
        except Exception as e:
            print(f"[Auth] Note on settings migration: {e}")

    # Migrate existing log files (file mode only — can't migrate to DB without username context yet)
    if not db_layer.is_db_available():
        root_logs = BASE_DIR / "output" / "logs"
        user_logs = user.output_dir / "logs"
        if root_logs.exists():
            try:
                user_logs.mkdir(parents=True, exist_ok=True)
                for f_log in root_logs.glob("run_*.json"):
                    shutil.copy2(f_log, user_logs / f_log.name)
                print(f"[Auth] Migrated existing history logs to {user.username}")
            except Exception as e:
                print(f"[Auth] Note on logs migration: {e}")


def _make_unique_username(base: str) -> str:
    """Generate a slug username that doesn't conflict with existing ones."""
    slug = re.sub(r"[^a-z0-9_-]", "", base.lower())[:20] or "user"

    if db_layer.is_db_available():
        # Check against DB
        if not db_layer.db_get_user_by_username(slug):
            return slug
        for i in range(2, 100):
            candidate = f"{slug}{i}"
            if not db_layer.db_get_user_by_username(candidate):
                return candidate
    else:
        db = _load_users_db()
        if slug not in db:
            return slug
        for i in range(2, 100):
            candidate = f"{slug}{i}"
            if candidate not in db:
                return candidate

    return slug + "_" + secrets.token_hex(3)


def change_password(username: str, current_password: str, new_password: str) -> tuple:
    """Change user password. Returns (success, error_message)."""
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters."

    if db_layer.is_db_available():
        entry = db_layer.db_get_user_by_username(username)
        if not entry:
            return False, "User not found."
        if not check_password_hash(entry.get("password_hash", ""), current_password):
            return False, "Current password is incorrect."
        new_hash = generate_password_hash(new_password)
        ok = db_layer.db_update_password(username, new_hash)
        return (True, None) if ok else (False, "Failed to update password.")

    # File fallback
    db = _load_users_db()
    if username not in db:
        return False, "User not found."
    entry = db[username]
    if not check_password_hash(entry.get("password_hash", ""), current_password):
        return False, "Current password is incorrect."
    db[username]["password_hash"] = generate_password_hash(new_password)
    _save_users_db(db)
    return True, None


# ─── Migration Helper ─────────────────────────────────────────────────────────

def migrate_existing_data(existing_resume_path: Path, existing_env_path: Path):
    """
    On first boot with no users, prompt to create the first account.
    Called from app.py during startup.
    """
    if db_layer.is_db_available():
        if db_layer.db_count_users() > 0:
            return
    else:
        db = _load_users_db()
        if db:
            return

    print("[Auth] No users found. The first person to sign up will inherit existing data automatically.")


def get_all_users() -> list:
    """Return list of all registered user dicts (for admin inspection if needed)."""
    if db_layer.is_db_available():
        return db_layer.db_get_all_users()

    db = _load_users_db()
    return [
        {"username": uname, "email": entry.get("email", ""), "display_name": entry.get("display_name", uname), "created_at": entry.get("created_at", "")}
        for uname, entry in db.items()
    ]


# ─── Secret Key Helper ────────────────────────────────────────────────────────

def ensure_secret_key(env_path: Path) -> str:
    """
    Read or generate AUTH_SECRET_KEY.
    In production, prefer AUTH_SECRET_KEY environment variable directly.
    Falls back to .env file for local dev.
    """
    # Production: read from environment directly (Render sets this)
    key = os.environ.get("AUTH_SECRET_KEY", "")
    if key:
        return key

    # Local dev: read from .env file
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            if line.strip().startswith("AUTH_SECRET_KEY="):
                key = line.strip().split("=", 1)[1]
                break

    if not key:
        key = secrets.token_hex(32)
        lines.append(f"\nAUTH_SECRET_KEY={key}\n")
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nAUTH_SECRET_KEY={key}\n")
        print(f"[Auth] Generated new AUTH_SECRET_KEY and saved to .env")

    return key
