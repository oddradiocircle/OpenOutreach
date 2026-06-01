import logging
import random
import time
from typing import Dict, Any, Optional

from django.db import transaction

from linkedin.url_utils import url_to_public_id, public_id_to_url
from linkedin.enums import ProfileState

logger = logging.getLogger(__name__)


def lead_exists(url: str) -> bool:
    """Check if Lead already exists for this LinkedIn URL."""
    from crm.models import Lead

    pid = url_to_public_id(url)
    if not pid:
        return False
    return Lead.objects.filter(public_identifier=pid).exists()


def create_enriched_lead(session, url: str, profile: Dict[str, Any]) -> Optional[int]:
    """Create Lead with full profile data and embedding.

    Returns lead PK or None if exists.
    Does NOT create Deal — that comes at qualification.
    """
    from crm.models import Lead

    # Use canonical public_identifier from Voyager response when available.
    canonical_pid = profile.get("public_identifier")
    public_id = canonical_pid or url_to_public_id(url)
    clean_url = public_id_to_url(public_id)

    urn = profile.get("urn") or None

    with transaction.atomic():
        if Lead.objects.filter(public_identifier=public_id).exists():
            return None
        if urn and Lead.objects.filter(urn=urn).exists():
            logger.info(
                "Lead with URN %s already exists — skipping duplicate %s",
                urn, public_id,
            )
            return None
        positions = profile.get("positions") or [{}]
        lead = Lead.objects.create(
            linkedin_url=clean_url,
            public_identifier=public_id,
            full_name=profile.get("full_name") or "",
            first_name=profile.get("first_name") or "",
            headline=profile.get("headline") or "",
            industry=(profile.get("industry") or {}).get("name") or "",
            current_company=positions[0].get("company_name") or "",
            current_title=positions[0].get("title") or "",
            location=profile.get("location_name") or "",
            country_code=profile.get("country_code") or "",
            languages=profile.get("supported_locales") or [],
        )
        _cache_urn_from_profile(lead, profile)

    lead.embed_from_profile(profile)

    logger.debug("Created enriched lead for %s (pk=%d)", public_id, lead.pk)
    return lead.pk


@transaction.atomic
def promote_lead_to_deal(session, public_id: str, reason: str = ""):
    """Create a Deal for a positively qualified Lead.

    Already-connected campaign leads are created directly as CONNECTED;
    other leads start as QUALIFIED and proceed through the connect flow.
    Returns the Deal.
    """
    from crm.models import CampaignLead, Lead, Deal

    lead = Lead.objects.filter(public_identifier=public_id).first()
    if not lead:
        raise ValueError(f"No Lead for {public_id}")

    relationship_status = get_campaign_lead_relationship_status(session, public_id)
    state = (
        ProfileState.CONNECTED
        if relationship_status == CampaignLead.RelationshipStatus.CONNECTED
        else ProfileState.QUALIFIED
    )
    deal = Deal.objects.create(
        lead=lead,
        campaign=session.campaign,
        state=state,
        reason=reason,
    )

    from termcolor import colored
    label = "CONNECTED" if state == ProfileState.CONNECTED else "QUALIFIED"
    logger.info("%s %s", public_id, colored(label, "green", attrs=["bold"]))
    return deal


def get_leads_for_qualification(session) -> list:
    """Leads eligible for qualification in the current campaign.

    Returns profile dicts for leads that are not permanently disqualified
    and have no Deal in this campaign.
    """
    from crm.models import CampaignLead, Lead

    campaign_leads = (
        CampaignLead.objects
        .filter(campaign=session.campaign, lead__disqualified=False)
        .exclude(lead__deal__campaign=session.campaign)
        .select_related("lead")
        .order_by("priority", "creation_date")
    )
    queued = []
    queued_lead_ids = set()
    for campaign_lead in campaign_leads:
        profile = campaign_lead.lead.to_profile_dict()
        profile["meta"].update({
            "campaign_lead_id": campaign_lead.pk,
            "campaign_lead_source": campaign_lead.source,
            "relationship_status": campaign_lead.relationship_status,
            "priority": campaign_lead.priority,
        })
        queued.append(profile)
        queued_lead_ids.add(campaign_lead.lead_id)

    fallback_leads = Lead.objects.filter(
        disqualified=False,
    ).exclude(
        deal__campaign=session.campaign,
    ).exclude(
        pk__in=queued_lead_ids,
    ).order_by(
        "creation_date",
    )

    return queued + [lead.to_profile_dict() for lead in fallback_leads]


def get_campaign_lead_relationship_status(session, public_id: str) -> str | None:
    """Return this lead's CampaignLead relationship status for session.campaign."""
    from crm.models import CampaignLead

    return (
        CampaignLead.objects
        .filter(campaign=session.campaign, lead__public_identifier=public_id)
        .values_list("relationship_status", flat=True)
        .first()
    )


def update_lead_slug(old_public_id: str, new_public_id: str):
    """Update a Lead after LinkedIn redirected its vanity URL."""
    from crm.models import Lead

    new_url = public_id_to_url(new_public_id)
    updated = Lead.objects.filter(public_identifier=old_public_id).update(
        public_identifier=new_public_id,
        linkedin_url=new_url,
    )
    if updated:
        logger.info("Lead slug updated: %s → %s", old_public_id, new_public_id)
    return updated


def disqualify_lead(public_id: str):
    """Set Lead.disqualified = True (account-level, permanent, cross-campaign)."""
    from crm.models import Lead

    lead = Lead.objects.filter(public_identifier=public_id).first()
    if not lead:
        logger.warning("disqualify_lead: no Lead for %s", public_id)
        return
    lead.disqualified = True
    lead.save(update_fields=["disqualified"])


def discover_and_enrich(session, urls):
    """For each new URL, call Voyager API, create enriched Lead (with embedding).

    Skips URLs that already have a Lead, caps at enrich_max_per_page (DOM
    order — LinkedIn's own relevance), and pauses a human-ish
    [enrich_min_delay_seconds, enrich_max_delay_seconds] between scrapes.
    """
    from linkedin.api.client import PlaywrightLinkedinAPI
    from linkedin.conf import CAMPAIGN_CONFIG

    new_urls = [u for u in urls if not lead_exists(u)]
    if not new_urls:
        return

    max_per_page = CAMPAIGN_CONFIG["enrich_max_per_page"]
    if len(new_urls) > max_per_page:
        new_urls = new_urls[:max_per_page]

    logger.info("Discovered %d new profiles (%d total on page)", len(new_urls), len(urls))

    min_delay = CAMPAIGN_CONFIG["enrich_min_delay_seconds"]
    max_delay = CAMPAIGN_CONFIG["enrich_max_delay_seconds"]
    session.ensure_browser()
    api = PlaywrightLinkedinAPI(session=session)
    enriched = 0

    for url in new_urls:
        public_id = url_to_public_id(url)
        if not public_id:
            continue

        try:
            profile, _raw = api.get_profile(profile_url=url)
        except Exception:
            logger.warning("Voyager API failed for %s — skipping", url)
            continue

        if not profile:
            logger.warning("Empty profile for %s — skipping", url)
            continue

        lead_pk = create_enriched_lead(session, url, profile)
        if lead_pk is not None:
            _attach_search_campaign_lead(session.campaign, lead_pk)
            enriched += 1

        time.sleep(random.uniform(min_delay, max_delay))

    logger.info("Enriched %d/%d new profiles", enriched, len(new_urls))


def _attach_search_campaign_lead(campaign, lead_pk: int):
    from crm.models import CampaignLead

    CampaignLead.objects.get_or_create(
        campaign=campaign,
        lead_id=lead_pk,
        defaults={
            "source": CampaignLead.Source.LINKEDIN_SEARCH,
            "relationship_status": CampaignLead.RelationshipStatus.UNKNOWN,
            "priority": 50,
        },
    )


def _cache_urn_from_profile(lead, profile: Dict[str, Any]):
    """Promote ``profile['urn']`` onto the Lead row if not already cached.

    The only durable field we extract from a fresh scrape — everything
    else lives in memory for the lifetime of the caller's dict.
    """
    urn = profile.get("urn") or None
    if urn and lead.urn != urn:
        lead.urn = urn
        lead.save(update_fields=["urn"])
