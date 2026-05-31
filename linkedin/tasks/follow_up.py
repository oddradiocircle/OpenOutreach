# linkedin/tasks/follow_up.py
"""Follow-up task — runs the agentic follow-up for one eligible CONNECTED deal."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone
from termcolor import colored

from linkedin.enums import ProfileState
from linkedin.models import ActionLog

logger = logging.getLogger(__name__)

# Required silence between nudges scales with unanswered count:
# 1 unanswered → 3d, 2 → 6d, 3 → 9d. Skips the LLM call while open.
MIN_DAYS_PER_UNANSWERED = 3

# Unicode spaces that LinkedIn rejects (narrow no-break space, non-breaking space, etc.)
_UNICODE_SPACES = "       　"


def _normalize_message(text: str) -> str:
    """Normalize message text before saving or sending.

    - Replaces Unicode space variants with ASCII space (avoids LinkedIn 400).
    - Strips carriage returns so \\r\\n → \\n, preventing Playwright from typing
      \\r and \\n as two separate Enter keypresses (which creates double blank lines).
    """
    text = text.translate(str.maketrans(_UNICODE_SPACES, " " * len(_UNICODE_SPACES)))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _build_send_profile(deal) -> dict:
    """Minimal profile dict for ``send_raw_message`` and its fallbacks."""
    lead = deal.lead
    return {
        "public_identifier": lead.public_identifier,
        "urn": lead.urn or "",
    }


def _too_soon_to_nudge(deal) -> bool:
    """Wait ``unanswered_count * MIN_DAYS_PER_UNANSWERED`` days between nudges."""
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(type(deal.lead))
    messages = ChatMessage.objects.filter(content_type=ct, object_id=deal.lead_id)

    last = messages.order_by("-creation_date").first()
    if last is None or not last.is_outgoing:
        return False

    last_reply = messages.filter(is_outgoing=False).order_by("-creation_date").first()
    nudges = messages.filter(is_outgoing=True)
    if last_reply:
        nudges = nudges.filter(creation_date__gt=last_reply.creation_date)

    required = timedelta(days=nudges.count() * MIN_DAYS_PER_UNANSWERED)
    return timezone.now() - last.creation_date < required


def _leads_followed_up_elsewhere(campaign):
    """Lead IDs that are Connected (active deal) in any campaign other than *campaign*.

    A lead being followed up in another campaign must not receive messages from
    this one — they would get two disconnected conversations from the same sender.
    The campaign whose deal became Connected first owns the conversation until
    that deal is resolved.
    """
    from crm.models import Deal

    return (
        Deal.objects.filter(state=ProfileState.CONNECTED, outcome="")
        .exclude(campaign=campaign)
        .values_list("lead_id", flat=True)
    )


def _sync_conversation_quietly(session, deal) -> None:
    """Sync the deal's LinkedIn conversation to catch unseen replies (best-effort)."""
    from linkedin.db.chat import sync_conversation
    try:
        sync_conversation(session, deal.lead.public_identifier)
    except Exception:
        logger.debug("pre-check sync failed for %s", deal.lead.public_identifier)


def _next_followup_deal(campaign, session=None):
    """Oldest CONNECTED deal in *campaign* eligible for a new follow-up draft."""
    from chat.models import ChatMessage
    from crm.models import Deal, Lead
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import OuterRef, Q, Subquery

    lead_ct_id = ContentType.objects.get_for_model(Lead).id
    last_msg_is_outgoing_sq = Subquery(
        ChatMessage.objects.filter(
            content_type_id=lead_ct_id,
            object_id=OuterRef("lead_id"),
        )
        .order_by("-creation_date")
        .values("is_outgoing")[:1]
    )

    base = (
        Deal.objects.filter(
            campaign=campaign,
            state=ProfileState.CONNECTED,
            outcome="",
            lead__disqualified=False,
            pending_message="",
        )
        .exclude(lead_id__in=_leads_followed_up_elsewhere(campaign))
        .select_related("lead", "campaign")
        .annotate(last_msg_is_outgoing=last_msg_is_outgoing_sq)
    )

    # Hot path: lead replied last — skip cooldown check, return oldest immediately.
    hot = base.filter(last_msg_is_outgoing=False).order_by("update_date").first()
    if hot is not None:
        return hot

    # Cold path: we sent last or no messages — apply existing cooldown + sync-to-unblock.
    for deal in base.filter(
        Q(last_msg_is_outgoing=True) | Q(last_msg_is_outgoing__isnull=True)
    ).order_by("update_date"):
        if not _too_soon_to_nudge(deal):
            return deal
        if session is not None:
            _sync_conversation_quietly(session, deal)
            if not _too_soon_to_nudge(deal):
                return deal
    return None


def _next_approved_deal(campaign):
    """Oldest CONNECTED deal in *campaign* with a valid approved message ready to send.

    Clears and skips drafts that became stale because the lead replied after approval.
    """
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType
    from crm.models import Deal

    candidates = (
        Deal.objects.filter(
            campaign=campaign,
            state=ProfileState.CONNECTED,
            outcome="",
            lead__disqualified=False,
            pending_message_approved=True,
        )
        .exclude(pending_message="")
        .exclude(lead_id__in=_leads_followed_up_elsewhere(campaign))
        .select_related("lead", "campaign")
        .order_by("update_date")
    )
    for deal in candidates:
        ct = ContentType.objects.get_for_model(type(deal.lead))
        last = ChatMessage.objects.filter(
            content_type=ct, object_id=deal.lead_id
        ).order_by("-creation_date").first()
        if last is not None and not last.is_outgoing:
            # Lead replied after approval — draft is stale, discard it.
            deal.pending_message = ""
            deal.pending_message_approved = False
            deal.save(update_fields=["pending_message", "pending_message_approved"])
            logger.info(
                "[%s] discarded stale draft for %s — lead replied since approval",
                campaign, deal.lead.public_identifier,
            )
            continue
        return deal
    return None


def _send_approved(session, deal) -> bool:
    """Send a pre-approved pending message and clear the draft fields.

    Returns True if the message was sent, False on failure (caller falls through
    to Phase 2 so other leads in the campaign are not blocked by a stuck send).
    """
    from linkedin.actions.message import send_raw_message
    from linkedin.db.deals import set_profile_state
    from linkedin.db.chat import sync_conversation

    campaign = session.campaign
    public_id = deal.lead.public_identifier
    message = _normalize_message(deal.pending_message)

    logger.info("[%s] %s %s (approved)", campaign, colored("▶ follow_up", "green", attrs=["bold"]), public_id)
    logger.info("[%s] sending approved message for %s: %s", campaign, public_id, message)

    sent = send_raw_message(session, _build_send_profile(deal), message)
    if not sent:
        logger.warning("follow_up for %s: approved send failed — skipping to Phase 2", public_id)
        return False

    session.linkedin_profile.record_action(ActionLog.ActionType.FOLLOW_UP, campaign, lead=deal.lead)
    deal.pending_message = ""
    deal.pending_message_approved = False
    deal.save()

    try:
        sync_conversation(session, public_id)
    except Exception:
        logger.exception("post-send sync failed for %s (best-effort)", public_id)
    return True


def handle_follow_up(task, session, qualifiers):
    from linkedin.actions.message import send_raw_message
    from linkedin.agents.follow_up import run_follow_up_agent
    from linkedin.db.deals import set_profile_state
    from linkedin.db.summaries import materialize_profile_summary_if_missing

    campaign = session.campaign

    if not session.linkedin_profile.can_execute(ActionLog.ActionType.FOLLOW_UP):
        logger.info("[%s] follow_up: daily limit reached — slot skipped", campaign)
        return

    # Send any pre-approved draft before generating new ones.
    # Only stop here if the send succeeded — a failed send falls through to
    # Phase 2 so other leads in the campaign are not blocked.
    approved = _next_approved_deal(campaign)
    if approved and _send_approved(session, approved):
        return

    deal = _next_followup_deal(campaign, session=session)
    if deal is None:
        logger.info("[%s] follow_up: no eligible CONNECTED deal — slot skipped", campaign)
        return

    public_id = deal.lead.public_identifier
    logger.info(
        "[%s] %s %s",
        campaign, colored("▶ follow_up", "green", attrs=["bold"]), public_id,
    )

    materialize_profile_summary_if_missing(deal, session)
    decision = run_follow_up_agent(session, deal)

    profile = _build_send_profile(deal)

    if decision.action == "send_message":
        if campaign.require_message_approval:
            logger.info(
                "[%s] follow_up draft for %s (pending approval): %s",
                campaign, public_id, decision.message,
            )
            deal.pending_message = _normalize_message(decision.message)
            deal.pending_message_approved = False
            deal.save(update_fields=["pending_message", "pending_message_approved"])
            return

        msg = _normalize_message(decision.message)
        logger.info("[%s] follow_up message for %s: %s", campaign, public_id, msg)
        sent = send_raw_message(session, profile, msg)
        if not sent:
            set_profile_state(session, public_id, ProfileState.QUALIFIED.value)
            logger.warning("follow_up for %s: send failed — moving to QUALIFIED for re-connection", public_id)
            return
        session.linkedin_profile.record_action(
            ActionLog.ActionType.FOLLOW_UP, session.campaign, lead=deal.lead,
        )
        from linkedin.db.chat import sync_conversation
        try:
            sync_conversation(session, public_id)
        except Exception:
            logger.exception("post-send sync failed for %s (best-effort)", public_id)
        deal.save()

    elif decision.action == "mark_completed":
        set_profile_state(session, public_id, ProfileState.COMPLETED.value, outcome=decision.outcome)
        logger.info("[%s] follow_up completed for %s: outcome=%s", campaign, public_id, decision.outcome)

    elif decision.action == "wait":
        deal.save()
