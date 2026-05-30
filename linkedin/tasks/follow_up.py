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
    from crm.models import Deal

    deals = (
        Deal.objects.filter(
            campaign=campaign,
            state=ProfileState.CONNECTED,
            outcome="",
            lead__disqualified=False,
            pending_message="",
        )
        .exclude(lead_id__in=_leads_followed_up_elsewhere(campaign))
        .select_related("lead", "campaign")
        .order_by("update_date")
    )
    for deal in deals:
        if not _too_soon_to_nudge(deal):
            return deal
        # The last known message is outgoing — sync to catch any unseen reply,
        # then re-check so a reply unblocks the deal immediately.
        if session is not None:
            _sync_conversation_quietly(session, deal)
            if not _too_soon_to_nudge(deal):
                return deal
    return None


def _next_approved_deal(campaign):
    """Oldest CONNECTED deal in *campaign* with an approved message ready to send."""
    from crm.models import Deal

    return (
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
        .first()
    )


def _send_approved(session, deal) -> None:
    """Send a pre-approved pending message and clear the draft fields."""
    from linkedin.actions.message import send_raw_message
    from linkedin.db.deals import set_profile_state
    from linkedin.db.chat import sync_conversation

    campaign = session.campaign
    public_id = deal.lead.public_identifier
    message = deal.pending_message

    logger.info("[%s] %s %s (approved)", campaign, colored("▶ follow_up", "green", attrs=["bold"]), public_id)
    logger.info("[%s] sending approved message for %s: %s", campaign, public_id, message)

    sent = send_raw_message(session, _build_send_profile(deal), message)
    if not sent:
        logger.warning("follow_up for %s: approved send failed — will retry on next slot", public_id)
        return

    session.linkedin_profile.record_action(ActionLog.ActionType.FOLLOW_UP, campaign)
    deal.pending_message = ""
    deal.pending_message_approved = False
    deal.save()

    try:
        sync_conversation(session, public_id)
    except Exception:
        logger.exception("post-send sync failed for %s (best-effort)", public_id)


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
    approved = _next_approved_deal(campaign)
    if approved:
        _send_approved(session, approved)
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
            deal.pending_message = decision.message
            deal.pending_message_approved = False
            deal.save(update_fields=["pending_message", "pending_message_approved"])
            return

        logger.info("[%s] follow_up message for %s: %s", campaign, public_id, decision.message)
        sent = send_raw_message(session, profile, decision.message)
        if not sent:
            set_profile_state(session, public_id, ProfileState.QUALIFIED.value)
            logger.warning("follow_up for %s: send failed — moving to QUALIFIED for re-connection", public_id)
            return
        session.linkedin_profile.record_action(
            ActionLog.ActionType.FOLLOW_UP, session.campaign,
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
