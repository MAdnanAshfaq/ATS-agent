"""
gemini_client.py — Intelligent Multi-Key Gemini API Pool & Failover Manager

Supports multiple API keys via:
1. GEMINI_API_KEY (Primary)
2. GEMINI_API_KEY_2 (Backup / Secondary)
3. GEMINI_API_KEY_3 or GEMINI_BACKUP_KEY
4. Comma-separated list in GEMINI_API_KEY: "key1, key2, key3"

Automatically catches RESOURCE_EXHAUSTED / 429 / Quota limits, rotates to the next
healthy API key, and transparently retries requests so your application never stalls.
"""

import os
import sys
import time
import logging
import re
from typing import List, Callable, Any
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Ensure Windows stdout never crashes on unicode characters
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Suppress Google GenAI internal SDK AFC (Automatic Function Calling) advisory warnings
logging.getLogger("google_genai.models").setLevel(logging.ERROR)
logging.getLogger("google_genai").setLevel(logging.ERROR)

import threading

logger = logging.getLogger("gemini_client")

# Global pool state (fallback for single-user/local script runs)
_ACTIVE_KEY_INDEX = 0

# Production-level thread-local storage for isolated per-user/per-pipeline execution
_THREAD_LOCAL = threading.local()

# Global set of permanently revoked / invalid API keys (ONLY true API_KEY_INVALID errors)
_DEAD_KEYS = set()


def is_key_invalid_error(e: Exception) -> bool:
    """Return True ONLY if the error indicates a truly malformed/deleted/invalid API key."""
    err_str = str(e).upper()
    return "API_KEY_INVALID" in err_str or "API KEY NOT VALID" in err_str or "CONSUMER_INVALID" in err_str


def extract_retry_delay(err: Exception) -> float:
    """Extract Google's requested backoff delay in seconds (default 10s)."""
    msg = str(err)
    m = re.search(r"retry in\s+([\d\.]+)\s*s", msg, re.IGNORECASE)
    if m:
        try:
            return min(float(m.group(1)) + 1.5, 45.0)
        except Exception:
            pass
    m2 = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)s?", msg, re.IGNORECASE)
    if m2:
        try:
            return min(float(m2.group(1)) + 1.5, 45.0)
        except Exception:
            pass
    return 10.0


def mark_key_dead(key: str, reason: str = "invalid"):
    """Mark an API key as permanently invalid so it is purged from all future rotations."""
    if key and isinstance(key, str):
        clean = key.strip()
        _DEAD_KEYS.add(clean)
        masked = (clean[:6] + "..." + clean[-4:]) if len(clean) > 10 else "key"
        logger.error(f"[Gemini Pool] Permanently disabling invalid key {masked} ({reason})")
        print(f"\n[Gemini Pool] [DEAD KEY PURGED] Key {masked} removed from pool: {reason}")


def set_thread_gemini_keys(keys: List[str]):
    """Assign specific Gemini keys to the current thread/pipeline execution."""
    clean = [k.strip() for k in keys if k and isinstance(k, str) and k.strip() and k.strip() not in _DEAD_KEYS]
    _THREAD_LOCAL.gemini_keys = clean
    _THREAD_LOCAL.active_index = 0
    if clean:
        logger.info(f"[Gemini Pool] Set {len(clean)} thread-isolated keys for active user execution.")


def clear_thread_gemini_keys():
    """Clear thread-local keys upon request/pipeline completion."""
    if hasattr(_THREAD_LOCAL, "gemini_keys"):
        del _THREAD_LOCAL.gemini_keys
    if hasattr(_THREAD_LOCAL, "active_index"):
        del _THREAD_LOCAL.active_index


def get_all_gemini_keys() -> List[str]:
    """
    Extract all configured Gemini API keys with production-grade priority:
    1. Thread-isolated keys (explicitly set for this user's running pipeline)
    2. Active authenticated user's settings from NeonDB / session (current_user.get_settings())
    3. Server-level environment fallback (.env)
    """
    raw_keys = []
    # 1. Thread-local keys (highest precedence, safe for concurrent background pipelines)
    thread_keys = getattr(_THREAD_LOCAL, "gemini_keys", None)
    if thread_keys:
        raw_keys = list(thread_keys)
    else:
        # 2. Active logged-in user's settings from NeonDB (production multi-user mode)
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                s = current_user.get_settings()
                user_keys = []
                for k_name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
                    val = (s.get(k_name) or "").strip()
                    if val:
                        for part in val.split(","):
                            clean_part = part.strip()
                            if clean_part and clean_part not in user_keys:
                                user_keys.append(clean_part)
                if user_keys:
                    raw_keys = user_keys
        except Exception:
            pass

        # 3. Server fallback from environment / .env
        if not raw_keys:
            load_dotenv(override=False)
            env_keys = []
            primary = os.getenv("GEMINI_API_KEY", "").strip()
            if primary:
                for k in primary.split(","):
                    clean_k = k.strip()
                    if clean_k and clean_k not in env_keys:
                        env_keys.append(clean_k)

            for env_name in ("GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_BACKUP_KEY", "GEMINI_KEY_2"):
                val = os.getenv(env_name, "").strip()
                if val and val not in env_keys:
                    env_keys.append(val)

            raw_keys = env_keys

    # Filter out any keys that have thrown 403 PERMISSION_DENIED or API_KEY_INVALID
    return [k for k in raw_keys if k not in _DEAD_KEYS]


def get_active_key() -> str:
    """Return the currently selected Gemini API key for this user/thread."""
    keys = get_all_gemini_keys()
    if not keys:
        raise RuntimeError(
            "No Gemini API key found. Please enter your personal Gemini API key in the Setup tab."
        )

    if hasattr(_THREAD_LOCAL, "active_index"):
        _THREAD_LOCAL.active_index = _THREAD_LOCAL.active_index % len(keys)
        return keys[_THREAD_LOCAL.active_index]

    global _ACTIVE_KEY_INDEX
    _ACTIVE_KEY_INDEX = _ACTIVE_KEY_INDEX % len(keys)
    return keys[_ACTIVE_KEY_INDEX]


def rotate_key(reason: str = "quota") -> str:
    """Rotate to the next available API key in the pool for this user/thread."""
    keys = get_all_gemini_keys()
    if not keys:
        raise RuntimeError("No Gemini API keys available to rotate.")

    if hasattr(_THREAD_LOCAL, "active_index"):
        old_idx = _THREAD_LOCAL.active_index % len(keys)
        _THREAD_LOCAL.active_index = (old_idx + 1) % len(keys)
        new_idx = _THREAD_LOCAL.active_index
    else:
        global _ACTIVE_KEY_INDEX
        old_idx = _ACTIVE_KEY_INDEX % len(keys)
        _ACTIVE_KEY_INDEX = (old_idx + 1) % len(keys)
        new_idx = _ACTIVE_KEY_INDEX

    new_key = keys[new_idx]
    masked_old = (keys[old_idx][:6] + "..." + keys[old_idx][-4:]) if len(keys[old_idx]) > 10 else f"Key #{old_idx+1}"
    masked_new = (new_key[:6] + "..." + new_key[-4:]) if len(new_key) > 10 else f"Key #{new_idx+1}"

    print(f"\n[Gemini Pool] [ROTATING] {reason.upper()}: Rotating from Key #{old_idx+1} ({masked_old}) to Key #{new_idx+1} ({masked_new})...")
    return new_key


def get_gemini_client(force_rotate: bool = False) -> genai.Client:
    """Get a GenAI client initialized with the current active API key."""
    if force_rotate:
        rotate_key(reason="manual request")
    key = get_active_key()
    return genai.Client(api_key=key)


def is_quota_error(exc: Exception) -> bool:
    """Check if an exception is due to rate limits or quota exhaustion."""
    err_msg = str(exc).upper()
    quota_signals = (
        "RESOURCE_EXHAUSTED",
        "429",
        "QUOTA",
        "RATE_LIMIT",
        "EXHAUSTED",
        "TOO MANY REQUESTS",
        "API_KEY_INVALID",
        "PERMISSION_DENIED",
    )
    return any(sig in err_msg for sig in quota_signals)


def execute_with_failover(fn: Callable[[genai.Client], Any], max_rotations: int = None) -> Any:
    """
    Execute a Gemini operation with automatic multi-key failover.
    If a quota/rate-limit error occurs, rotates to the backup key and retries immediately.
    """
    keys = get_all_gemini_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEY is not configured in .env.")

    if max_rotations is None:
        max_rotations = max(3, len(keys) * 2)

    last_exception = None
    for attempt in range(max_rotations):
        try:
            client = get_gemini_client()
            return fn(client)
        except Exception as e:
            last_exception = e
            if is_quota_error(e):
                if len(keys) > 1:
                    rotate_key(reason=f"Quota Limit ({type(e).__name__})")
                    time.sleep(1)
                    continue
                else:
                    print(f"[Gemini Pool] [WARN] Single API key hit rate limit: {e}. Waiting 8s...")
                    time.sleep(8)
                    continue
            else:
                # Other non-quota errors (e.g. transient 503 network error)
                if "503" in str(e) or "UNAVAILABLE" in str(e).upper():
                    print(f"[Gemini Pool] Server busy (503). Waiting 4s...")
                    time.sleep(4)
                    continue
                raise e

    raise last_exception or RuntimeError("Gemini operations failed after all key failovers.")
