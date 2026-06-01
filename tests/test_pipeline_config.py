# tests/test_pipeline_config.py
"""Tests for get_campaign_config() resolver."""
import pytest

from linkedin.pipeline_config import PipelineConfig, get_campaign_config, _DEFAULTS


@pytest.mark.django_db
def test_returns_siteconfig_values_when_no_campaign_override():
    from linkedin.models import SiteConfig

    site = SiteConfig.load()
    site.follow_up_cooldown_hours = 48
    site.reengagement_greeting_days = 5
    site.gpr_qualification_threshold = 0.75
    site.check_pending_daily_cap = 50
    site.max_followups_without_reply = 7
    site.save()

    cfg = get_campaign_config()
    assert cfg.follow_up_cooldown_hours == 48
    assert cfg.reengagement_greeting_days == 5
    assert cfg.gpr_qualification_threshold == 0.75
    assert cfg.check_pending_daily_cap == 50
    assert cfg.max_followups_without_reply == 7


@pytest.mark.django_db
def test_campaign_override_takes_precedence_over_siteconfig():
    from linkedin.models import Campaign, SiteConfig

    site = SiteConfig.load()
    site.follow_up_cooldown_hours = 72
    site.save()

    campaign = Campaign.objects.create(name="Override Campaign", follow_up_cooldown_hours=24)
    cfg = get_campaign_config(campaign)
    assert cfg.follow_up_cooldown_hours == 24


@pytest.mark.django_db
def test_null_campaign_field_falls_through_to_siteconfig():
    from linkedin.models import Campaign, SiteConfig

    site = SiteConfig.load()
    site.follow_up_cooldown_hours = 96
    site.save()

    campaign = Campaign.objects.create(name="No Override Campaign")  # follow_up_cooldown_hours=None
    cfg = get_campaign_config(campaign)
    assert cfg.follow_up_cooldown_hours == 96


@pytest.mark.django_db
def test_fallback_constants_used_when_siteconfig_missing():
    from linkedin.models import SiteConfig

    SiteConfig.objects.all().delete()
    cfg = get_campaign_config()
    assert cfg.follow_up_cooldown_hours == _DEFAULTS["follow_up_cooldown_hours"]
    assert cfg.reengagement_greeting_days == _DEFAULTS["reengagement_greeting_days"]
    assert cfg.check_pending_daily_cap == _DEFAULTS["check_pending_daily_cap"]


@pytest.mark.django_db
def test_returns_pipeline_config_dataclass():
    cfg = get_campaign_config()
    assert isinstance(cfg, PipelineConfig)
