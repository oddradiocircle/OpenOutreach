from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath

from crm.models import CampaignLead, Lead
from linkedin.url_utils import public_id_to_url, url_to_public_id


class LinkedInExportError(ValueError):
    """Raised when a LinkedIn export ZIP cannot be read as expected."""


@dataclass(frozen=True)
class ExportCsv:
    name: str
    rows: list[dict[str, str]]


@dataclass
class ImportSummary:
    files_processed: list[str]
    leads_created: int = 0
    leads_reused: int = 0
    campaign_leads_created: int = 0
    campaign_leads_updated: int = 0
    skipped_invalid_profile_urls: int = 0


def import_connections(zip_path: str, campaign) -> ImportSummary:
    """Import LinkedIn Connections.csv rows into a campaign lead queue."""
    summary = ImportSummary(files_processed=[])
    export_csv = read_export_csv(zip_path, "Connections.csv")
    if export_csv is None:
        return summary

    summary.files_processed.append(export_csv.name)
    for row in export_csv.rows:
        public_id = extract_profile_public_id(_row_value(row, "URL", "Profile URL", "Member Profile URL"))
        if not public_id:
            summary.skipped_invalid_profile_urls += 1
            continue

        lead, lead_created = Lead.objects.get_or_create(
            public_identifier=public_id,
            defaults={"linkedin_url": public_id_to_url(public_id)},
        )
        if lead_created:
            summary.leads_created += 1
        else:
            summary.leads_reused += 1

        metadata = _connection_metadata(row)
        connected_on = _parse_date(_row_value(row, "Connected On", "ConnectedOn"))
        _, campaign_lead_created = CampaignLead.objects.update_or_create(
            campaign=campaign,
            lead=lead,
            defaults={
                "source": CampaignLead.Source.LINKEDIN_CONNECTION,
                "relationship_status": CampaignLead.RelationshipStatus.CONNECTED,
                "priority": 10,
                "connected_on": connected_on,
                "metadata": metadata,
            },
        )
        if campaign_lead_created:
            summary.campaign_leads_created += 1
        else:
            summary.campaign_leads_updated += 1

    return summary


def list_export_files(zip_path: str) -> list[str]:
    """Return non-directory member names from a LinkedIn export ZIP."""
    with zipfile.ZipFile(zip_path) as archive:
        return [info.filename for info in archive.infolist() if not info.is_dir()]


def read_export_csv(zip_path: str, filename: str, required: bool = False) -> ExportCsv | None:
    """Read a CSV file from a LinkedIn export ZIP.

    LinkedIn exports may include files inside a top-level directory and some
    CSVs start with explanatory note rows before the actual header. This helper
    finds the member by basename and discards rows before the first useful
    header row.
    """
    with zipfile.ZipFile(zip_path) as archive:
        member = _find_member(archive, filename)
        if member is None:
            if required:
                raise LinkedInExportError(f"{filename} not found in LinkedIn export ZIP")
            return None

        with archive.open(member) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            return ExportCsv(name=member, rows=list(_dict_rows_after_header(text)))


def iter_export_csv(zip_path: str, filename: str, required: bool = False) -> Iterator[dict[str, str]]:
    export_csv = read_export_csv(zip_path, filename, required=required)
    if export_csv is None:
        return
    yield from export_csv.rows


def extract_profile_public_id(*values: str | None) -> str | None:
    """Return the first LinkedIn /in/ public identifier found in values."""
    for value in values:
        public_id = url_to_public_id(value or "")
        if public_id:
            return public_id
    return None


def lead_defaults_from_public_id(public_id: str) -> dict[str, str]:
    return {
        "public_identifier": public_id,
        "linkedin_url": public_id_to_url(public_id),
    }


def _find_member(archive: zipfile.ZipFile, filename: str) -> str | None:
    expected = filename.casefold()
    for member in archive.namelist():
        if PurePosixPath(member).name.casefold() == expected:
            return member
    return None


def _dict_rows_after_header(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    reader = csv.reader(lines)
    header: list[str] | None = None
    for row in reader:
        normalized = [_normalize_cell(cell) for cell in row]
        if header is None:
            if _looks_like_header(normalized):
                header = normalized
            continue
        if not any(normalized):
            continue
        yield {
            key: normalized[idx] if idx < len(normalized) else ""
            for idx, key in enumerate(header)
            if key
        }


def _looks_like_header(row: list[str]) -> bool:
    if not row:
        return False
    lowered = {cell.casefold() for cell in row if cell}
    return bool(lowered & {"url", "profile url", "from", "to", "sent date", "date"})


def _normalize_cell(value: str | None) -> str:
    return (value or "").strip()


def _row_value(row: dict[str, str], *keys: str) -> str:
    by_casefold = {key.casefold(): value for key, value in row.items()}
    for key in keys:
        value = by_casefold.get(key.casefold())
        if value:
            return value
    return ""


def _connection_metadata(row: dict[str, str]) -> dict[str, str]:
    fields = {
        "first_name": _row_value(row, "First Name", "FirstName"),
        "last_name": _row_value(row, "Last Name", "LastName"),
        "email": _row_value(row, "Email Address", "Email"),
        "company": _row_value(row, "Company"),
        "position": _row_value(row, "Position"),
        "profile_url": _row_value(row, "URL", "Profile URL", "Member Profile URL"),
    }
    full_name = " ".join(part for part in [fields["first_name"], fields["last_name"]] if part)
    if full_name:
        fields["name"] = full_name
    return {key: value for key, value in fields.items() if value}


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
