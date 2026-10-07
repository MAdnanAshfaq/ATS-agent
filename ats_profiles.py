"""ats_profiles.py - Compatibility bridge and profile provider for Multi-ATS engine.

Delegates to platform_rules.py to provide consistent interface across modules.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from platform_rules import (
    AtsProfile,
    get_profile,
    get_safe_mode_profile,
    get_all_platforms,
    _load_registry,
    REGISTRY_PATH,
)


def get_all_profiles() -> Dict[str, AtsProfile]:
    """Return dictionary mapping platform_id to AtsProfile."""
    return _load_registry()


def get_platform_options() -> List[Dict[str, Any]]:
    """Return formatted options list for UI select boxes."""
    return get_all_platforms()


ATSProfile = AtsProfile
ATS_PROFILES = get_all_profiles()

__all__ = [
    "AtsProfile",
    "ATSProfile",
    "get_profile",
    "get_safe_mode_profile",
    "get_all_profiles",
    "get_all_platforms",
    "list_profiles",
    "get_platform_options",
    "ATS_PROFILES",
    "REGISTRY_PATH",
]

