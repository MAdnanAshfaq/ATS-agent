"""ats_detector.py - Multi-ATS Platform Detection with Learned Domain Memory & HTML Inspection.

Detects target ATS platform from:
1. Continuous learning memory (user-confirmed/overridden domain mappings).
2. Built-in platform URL signatures.
3. HTML source fingerprints (for scraped job pages on custom corporate domains).
4. Zero-guesswork fallback: Safe Mode (strictest common denominator).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from ats_learning import lookup_learned_domain
from platform_rules import AtsProfile, get_all_platforms, get_profile, get_safe_mode_profile, _load_registry

logger = logging.getLogger("ats_detector")

# HTML and text fingerprints for custom corporate domains embedding ATS iframes or widgets
HTML_FINGERPRINTS = {
    "greenhouse": [
        "boards.greenhouse.io",
        "greenhouse.io",
        "gh_src",
        "grnhse",
        "greenhouse-embed",
        "api.greenhouse.io",
        "powered by greenhouse",
    ],
    "lever": [
        "jobs.lever.co",
        "lever.co",
        "lever-jobs-container",
        "lever.co/embed",
        "lever-apply",
        "powered by lever",
    ],
    "workday": [
        "myworkdayjobs.com",
        "workday.com",
        "wd-job-posting",
        "workdaycdn.com",
        "workday-job-details",
        "wday",
        "powered by workday",
        "workday careers",
    ],
    "icims": [
        "icims.com",
        "icims-wrapper",
        "careers-icims",
        "icims-content",
        "powered by icims",
    ],
    "taleo": [
        "taleo.net",
        "taleo-job",
        "oraclecloud.com/career",
        "powered by taleo",
    ],
    "ashby": [
        "ashbyhq.com",
        "jobs.ashbyhq.com",
        "ashby-job-posting",
        "powered by ashby",
    ],
    "smartrecruiters": [
        "smartrecruiters.com",
        "smartrecruiters-widget",
        "st-apply",
        "powered by smartrecruiters",
    ],
    "workable": [
        "workable.com",
        "apply.workable.com",
        "workable-jobs",
        "powered by workable",
    ],
    "bamboohr": [
        "bamboohr.com/jobs",
        "bamboohr.com",
        "bamboohr-embed",
        "powered by bamboohr",
    ],
    "jobvite": [
        "jobvite.com",
        "jobvite-job-board",
        "powered by jobvite",
    ],
    "successfactors": [
        "successfactors.com",
        "successfactors.eu",
        "jobs2web.com",
        "powered by successfactors",
    ],
}


def detect_ats_from_url(
    url: str,
    html_content: Optional[str] = None,
) -> Tuple[AtsProfile, float, str, bool]:
    """Detect ATS platform from URL, learning memory, or HTML content.

    Returns:
        (profile, confidence, source, detected)
        - profile: The resolved AtsProfile dataclass.
        - confidence: Float 0.0 to 1.0 representing detection confidence.
        - source: 'learned_memory' | 'url_signature' | 'html_fingerprint' | 'safe_mode_fallback'.
        - detected: True if matched; False if defaulted to Safe Mode.
    """
    if not url or not url.strip():
        return get_safe_mode_profile(), 0.0, "safe_mode_fallback", False

    clean_url = url.strip()

    # Step 1: Check continuous learning memory (learned from past user overrides/confirmations)
    learned = lookup_learned_domain(clean_url)
    if learned:
        platform_id, conf = learned
        profile = get_profile(platform_id)
        logger.info("ATS detected via continuous learning: %s -> %s (conf: %.2f)", clean_url, platform_id, conf)
        return profile, conf, "learned_memory", True

    # Step 2: Check built-in URL signatures from ats_registry.json
    parsed = urlparse(clean_url if "://" in clean_url else f"https://{clean_url}")
    host = (parsed.netloc or "").lower()
    full_url_lower = clean_url.lower()

    registry = _load_registry()
    for plat_id, profile in registry.items():
        if plat_id == "unknown":
            continue
        for sig in profile.url_signatures:
            sig_lower = sig.lower()
            if sig_lower in host or sig_lower in full_url_lower:
                logger.info("ATS detected via URL signature: %s matches %s -> %s", clean_url, sig, plat_id)
                return profile, 0.95, "url_signature", True

    # Step 3: Check HTML source fingerprints (for custom domains embedding third-party ATSs)
    if html_content:
        html_lower = html_content.lower()
        for plat_id, signatures in HTML_FINGERPRINTS.items():
            for sig in signatures:
                if sig.lower() in html_lower:
                    profile = get_profile(plat_id)
                    logger.info("ATS detected via HTML fingerprint: %s in page -> %s", sig, plat_id)
                    return profile, 0.85, "html_fingerprint", True

    # Step 4: Zero-guesswork fallback - Safe Mode
    logger.info("ATS unrecognized for %s; applying Safe Mode (Universal Compatibility).", clean_url)
    return get_safe_mode_profile(), 0.0, "safe_mode_fallback", False


def detect_ats_from_text(text: str) -> Tuple[AtsProfile, float, str, bool]:
    """Detect ATS platform from job description prose or embedded text.

    Scans text for URLs, mentions of ATS providers, or system fingerprints.
    """
    if not text or not text.strip():
        return get_safe_mode_profile(), 0.0, "safe_mode_fallback", False

    # Check for embedded URLs in text
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    for u in urls:
        prof, conf, src, det = detect_ats_from_url(u)
        if det:
            return prof, conf, f"text_embedded_url_{src}", True

    # Check HTML fingerprints against text
    text_lower = text.lower()
    for plat_id, signatures in HTML_FINGERPRINTS.items():
        for sig in signatures:
            if sig.lower() in text_lower:
                profile = get_profile(plat_id)
                return profile, 0.80, "text_fingerprint", True

    return get_safe_mode_profile(), 0.0, "safe_mode_fallback", False


def detect_ats(
    url_or_text: str,
    html_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Public helper returning a dictionary suitable for API responses and UI dropdowns."""
    profile, confidence, source, detected = detect_ats_from_url(url_or_text, html_content=html_content)
    return {
        "platform_id": profile.platform_id,
        "display_name": profile.display_name,
        "confidence": round(confidence, 2),
        "source": source,
        "detected": detected,
        "profile": profile.to_dict(),
        "all_platforms": get_all_platforms(),
    }
