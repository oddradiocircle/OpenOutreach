# linkedin/prompts.py
"""Prompt resolution: DB override → hardcoded .j2 / inline fallback.

Resolution order (Phase 1):
  1. Global PromptTemplate row in the DB.
  2. Hardcoded fallback: .j2 file from PROMPTS_DIR or inline constant.

Phase 2 will prepend campaign-level CampaignPromptOverride before the global row.
"""
from __future__ import annotations

import logging

from linkedin.conf import PROMPTS_DIR

logger = logging.getLogger(__name__)

# Keys that have a .j2 file fallback (filename without the directory prefix).
_J2_FALLBACKS: dict[str, str] = {
    "qualification": "qualify_lead.j2",
    "follow_up_agent": "follow_up_agent.j2",
}


def _inline_fallback(key: str) -> str | None:
    """Return inline hardcoded text for keys that have no .j2 file."""
    if key == "profile_fact_extraction":
        from linkedin.db.summaries import _FACT_EXTRACTION_PROMPT
        return _FACT_EXTRACTION_PROMPT
    if key == "chat_fact_reconciliation":
        from linkedin.vendor.mem0.configs.prompts import DEFAULT_UPDATE_MEMORY_PROMPT
        return DEFAULT_UPDATE_MEMORY_PROMPT
    return None


def _load_fallback(key: str) -> str:
    """Load hardcoded fallback for `key` — .j2 file first, then inline constant."""
    j2_file = _J2_FALLBACKS.get(key)
    if j2_file:
        return (PROMPTS_DIR / j2_file).read_text(encoding="utf-8")
    inline = _inline_fallback(key)
    if inline is not None:
        return inline
    return ""


def get_prompt(key: str, campaign=None) -> str:
    """Resolve the prompt body for `key`.

    Resolution order:
      1. Campaign-level CampaignPromptOverride (Phase 2 — not yet wired).
      2. Global PromptTemplate row from the DB.
      3. Hardcoded fallback (.j2 file or inline constant).
    """
    if campaign is not None:
        try:
            from linkedin.models import CampaignPromptOverride
            override = CampaignPromptOverride.objects.get(campaign=campaign, prompt_key=key)
            return override.body
        except Exception:
            pass

    try:
        from linkedin.models import PromptTemplate
        return PromptTemplate.objects.get(key=key).body
    except Exception:
        logger.debug("get_prompt: no DB row for key=%r — using hardcoded fallback", key)
        return _load_fallback(key)
