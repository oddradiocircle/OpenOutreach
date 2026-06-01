from __future__ import annotations

import csv
import hashlib
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
    invitations_imported: int = 0
    invitations_skipped: int = 0
    messages_imported: int = 0
    messages_skipped: int = 0
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


def import_invitations(zip_path: str, campaign) -> ImportSummary:
    """Import LinkedIn Invitations.csv rows into a campaign lead queue."""
    summary = ImportSummary(files_processed=[])
    export_csv = read_export_csv(zip_path, "Invitations.csv")
    if export_csv is None:
        return summary

    summary.files_processed.append(export_csv.name)
    for row in export_csv.rows:
        public_id = extract_profile_public_id(
            _row_value(row, "Profile URL", "URL", "Member Profile URL"),
            _row_value(row, "From Profile URL", "Inviter Profile URL", "Sender Profile URL"),
            _row_value(row, "To Profile URL", "Invitee Profile URL", "Recipient Profile URL"),
        )
        if not public_id:
            summary.skipped_invalid_profile_urls += 1
            summary.invitations_skipped += 1
            continue

        lead, lead_created = Lead.objects.get_or_create(
            public_identifier=public_id,
            defaults={"linkedin_url": public_id_to_url(public_id)},
        )
        if lead_created:
            summary.leads_created += 1
        else:
            summary.leads_reused += 1

        _, campaign_lead_created = CampaignLead.objects.update_or_create(
            campaign=campaign,
            lead=lead,
            defaults={
                "source": CampaignLead.Source.LINKEDIN_INVITATION,
                "relationship_status": CampaignLead.RelationshipStatus.INVITED,
                "priority": 20,
                "metadata": _invitation_metadata(row),
            },
        )
        if campaign_lead_created:
            summary.campaign_leads_created += 1
        else:
            summary.campaign_leads_updated += 1
        summary.invitations_imported += 1

    return summary


def import_messages(
    zip_path: str,
    campaign,
    owner_public_ids: set[str] | None = None,
    owner=None,
) -> ImportSummary:
    """Import LinkedIn messages.csv rows as Lead-linked ChatMessage rows."""
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType

    summary = ImportSummary(files_processed=[])
    export_csv = read_export_csv(zip_path, "messages.csv")
    if export_csv is None:
        return summary

    owner_public_ids = owner_public_ids or set()
    lead_ct = ContentType.objects.get_for_model(Lead)
    summary.files_processed.append(export_csv.name)

    for row in export_csv.rows:
        content = _row_value(row, "Content", "Message", "Text", "Body")
        if not content:
            summary.messages_skipped += 1
            continue

        sender_id = extract_profile_public_id(
            _row_value(row, "Sender Profile URL", "From Profile URL", "From"),
        )
        recipient_id = extract_profile_public_id(
            _row_value(row, "Recipient Profile URL", "To Profile URL", "To", "Recipients"),
        )
        counterparty_id = _counterparty_public_id(sender_id, recipient_id, owner_public_ids)
        if not counterparty_id:
            summary.skipped_invalid_profile_urls += 1
            summary.messages_skipped += 1
            continue

        lead, lead_created = Lead.objects.get_or_create(
            public_identifier=counterparty_id,
            defaults={"linkedin_url": public_id_to_url(counterparty_id)},
        )
        if lead_created:
            summary.leads_created += 1
        else:
            summary.leads_reused += 1

        is_outgoing = bool(sender_id and sender_id in owner_public_ids)
        creation_date = _parse_datetime(_row_value(row, "Date", "Created At", "Sent At", "Timestamp"))
        linkedin_urn = _synthetic_message_urn(row, content, is_outgoing)
        _, created = ChatMessage.objects.update_or_create(
            linkedin_urn=linkedin_urn,
            defaults={
                "content_type": lead_ct,
                "object_id": lead.pk,
                "content": content,
                "is_outgoing": is_outgoing,
                "owner": owner,
                **({"creation_date": creation_date} if creation_date else {}),
            },
        )
        if created:
            summary.messages_imported += 1
        else:
            summary.messages_skipped += 1

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
    return bool(lowered & {"url", "profile url", "from", "to", "sent date", "date"}) or any(
        cell.endswith("profile url") for cell in lowered
    )


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


def _invitation_metadata(row: dict[str, str]) -> dict[str, str]:
    fields = {
        "direction": _row_value(row, "Direction", "Invitation Direction", "Type"),
        "status": _row_value(row, "Status"),
        "sent_at": _row_value(row, "Sent At", "Sent Date", "Date", "Created At"),
        "message": _row_value(row, "Message", "Invite Message"),
        "from": _row_value(row, "From", "Inviter", "Sender"),
        "to": _row_value(row, "To", "Invitee", "Recipient"),
        "profile_url": _row_value(row, "Profile URL", "URL", "Member Profile URL"),
        "from_profile_url": _row_value(row, "From Profile URL", "Inviter Profile URL", "Sender Profile URL"),
        "to_profile_url": _row_value(row, "To Profile URL", "Invitee Profile URL", "Recipient Profile URL"),
    }
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


def _parse_datetime(value: str) -> datetime | None:
    from django.utils import timezone

    if not value:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d %b %Y, %H:%M",
        "%d %B %Y, %H:%M",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        except ValueError:
            continue
    parsed_date = _parse_date(value)
    if parsed_date:
        parsed = datetime.combine(parsed_date, datetime.min.time())
        return timezone.make_aware(parsed)
    return None


def _counterparty_public_id(
    sender_id: str | None,
    recipient_id: str | None,
    owner_public_ids: set[str],
) -> str | None:
    if sender_id and sender_id not in owner_public_ids:
        return sender_id
    if recipient_id and recipient_id not in owner_public_ids:
        return recipient_id
    return sender_id or recipient_id


def _synthetic_message_urn(row: dict[str, str], content: str, is_outgoing: bool) -> str:
    conversation_id = _row_value(row, "Conversation ID", "Conversation Id", "Conversation")
    timestamp = _row_value(row, "Date", "Created At", "Sent At", "Timestamp")
    direction = "out" if is_outgoing else "in"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    raw_key = "|".join([conversation_id, timestamp, direction, digest])
    stable = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"urn:openoutreach:linkedin-export-message:{stable}"
