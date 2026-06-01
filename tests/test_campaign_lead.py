import pytest
from django.db import IntegrityError

from crm.models import CampaignLead
from linkedin.models import Campaign
from tests.factories import LeadFactory


@pytest.mark.django_db
def test_campaign_lead_basic_creation_defaults():
    campaign = Campaign.objects.create(name="Warm Leads")
    lead = LeadFactory()

    campaign_lead = CampaignLead.objects.create(campaign=campaign, lead=lead)

    assert campaign_lead.source == CampaignLead.Source.MANUAL
    assert campaign_lead.relationship_status == CampaignLead.RelationshipStatus.UNKNOWN
    assert campaign_lead.priority == 100
    assert campaign_lead.metadata == {}
    assert campaign_lead.connected_on is None
    assert campaign_lead.creation_date is not None
    assert campaign_lead.update_date is not None


@pytest.mark.django_db
def test_campaign_lead_unique_per_campaign_and_lead():
    campaign = Campaign.objects.create(name="Unique Warm Leads")
    lead = LeadFactory()
    CampaignLead.objects.create(campaign=campaign, lead=lead)

    with pytest.raises(IntegrityError):
        CampaignLead.objects.create(campaign=campaign, lead=lead)


@pytest.mark.django_db
def test_campaign_lead_allows_same_lead_in_different_campaigns():
    lead = LeadFactory()
    first_campaign = Campaign.objects.create(name="First Campaign")
    second_campaign = Campaign.objects.create(name="Second Campaign")

    CampaignLead.objects.create(campaign=first_campaign, lead=lead)
    CampaignLead.objects.create(campaign=second_campaign, lead=lead)

    assert CampaignLead.objects.filter(lead=lead).count() == 2
