"""Timezone utilities for display-side conversions.

All datetimes in the DB are stored as UTC (USE_TZ=True). This module
provides the display-timezone helpers used by admin, CLI, and agent code.
"""
from __future__ import annotations

import zoneinfo
from datetime import datetime


_FALLBACK_TZ = "America/Bogota"


def get_display_tz() -> zoneinfo.ZoneInfo:
    """Return the configured display timezone from SiteConfig."""
    try:
        from linkedin.models import SiteConfig
        name = (SiteConfig.load().display_timezone or "").strip() or _FALLBACK_TZ
        return zoneinfo.ZoneInfo(name)
    except Exception:
        return zoneinfo.ZoneInfo(_FALLBACK_TZ)


def localtime(dt: datetime | None) -> datetime | None:
    """Convert a UTC-aware datetime to the configured display timezone."""
    if dt is None:
        return None
    tz = get_display_tz()
    return dt.astimezone(tz)


def localfmt(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a UTC datetime in the display timezone. Returns "" if dt is None."""
    if dt is None:
        return ""
    return localtime(dt).strftime(fmt)
