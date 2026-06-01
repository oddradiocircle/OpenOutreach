# tests/test_regeneration.py
"""Tests for the Reject & Regenerate flow (Phase 4)."""
from unittest.mock import patch

import pytest

from tests.factories import DealFactory, LeadFactory


def _make_deal(campaign, state="connected", pending_message="Hello there"):
    lead = LeadFactory()
    deal = DealFactory(lead=lead, campaign=campaign, state=state)
    deal.pending_message = pending_message
    deal.pending_message_approved = False
    deal.save()
    return deal


@pytest.mark.django_db
def test_rejection_feedback_stored_on_deal(fake_session):
    from linkedin.models import Task

    deal = _make_deal(fake_session.campaign)
    deal.state = "connected"
    deal.save()

    deal.rejection_feedback = "Too formal"
    deal.regeneration_count = 1
    deal.pending_message = ""
    deal.save(update_fields=["rejection_feedback", "regeneration_count", "pending_message"])
    deal.refresh_from_db()

    assert deal.rejection_feedback == "Too formal"
    assert deal.regeneration_count == 1


@pytest.mark.django_db
def test_regeneration_count_incremented(fake_session):
    deal = _make_deal(fake_session.campaign)
    assert deal.regeneration_count == 0

    deal.regeneration_count += 1
    deal.save(update_fields=["regeneration_count"])
    deal.refresh_from_db()
    assert deal.regeneration_count == 1

    deal.regeneration_count += 1
    deal.save(update_fields=["regeneration_count"])
    deal.refresh_from_db()
    assert deal.regeneration_count == 2


@pytest.mark.django_db
def test_regenerated_draft_leaves_deal_pending(fake_session):
    """Regeneration task dispatch does not change deal state."""
    from django.utils import timezone
    from linkedin.models import Task

    deal = _make_deal(fake_session.campaign)
    deal.state = "connected"
    deal.save()

    feedback = "Mention their role more directly"
    deal.rejection_feedback = feedback
    deal.regeneration_count = (deal.regeneration_count or 0) + 1
    deal.pending_message = ""
    deal.pending_message_approved = False
    deal.save()

    Task.objects.create(
        task_type=Task.TaskType.FOLLOW_UP,
        scheduled_at=timezone.now(),
        payload={
            "campaign_id": deal.campaign_id,
            "deal_id": deal.pk,
            "regeneration_feedback": feedback,
        },
    )

    # State should remain connected (PENDING in terminology = awaiting draft approval)
    deal.refresh_from_db()
    assert deal.state == "connected"
    task = Task.objects.filter(task_type=Task.TaskType.FOLLOW_UP).first()
    assert task is not None
    assert task.payload["regeneration_feedback"] == feedback
    assert task.payload["deal_id"] == deal.pk


@pytest.mark.django_db
def test_feedback_appears_in_regenerated_prompt(fake_session):
    """regeneration_feedback is injected into the system prompt."""
    from linkedin.agents.follow_up import _render_system_prompt

    deal = _make_deal(fake_session.campaign)
    deal.profile_summary = {"facts": []}
    deal.chat_summary = {"facts": []}
    deal.save()

    feedback = "Be more casual and ask about their workflow"
    with patch("linkedin.db.chat.sync_conversation"):
        prompt = _render_system_prompt(fake_session, deal, [], regeneration_feedback=feedback)

    assert "Operator instructions" in prompt
    assert feedback in prompt


@pytest.mark.django_db
def test_prompt_without_feedback_has_no_operator_section(fake_session):
    """No feedback = no Operator instructions block."""
    from linkedin.agents.follow_up import _render_system_prompt

    deal = _make_deal(fake_session.campaign)
    deal.profile_summary = {"facts": []}
    deal.chat_summary = {"facts": []}
    deal.save()

    prompt = _render_system_prompt(fake_session, deal, [], regeneration_feedback=None)
    assert "Operator instructions" not in prompt


@pytest.mark.django_db
def test_cli_feedback_flag_creates_regen_task(fake_session):
    """--feedback flag creates immediate FOLLOW_UP task with regeneration payload."""
    from django.utils import timezone
    from typer.testing import CliRunner

    from linkedin.models import Task
    from oo_cli import app

    deal = _make_deal(fake_session.campaign)
    deal.state = "connected"
    deal.save()

    runner = CliRunner()
    result = runner.invoke(app, ["crm", "reject", str(deal.pk), "--feedback", "Too formal"])
    assert result.exit_code == 0, result.output

    deal.refresh_from_db()
    assert deal.rejection_feedback == "Too formal"
    assert deal.regeneration_count == 1
    assert deal.pending_message == ""

    task = Task.objects.filter(task_type=Task.TaskType.FOLLOW_UP).first()
    assert task is not None
    assert task.payload["regeneration_feedback"] == "Too formal"


@pytest.mark.django_db
def test_cli_without_feedback_hard_rejects(fake_session):
    """Without --feedback, original hard-reject behaviour is unchanged."""
    from typer.testing import CliRunner

    from linkedin.models import Task
    from oo_cli import app

    deal = _make_deal(fake_session.campaign)
    deal.state = "connected"
    deal.save()
    initial_count = deal.regeneration_count

    runner = CliRunner()
    result = runner.invoke(app, ["crm", "reject", str(deal.pk)])
    assert result.exit_code == 0, result.output

    deal.refresh_from_db()
    assert deal.pending_message == ""
    assert deal.regeneration_count == initial_count  # unchanged
    assert not Task.objects.filter(task_type=Task.TaskType.FOLLOW_UP).exists()
