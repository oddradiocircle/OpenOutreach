# linkedin/pipeline_config.py
"""Resolved pipeline configuration for a campaign.

Resolution order for each field:
  1. Campaign-level override (if not None).
  2. SiteConfig singleton.
  3. Hardcoded fallback constant.
"""
from __future__ import annotations

from dataclasses import dataclass

# Hardcoded fallback constants (used only when SiteConfig row is absent).
_DEFAULTS = {
    "follow_up_cooldown_hours": 72,
    "reengagement_greeting_days": 3,
    "gpr_qualification_threshold": 0.85,
    "connect_daily_limit": 20,
    "follow_up_daily_limit": 25,
    "check_pending_daily_cap": 100,
    "max_followups_without_reply": 10,
    "min_qualification_observations_before_connect": 0,
    "preconnect_qualification_batch_size": 1,
}


@dataclass(frozen=True)
class PipelineConfig:
    follow_up_cooldown_hours: int
    reengagement_greeting_days: int
    gpr_qualification_threshold: float
    connect_daily_limit: int
    follow_up_daily_limit: int
    check_pending_daily_cap: int
    max_followups_without_reply: int
    min_qualification_observations_before_connect: int
    preconnect_qualification_batch_size: int


def get_campaign_config(campaign=None) -> PipelineConfig:
    """Return the effective PipelineConfig for *campaign*.

    campaign may be None (returns SiteConfig / fallback values only).
    """
    try:
        from linkedin.models import SiteConfig
        site = SiteConfig.load()
    except Exception:
        site = None

    def resolve(field: str):
        if campaign is not None:
            val = getattr(campaign, field, None)
            if val is not None:
                return val
        if site is not None:
            val = getattr(site, field, None)
            if val is not None:
                return val
        return _DEFAULTS[field]

    return PipelineConfig(
        follow_up_cooldown_hours=resolve("follow_up_cooldown_hours"),
        reengagement_greeting_days=resolve("reengagement_greeting_days"),
        gpr_qualification_threshold=resolve("gpr_qualification_threshold"),
        connect_daily_limit=resolve("connect_daily_limit"),
        follow_up_daily_limit=resolve("follow_up_daily_limit"),
        check_pending_daily_cap=resolve("check_pending_daily_cap"),
        max_followups_without_reply=resolve("max_followups_without_reply"),
        min_qualification_observations_before_connect=resolve("min_qualification_observations_before_connect"),
        preconnect_qualification_batch_size=resolve("preconnect_qualification_batch_size"),
    )
