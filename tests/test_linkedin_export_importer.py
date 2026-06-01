import zipfile

import pytest

from chat.models import ChatMessage
from crm.models import CampaignLead, Lead
from linkedin.importers.linkedin_export import (
    import_connections,
    import_invitations,
    import_messages,
    read_export_csv,
)
from linkedin.models import Campaign


def _zip_with(tmp_path, files):
    path = tmp_path / "linkedin-export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return str(path)


@pytest.mark.django_db
def test_read_export_csv_skips_linkedin_notes(tmp_path):
    zip_path = _zip_with(
        tmp_path,
        {
            "Basic_LinkedInDataExport_01-01-2026/Connections.csv": (
                "Notes before the header\n"
                "Another note\n"
                "First Name,Last Name,URL,Company,Position,Connected On\n"
                "Ada,Lovelace,https://www.linkedin.com/in/ada-lovelace/,Analytical Engines,Founder,01/02/2026\n"
            ),
        },
    )

    export_csv = read_export_csv(zip_path, "Connections.csv", required=True)

    assert export_csv is not None
    assert export_csv.name.endswith("Connections.csv")
    assert export_csv.rows == [
        {
            "First Name": "Ada",
            "Last Name": "Lovelace",
            "URL": "https://www.linkedin.com/in/ada-lovelace/",
            "Company": "Analytical Engines",
            "Position": "Founder",
            "Connected On": "01/02/2026",
        },
    ]


@pytest.mark.django_db
def test_import_connections_is_idempotent_and_skips_invalid_urls(tmp_path):
    campaign = Campaign.objects.create(name="Warm Campaign")
    zip_path = _zip_with(
        tmp_path,
        {
            "Connections.csv": (
                "First Name,Last Name,URL,Company,Position,Email Address,Connected On\n"
                "Ada,Lovelace,https://www.linkedin.com/in/ada-lovelace/,Analytical Engines,Founder,ada@example.com,2026-01-02\n"
                "Bad,URL,https://www.linkedin.com/company/not-a-profile/,Widgets,Buyer,bad@example.com,2026-01-03\n"
            ),
        },
    )

    first = import_connections(zip_path, campaign)
    second = import_connections(zip_path, campaign)

    assert first.files_processed == ["Connections.csv"]
    assert first.leads_created == 1
    assert first.campaign_leads_created == 1
    assert first.skipped_invalid_profile_urls == 1
    assert second.leads_reused == 1
    assert second.campaign_leads_updated == 1
    assert second.skipped_invalid_profile_urls == 1
    assert Lead.objects.filter(public_identifier="ada-lovelace").count() == 1
    campaign_lead = CampaignLead.objects.get(campaign=campaign)
    assert campaign_lead.source == CampaignLead.Source.LINKEDIN_CONNECTION
    assert campaign_lead.relationship_status == CampaignLead.RelationshipStatus.CONNECTED
    assert campaign_lead.priority == 10
    assert campaign_lead.metadata["company"] == "Analytical Engines"


@pytest.mark.django_db
def test_import_invitations_creates_invited_campaign_lead(tmp_path):
    campaign = Campaign.objects.create(name="Invitation Campaign")
    zip_path = _zip_with(
        tmp_path,
        {
            "Invitations.csv": (
                "Direction,Status,Sent At,Message,To Profile URL\n"
                "OUTGOING,PENDING,2026-01-04,Hello,https://www.linkedin.com/in/grace-hopper/\n"
            ),
        },
    )

    summary = import_invitations(zip_path, campaign)

    assert summary.invitations_imported == 1
    campaign_lead = CampaignLead.objects.get(campaign=campaign)
    assert campaign_lead.lead.public_identifier == "grace-hopper"
    assert campaign_lead.source == CampaignLead.Source.LINKEDIN_INVITATION
    assert campaign_lead.relationship_status == CampaignLead.RelationshipStatus.INVITED
    assert campaign_lead.metadata["message"] == "Hello"


@pytest.mark.django_db
def test_import_messages_deduplicates_by_synthetic_linkedin_urn(tmp_path):
    campaign = Campaign.objects.create(name="Message Campaign")
    zip_path = _zip_with(
        tmp_path,
        {
            "messages.csv": (
                "Conversation ID,Date,Sender Profile URL,Recipient Profile URL,Content\n"
                "c1,2026-01-05 10:30:00,https://www.linkedin.com/in/me/,https://www.linkedin.com/in/katherine-johnson/,Hi Katherine\n"
                "c1,2026-01-05 10:31:00,https://www.linkedin.com/in/katherine-johnson/,https://www.linkedin.com/in/me/,Hello\n"
                "c2,2026-01-06 09:00:00,,https://www.linkedin.com/company/not-a-profile/,Skip me\n"
            ),
        },
    )

    first = import_messages(zip_path, campaign, owner_public_ids={"me"})
    second = import_messages(zip_path, campaign, owner_public_ids={"me"})

    assert first.messages_imported == 2
    assert first.messages_skipped == 1
    assert first.skipped_invalid_profile_urls == 1
    assert second.messages_imported == 0
    assert second.messages_skipped == 3
    assert ChatMessage.objects.count() == 2
    assert Lead.objects.get(public_identifier="katherine-johnson")
    assert list(ChatMessage.objects.order_by("creation_date").values_list("is_outgoing", flat=True)) == [True, False]
