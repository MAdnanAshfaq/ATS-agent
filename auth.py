"""
auth.py — Multi-user authentication for ATS Agent.
Each user has fully isolated data: resume, settings/API keys, and job history.
Uses werkzeug password hashing + flask-login sessions.
Compatible with localhost, Cloudflare tunnel, and live domains.
"""

import json
import os
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "users"
USERS_DB = BASE_DIR / "data" / "users.json"

# Ensure base data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)


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

    @property
    def resume_path(self) -> Path:
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
        current = self.get_settings()
        current.update({k: v for k, v in updates.items() if v is not None})
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)

    def has_resume(self) -> bool:
        """Returns True if user has a non-empty resume uploaded."""
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
    """Load the users registry JSON. Schema: {username: {email, password_hash, display_name, created_at}}"""
    if not USERS_DB.exists():
        return {}
    try:
        with open(USERS_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users_db(db: dict):
    USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_DB, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)


def load_user_by_id(username: str):
    """Flask-Login callback: load user from session ID (username)."""
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
    """Find user record by email address (for login)."""
    email_lower = email.strip().lower()
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
    return User(
        username=username,
        email=entry.get("email", ""),
        display_name=entry.get("display_name", username),
    )


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

    db = _load_users_db()
    is_first_user = len(db) == 0

    db[username] = {
        "email": email,
        "password_hash": generate_password_hash(password),
        "display_name": display_name,
        "created_at": datetime.utcnow().isoformat(),
    }
    _save_users_db(db)

    user = User(username=username, email=email, display_name=display_name)
    # Create their data directories
    user.data_dir.mkdir(parents=True, exist_ok=True)
    user.output_dir.mkdir(parents=True, exist_ok=True)

    if is_first_user:
        # First account created inherits legacy root data if present
        root_resume = BASE_DIR / "base_resume.json"
        if root_resume.exists() and not user.resume_path.exists():
            try:
                shutil.copy2(root_resume, user.resume_path)
                print(f"[Auth] Migrated root base_resume.json to {user.username}")
            except Exception as e:
                print(f"[Auth] Note on resume migration: {e}")

        root_docx = BASE_DIR / "master_resume_original.docx"
        if root_docx.exists():
            try:
                shutil.copy2(root_docx, user.data_dir / "master_resume_original.docx")
            except Exception:
                pass

        # Inherit .env credentials
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
                print(f"[Auth] Migrated .env credentials to {user.username}")
            except Exception as e:
                print(f"[Auth] Note on settings migration: {e}")

        # Inherit root logs if present
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

    return user, None


def _make_unique_username(base: str) -> str:
    """Generate a slug username that doesn't conflict with existing ones."""
    import re
    slug = re.sub(r"[^a-z0-9_-]", "", base.lower())[:20] or "user"
    db = _load_users_db()
    if slug not in db:
        return slug
    # Append a number until unique
    for i in range(2, 100):
        candidate = f"{slug}{i}"
        if candidate not in db:
            return candidate
    return slug + "_" + secrets.token_hex(3)


def change_password(username: str, current_password: str, new_password: str) -> tuple:
    """Change user password. Returns (success, error_message)."""
    db = _load_users_db()
    if username not in db:
        return False, "User not found."
    entry = db[username]
    if not check_password_hash(entry.get("password_hash", ""), current_password):
        return False, "Current password is incorrect."
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters."
    db[username]["password_hash"] = generate_password_hash(new_password)
    _save_users_db(db)
    return True, None


# ─── Migration Helper ─────────────────────────────────────────────────────────

def migrate_existing_data(existing_resume_path: Path, existing_env_path: Path):
    """
    On first boot with no users, prompt to create the first account.
    Called from app.py during startup.
    """
    db = _load_users_db()
    if db:
        return  # Users already exist, nothing to do

    print("[Auth] No users found. The first person to sign up will inherit existing data automatically if desired.")


def get_all_users() -> list:
    """Return list of all registered user dicts (for admin inspection if needed)."""
    db = _load_users_db()
    return [
        {"username": uname, "email": entry.get("email", ""), "display_name": entry.get("display_name", uname), "created_at": entry.get("created_at", "")}
        for uname, entry in db.items()
    ]


# ─── Secret Key Helper ────────────────────────────────────────────────────────

def ensure_secret_key(env_path: Path) -> str:
    """
    Read or generate AUTH_SECRET_KEY in .env. Returns the key string.
    This key signs Flask sessions — must be stable across restarts.
    """
    key = ""
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
