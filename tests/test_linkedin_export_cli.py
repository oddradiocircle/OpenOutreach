import zipfile

import pytest
from typer.testing import CliRunner

from crm.models import CampaignLead, Lead
from linkedin.models import Campaign
from oo_cli import app


def _zip_with(tmp_path, files):
    path = tmp_path / "linkedin-export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.mark.django_db
def test_linkedin_import_export_cli_success(tmp_path):
    campaign = Campaign.objects.create(name="CLI Warm Campaign")
    zip_path = _zip_with(
        tmp_path,
        {
            "Connections.csv": (
                "First Name,Last Name,URL,Company,Position,Connected On\n"
                "Ada,Lovelace,https://www.linkedin.com/in/ada-cli/,Analytical Engines,Founder,2026-01-02\n"
            ),
        },
    )

    result = CliRunner().invoke(
        app,
        ["linkedin", "import-export", str(zip_path), "--campaign", "CLI Warm"],
    )

    assert result.exit_code == 0, result.output
    assert "Imported LinkedIn export into campaign" in result.output
    assert "leads created" in result.output
    assert Lead.objects.filter(public_identifier="ada-cli").exists()
    assert CampaignLead.objects.filter(campaign=campaign, lead__public_identifier="ada-cli").exists()


@pytest.mark.django_db
def test_linkedin_import_export_cli_missing_campaign(tmp_path):
    zip_path = _zip_with(tmp_path, {"Connections.csv": "First Name,Last Name,URL\n"})

    result = CliRunner().invoke(
        app,
        ["linkedin", "import-export", str(zip_path), "--campaign", "Does Not Exist"],
    )

    assert result.exit_code == 1
    assert "No campaign matching" in result.output


@pytest.mark.django_db
def test_linkedin_import_export_cli_missing_file():
    Campaign.objects.create(name="Existing Campaign")

    result = CliRunner().invoke(
        app,
        ["linkedin", "import-export", "/tmp/openoutreach-missing-linkedin-export.zip", "--campaign", "Existing"],
    )

    assert result.exit_code == 1
    assert "LinkedIn export ZIP not found" in result.output


@pytest.mark.django_db
def test_linkedin_import_export_cli_idempotent_rerun(tmp_path):
    Campaign.objects.create(name="Idempotent Campaign")
    zip_path = _zip_with(
        tmp_path,
        {
            "Connections.csv": (
                "First Name,Last Name,URL,Company,Position,Connected On\n"
                "Grace,Hopper,https://www.linkedin.com/in/grace-cli/,COBOL,Admiral,2026-01-02\n"
            ),
        },
    )
    runner = CliRunner()

    first = runner.invoke(app, ["linkedin", "import-export", str(zip_path), "--campaign", "Idempotent"])
    second = runner.invoke(app, ["linkedin", "import-export", str(zip_path), "--campaign", "Idempotent"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert Lead.objects.filter(public_identifier="grace-cli").count() == 1
    assert CampaignLead.objects.filter(lead__public_identifier="grace-cli").count() == 1
    assert "campaign leads updated" in second.output
