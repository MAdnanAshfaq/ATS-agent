"""ats_learning.py - Continuous Learning Memory for Multi-ATS Platform Mapping and Optimization.

Maintains an adaptive, persistent memory of:
1. Domain-to-ATS associations learned from user confirmations and manual overrides.
2. Platform friction metrics (density flags, audit passes/failures) to improve generation over time.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("ats_learning")

LEARNED_DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "ats_learned_domains.json")
_LOCK = threading.Lock()


def _extract_domain(url_or_domain: str) -> str:
    """Normalize a URL or raw domain to a clean lowercase hostname."""
    if not url_or_domain:
        return ""
    text = url_or_domain.strip().lower()
    if not text.startswith("http://") and not text.startswith("https://"):
        text = "https://" + text
    try:
        parsed = urlparse(text)
        host = parsed.netloc or parsed.path
        # Remove port if present
        host = host.split(":")[0]
        # Remove common prefixes
        if host.startswith("www."):
            host = host[4:]
        return host.strip()
    except Exception as e:
        logger.debug("Failed to extract domain from %s: %s", url_or_domain, e)
        return ""


def _load_data() -> Dict[str, Any]:
    """Load the learned dataset from disk with fallback to empty template."""
    default_structure = {
        "version": "1.0",
        "domains": {},
        "metrics": {
            "total_lookups": 0,
            "learned_hits": 0,
            "user_overrides": 0,
            "user_confirmations": 0,
        },
        "platform_audits": {},
    }
    if not os.path.exists(LEARNED_DATA_FILE):
        return default_structure
    try:
        with open(LEARNED_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "domains" not in data:
                data["domains"] = {}
            if "metrics" not in data:
                data["metrics"] = default_structure["metrics"]
            if "platform_audits" not in data:
                data["platform_audits"] = {}
            return data
    except Exception as e:
        logger.warning("Could not read ats_learned_domains.json: %s", e)
        return default_structure


def _save_data(data: Dict[str, Any]) -> None:
    """Write data to disk atomically."""
    try:
        os.makedirs(os.path.dirname(LEARNED_DATA_FILE), exist_ok=True)
        temp_file = LEARNED_DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if os.path.exists(LEARNED_DATA_FILE):
            os.replace(temp_file, LEARNED_DATA_FILE)
        else:
            os.rename(temp_file, LEARNED_DATA_FILE)
    except Exception as e:
        logger.error("Failed to save learned ATS data: %s", e)


def lookup_learned_domain(url_or_domain: str) -> Optional[Tuple[str, float]]:
    """Look up a domain in the continuous learning memory.

    Returns:
        (platform_id, confidence) if found, or None if unknown.
    """
    domain = _extract_domain(url_or_domain)
    if not domain:
        return None

    with _LOCK:
        data = _load_data()
        data["metrics"]["total_lookups"] = data["metrics"].get("total_lookups", 0) + 1
        domains = data.get("domains", {})

        # 1. Exact match
        if domain in domains:
            info = domains[domain]
            data["metrics"]["learned_hits"] = data["metrics"].get("learned_hits", 0) + 1
            _save_data(data)
            return info.get("platform_id"), float(info.get("confidence", 0.9))

        # 2. Subdomain lookup (e.g. jobs.company.com -> company.com)
        parts = domain.split(".")
        if len(parts) > 2:
            parent = ".".join(parts[-2:])
            if parent in domains:
                info = domains[parent]
                data["metrics"]["learned_hits"] = data["metrics"].get("learned_hits", 0) + 1
                _save_data(data)
                return info.get("platform_id"), float(info.get("confidence", 0.85))

        _save_data(data)
    return None


def get_domain_ats(url_or_domain: str) -> Optional[Dict[str, Any]]:
    """Retrieve full domain entry dictionary from continuous learning memory."""
    domain = _extract_domain(url_or_domain)
    if not domain:
        return None
    with _LOCK:
        data = _load_data()
        domains = data.get("domains", {})
        if domain in domains:
            return domains[domain]
        parts = domain.split(".")
        if len(parts) > 2:
            parent = ".".join(parts[-2:])
            if parent in domains:
                return domains[parent]
    return None



def record_domain_ats(
    url_or_domain: str,
    platform_id: str,
    source: str = "user_override",
    confidence: float = 1.0,
) -> bool:
    """Record or update a domain-to-ATS mapping based on user confirmation or override.

    Args:
        url_or_domain: The job application URL or domain name.
        platform_id: The verified ATS platform ID (e.g., 'workday', 'greenhouse').
        source: 'user_override', 'user_confirm', or 'html_signature'.
        confidence: Confidence score (typically 1.0 for explicit user action).

    Returns:
        True if successfully recorded.
    """
    domain = _extract_domain(url_or_domain)
    if not domain or not platform_id:
        return False

    now_iso = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        data = _load_data()
        domains = data.setdefault("domains", {})
        metrics = data.setdefault("metrics", {})

        if domain in domains:
            entry = domains[domain]
            entry["platform_id"] = platform_id
            entry["confirm_count"] = entry.get("confirm_count", 1) + 1
            entry["last_updated"] = now_iso
            entry["source"] = source
            entry["confidence"] = max(entry.get("confidence", 0.8), confidence)
        else:
            domains[domain] = {
                "platform_id": platform_id,
                "confidence": confidence,
                "first_learned": now_iso,
                "last_updated": now_iso,
                "confirm_count": 1,
                "source": source,
                "sample_domain": domain,
            }

        if source == "user_override":
            metrics["user_overrides"] = metrics.get("user_overrides", 0) + 1
        elif source == "user_confirm":
            metrics["user_confirmations"] = metrics.get("user_confirmations", 0) + 1

        _save_data(data)
        logger.info("Learned ATS mapping: %s -> %s (source: %s)", domain, platform_id, source)
    return True


def record_audit_event(
    platform_id: str,
    passed: bool,
    density_val: float = 0.0,
    issues_count: int = 0,
) -> None:
    """Record an audit event for continuous learning and calibration."""
    if not platform_id:
        return
    with _LOCK:
        data = _load_data()
        audits = data.setdefault("platform_audits", {})
        plat_stat = audits.setdefault(
            platform_id,
            {"total_runs": 0, "passes": 0, "fails": 0, "avg_density": 0.0},
        )
        total = plat_stat["total_runs"] + 1
        plat_stat["total_runs"] = total
        if passed:
            plat_stat["passes"] += 1
        else:
            plat_stat["fails"] += 1

        # Running average of keyword density
        prev_avg = plat_stat.get("avg_density", 0.0)
        plat_stat["avg_density"] = round(((prev_avg * (total - 1)) + density_val) / total, 4)
        _save_data(data)


def get_learning_stats() -> Dict[str, Any]:
    """Retrieve summary metrics and learned domain counts."""
    with _LOCK:
        data = _load_data()
        domains = data.get("domains", {})
        return {
            "total_learned_domains": len(domains),
            "total_domains_learned": len(domains),
            "metrics": data.get("metrics", {}),
            "platform_audits": data.get("platform_audits", {}),
            "sample_domains": {k: v.get("platform_id") for k, v in list(domains.items())[:10]},
        }


def record_user_feedback(url_or_domain: str, platform_id: str, confirmed: bool = True) -> bool:
    """Convenience helper to record user feedback/override."""
    source = "user_confirm" if confirmed else "user_override"
    return record_domain_ats(url_or_domain, platform_id, source=source, confidence=1.0)
