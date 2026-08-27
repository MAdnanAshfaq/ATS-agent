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

logger = logging.getLogger("gemini_client")

# Global pool state
_ACTIVE_KEY_INDEX = 0


def get_all_gemini_keys() -> List[str]:
    """Extract all configured non-empty Gemini API keys from environment."""
    load_dotenv(override=True)
    keys = []

    # 1. Primary key (might be comma-separated)
    primary = os.getenv("GEMINI_API_KEY", "").strip()
    if primary:
        for k in primary.split(","):
            clean_k = k.strip()
            if clean_k and clean_k not in keys:
                keys.append(clean_k)

    # 2. Numbered backup keys
    for env_name in ("GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_BACKUP_KEY", "GEMINI_KEY_2"):
        val = os.getenv(env_name, "").strip()
        if val and val not in keys:
            keys.append(val)

    return keys


def get_active_key() -> str:
    """Return the currently selected Gemini API key."""
    keys = get_all_gemini_keys()
    if not keys:
        raise RuntimeError(
            "No GEMINI_API_KEY found in .env. Please configure your API key in Settings."
        )
    global _ACTIVE_KEY_INDEX
    _ACTIVE_KEY_INDEX = _ACTIVE_KEY_INDEX % len(keys)
    return keys[_ACTIVE_KEY_INDEX]


def rotate_key(reason: str = "quota") -> str:
    """Rotate to the next available API key in the pool."""
    global _ACTIVE_KEY_INDEX
    keys = get_all_gemini_keys()
    if not keys:
        raise RuntimeError("No Gemini API keys available to rotate.")

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
