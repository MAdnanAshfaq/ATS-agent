"""List Gemini models that support generateContent.

Usage:
    python list_models.py                # key from GEMINI_API_KEY in .env / environment
    python list_models.py <username>     # key from that user's saved settings in the DB
                                         # (falls back to GEMINI_API_KEY if none found)
    ATS_USERNAME=<username> python list_models.py
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from google import genai


def _key_from_user_settings(username: str) -> str:
    """Return the first usable Gemini key stored for `username`, or ''."""
    try:
        import db
        settings = db.db_get_settings(username) or {}
    except Exception as e:
        print(f"[list_models] Could not read settings for '{username}': {e}", file=sys.stderr)
        return ""

    for item in settings.get("GEMINI_API_KEYS") or []:
        if isinstance(item, dict):
            val = (item.get("key") or "").strip()
        elif isinstance(item, str):
            val = item.strip()
        else:
            val = ""
        if val:
            return val

    for field in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
        val = (settings.get(field) or "").strip()
        if val:
            return val
    return ""


def resolve_api_key() -> str:
    username = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ATS_USERNAME", "")).strip()
    if username:
        key = _key_from_user_settings(username)
        if key:
            return key
        print(f"[list_models] No Gemini key saved for '{username}'; trying GEMINI_API_KEY.", file=sys.stderr)

    # GEMINI_API_KEY may hold a comma-separated list; use the first entry.
    env_val = os.environ.get("GEMINI_API_KEY", "")
    return next((k.strip() for k in env_val.split(",") if k.strip()), "")


def main() -> int:
    key = resolve_api_key()
    if not key:
        print("[list_models] No Gemini API key found. Set GEMINI_API_KEY in .env "
              "or pass a username whose settings contain a key.", file=sys.stderr)
        return 1

    client = genai.Client(api_key=key)
    for m in client.models.list():
        name = getattr(m, "name", "") or ""
        disp = getattr(m, "display_name", "") or ""
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            print(f"{name} ({disp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
