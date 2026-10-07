"""platform_rules.py - Multi-ATS Platform Rules Engine.

Loads platform parameters from ats_registry.json into typed AtsProfile dataclasses
for downstream consumption across the 4-agent cooperative engine.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("platform_rules")

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "ats_registry.json")


@dataclass(frozen=True)
class AtsProfile:
    platform_id: str
    display_name: str
    url_signatures: List[str] = field(default_factory=list)
    matching_style: str = "exact_weighted"  # 'exact_weighted' | 'semantic'
    title_weight: str = "high"  # 'high' | 'medium' | 'low'
    format_tolerance: str = "strict"  # 'strict' | 'moderate' | 'lenient'
    allows_tables: bool = False
    allows_columns: bool = False
    allows_header_contact: bool = False
    keyword_density_ceiling: float = 0.015  # Default 1.5% ceiling
    cover_letter_scored: bool = False
    date_format: str = "MM/YYYY"
    quirks: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.platform_id

    def validate_resume_dict(self, resume: Dict[str, Any], jd_keywords: Optional[List[str]] = None, jd_title: Optional[str] = None) -> Dict[str, Any]:
        """Convenience method to validate a resume dict against this platform profile."""
        from human_voice_audit import audit_ats_compliance
        return audit_ats_compliance(resume, self, jd_keywords=jd_keywords, jd_title=jd_title)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize dataclass to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AtsProfile:
        """Create AtsProfile from dictionary with safe defaults."""
        return cls(
            platform_id=data.get("platform_id", "unknown"),
            display_name=data.get("display_name", "Safe Mode (Universal ATS Compatibility)"),
            url_signatures=list(data.get("url_signatures", [])),
            matching_style=data.get("matching_style", "exact_weighted"),
            title_weight=data.get("title_weight", "high"),
            format_tolerance=data.get("format_tolerance", "strict"),
            allows_tables=bool(data.get("allows_tables", False)),
            allows_columns=bool(data.get("allows_columns", False)),
            allows_header_contact=bool(data.get("allows_header_contact", False)),
            keyword_density_ceiling=float(data.get("keyword_density_ceiling", 0.015)),
            cover_letter_scored=bool(data.get("cover_letter_scored", False)),
            date_format=data.get("date_format", "MM/YYYY"),
            quirks=list(data.get("quirks", [])),
        )


_PROFILES_CACHE: Optional[Dict[str, AtsProfile]] = None


def _load_registry() -> Dict[str, AtsProfile]:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is not None:
        return _PROFILES_CACHE

    profiles: Dict[str, AtsProfile] = {}
    try:
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                platforms = data.get("platforms", {})
                for key, p_data in platforms.items():
                    profiles[key.lower()] = AtsProfile.from_dict(p_data)
        else:
            logger.warning("ats_registry.json not found at %s. Using default safe mode.", REGISTRY_PATH)
    except Exception as e:
        logger.error("Failed to load ats_registry.json: %s", e)

    # Guarantee fallback unknown exists
    if "unknown" not in profiles:
        profiles["unknown"] = AtsProfile(
            platform_id="unknown",
            display_name="Safe Mode (Universal ATS Compatibility)",
            url_signatures=[],
            matching_style="exact_weighted",
            title_weight="high",
            format_tolerance="strict",
            allows_tables=False,
            allows_columns=False,
            allows_header_contact=False,
            keyword_density_ceiling=0.015,
            cover_letter_scored=False,
            date_format="MM/YYYY",
            quirks=["Universal fail-safe standard: zero tables, 1.5% density ceiling."],
        )

    _PROFILES_CACHE = profiles
    return profiles


def get_profile(platform_key: Optional[str]) -> AtsProfile:
    """Retrieve an AtsProfile by platform key (case-insensitive).

    Falls back to 'unknown' Safe Mode if key is None or unrecognized.
    """
    profiles = _load_registry()
    if not platform_key:
        return profiles["unknown"]
    clean_key = str(platform_key).strip().lower()
    return profiles.get(clean_key, profiles["unknown"])


def get_safe_mode_profile() -> AtsProfile:
    """Return the universal strictest-common-denominator Safe Mode profile."""
    return get_profile("unknown")


def get_all_platforms() -> List[Dict[str, Any]]:
    """Return a list of all available platforms for populating UI dropdowns and options."""
    profiles = _load_registry()
    results = []
    # Order known platforms first, followed by safe mode at the end
    sorted_keys = [k for k in profiles if k != "unknown"] + ["unknown"]
    for key in sorted_keys:
        p = profiles[key]
        results.append({
            "platform_id": p.platform_id,
            "display_name": p.display_name,
            "matching_style": p.matching_style,
            "density_ceiling": f"{p.keyword_density_ceiling * 100:.1f}%",
            "format_tolerance": p.format_tolerance,
            "date_format": p.date_format,
            "cover_letter_scored": p.cover_letter_scored,
            "is_safe_mode": (key == "unknown"),
        })
    return results
