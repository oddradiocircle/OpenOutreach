"""oo — OpenOutreach local CLI."""
import os
import sys
import zipfile
from pathlib import Path
from typing import Optional

import typer

# Bootstrap Django before any ORM import
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin.django_settings")
sys.path.insert(0, str(Path(__file__).parent))
import django
django.setup()

from rich.console import Console
from rich.table import Table, box as rbox

console = Console(highlight=False)

app = typer.Typer(
    name="oo",
    help="OpenOutreach local CLI — manage campaigns, leads, deals, tasks, and keywords.",
    no_args_is_help=True,
    add_completion=False,
)
crm_app = typer.Typer(help="Browse and edit CRM data.", no_args_is_help=True)
campaign_app = typer.Typer(help="Manage campaigns.", no_args_is_help=True)
task_app = typer.Typer(help="Inspect the task queue.", no_args_is_help=True)
keyword_app = typer.Typer(help="Manage search keywords.", no_args_is_help=True)
prompt_app = typer.Typer(help="Manage global and per-campaign LLM prompt templates.", no_args_is_help=True)
config_app = typer.Typer(help="Manage pipeline configuration (global and per-campaign).", no_args_is_help=True)
linkedin_app = typer.Typer(help="Import and inspect LinkedIn first-party data.", no_args_is_help=True)

app.add_typer(crm_app, name="crm")
app.add_typer(campaign_app, name="campaign")
app.add_typer(task_app, name="task")
app.add_typer(keyword_app, name="keyword")
app.add_typer(prompt_app, name="prompt")
app.add_typer(config_app, name="config")
app.add_typer(linkedin_app, name="linkedin")

# ── colour maps ────────────────────────────────────────────────────────────────
# Keys match ProfileState.value ("Qualified", "Ready to Connect", …)

STATE_COLOR = {
    "Qualified": "cyan",
    "Ready to Connect": "blue",
    "Pending": "yellow",
    "Connected": "green",
    "Completed": "bright_green",
    "Failed": "red",
}
OUTCOME_COLOR = {
    "converted": "bright_green",
    "not_interested": "red",
    "wrong_fit": "red",
    "no_budget": "yellow",
    "has_solution": "yellow",
    "bad_timing": "yellow",
    "unresponsive": "dim",
    "unknown": "dim",
    "": "dim",
}
VALID_STATES = list(STATE_COLOR.keys())
VALID_OUTCOMES = [k for k in OUTCOME_COLOR if k]
LINKEDIN_EXPORT_FILES = ("Connections.csv", "Invitations.csv", "messages.csv")


def _sc(state: str) -> str:
    c = STATE_COLOR.get(state, "white")
    return f"[{c}]{state}[/{c}]"


def _oc(outcome: str) -> str:
    c = OUTCOME_COLOR.get(outcome, "dim")
    return f"[{c}]{outcome or '—'}[/{c}]"


def _get_campaign(name: str):
    from linkedin.models import Campaign
    try:
        return Campaign.objects.get(name__icontains=name)
    except Campaign.DoesNotExist:
        console.print(f"[red]No campaign matching '{name}'[/red]")
        raise typer.Exit(1)
    except Campaign.MultipleObjectsReturned:
        console.print(f"[yellow]Multiple campaigns match '{name}' — be more specific[/yellow]")
        raise typer.Exit(1)


def _validate_linkedin_export_zip(zip_path: Path) -> list[str]:
    from linkedin.importers.linkedin_export import list_export_files

    if not zip_path.exists():
        console.print(f"[red]LinkedIn export ZIP not found: {zip_path}[/red]")
        raise typer.Exit(1)
    if not zip_path.is_file():
        console.print(f"[red]LinkedIn export path is not a file: {zip_path}[/red]")
        raise typer.Exit(1)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_file = archive.testzip()
    except zipfile.BadZipFile:
        console.print(f"[red]LinkedIn export is not a readable ZIP: {zip_path}[/red]")
        raise typer.Exit(1)

    if bad_file:
        console.print(f"[red]LinkedIn export ZIP failed integrity check at: {bad_file}[/red]")
        raise typer.Exit(1)

    files = list_export_files(str(zip_path))
    basenames = {path.name.casefold() for path in map(Path, files)}
    present = [name for name in LINKEDIN_EXPORT_FILES if name.casefold() in basenames]
    missing = [name for name in LINKEDIN_EXPORT_FILES if name.casefold() not in basenames]
    if missing:
        console.print(f"[yellow]Missing expected LinkedIn export files: {', '.join(missing)}[/yellow]")
    if not present:
        console.print("[red]No supported LinkedIn export CSV files found.[/red]")
        raise typer.Exit(1)
    return present


def _print_linkedin_import_summary(campaign_name: str, summaries) -> None:
    files = []
    for summary in summaries:
        files.extend(summary.files_processed)

    def total(field: str) -> int:
        return sum(getattr(summary, field, 0) for summary in summaries)

    console.print(f"[green]Imported LinkedIn export into campaign '{campaign_name}'.[/green]")
    console.print(f"[dim]processed files:[/dim] {', '.join(files) if files else 'none'}")

    table = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("leads created", str(total("leads_created")))
    table.add_row("leads reused", str(total("leads_reused")))
    table.add_row("campaign leads created", str(total("campaign_leads_created")))
    table.add_row("campaign leads updated", str(total("campaign_leads_updated")))
    table.add_row("invitations imported", str(total("invitations_imported")))
    table.add_row("invitations skipped", str(total("invitations_skipped")))
    table.add_row("messages imported", str(total("messages_imported")))
    table.add_row("messages skipped", str(total("messages_skipped")))
    table.add_row("invalid profile URLs skipped", str(total("skipped_invalid_profile_urls")))
    console.print(table)


# ── status ─────────────────────────────────────────────────────────────────────

@app.command()
def status():
    """System overview: campaigns, deals, task queue, activity today."""
    from crm.models import Deal
    from linkedin.models import ActionLog, Campaign, Task
    from django.db.models import Count
    from django.utils import timezone

    now = timezone.now()

    campaigns = Campaign.objects.all()
    console.print("\n[bold]Campaigns[/bold]")
    for c in campaigns:
        console.print(f"  {c.name}")

    console.print("\n[bold]Deals by state[/bold]")
    rows = (
        Deal.objects.values("campaign__name", "state")
        .annotate(n=Count("id"))
        .order_by("campaign__name", "state")
    )
    current = None
    for r in rows:
        if r["campaign__name"] != current:
            current = r["campaign__name"]
            console.print(f"  [dim]{current}[/dim]")
        console.print(f"    {_sc(r['state'])}  {r['n']}")

    console.print("\n[bold]Task queue[/bold]")
    for r in Task.objects.values("task_type", "status").annotate(n=Count("id")).order_by("task_type", "status"):
        console.print(f"  [dim]{r['task_type']:<18}[/dim] {r['status']:<12} {r['n']}")
    nxt = Task.objects.filter(status="pending").order_by("scheduled_at").values("task_type", "scheduled_at").first()
    if nxt:
        delta = int((nxt["scheduled_at"] - now).total_seconds() / 60)
        console.print(f"  [dim]next:[/dim] {nxt['task_type']} in {delta}m")

    console.print("\n[bold]Activity today[/bold]")
    rows = (
        ActionLog.objects.filter(created_at__date=now.date())
        .values("action_type", "linkedin_profile__user__username")
        .annotate(n=Count("id"))
    )
    if not rows:
        console.print("  [dim]none[/dim]")
    for r in rows:
        console.print(f"  {r['action_type']:<18} {r['n']}  [dim]({r['linkedin_profile__user__username']})[/dim]")
    console.print()


# ── run / admin ────────────────────────────────────────────────────────────────

@app.command()
def run():
    """Start the automation daemon."""
    from django.core.management import call_command
    call_command("rundaemon")


@app.command()
def admin(port: int = typer.Argument(8001, help="Port for the Django Admin server")):
    """Start the Django Admin web server."""
    from django.core.management import call_command
    console.print(f"\n  Django Admin: [bold]http://localhost:{port}/admin/[/bold]\n")
    call_command("runserver", f"{port}")


# ── linkedin imports ──────────────────────────────────────────────────────────

@linkedin_app.command("import-export")
def linkedin_import_export(
    zip_path: Path = typer.Argument(..., help="Path to a LinkedIn member data export ZIP"),
    campaign: str = typer.Option(..., "--campaign", help="Campaign name (partial match)"),
):
    """Import LinkedIn member export data into a campaign warm lead queue."""
    from linkedin.importers.linkedin_export import import_connections, import_invitations, import_messages
    from linkedin.models import LinkedInProfile

    c = _get_campaign(campaign)
    _validate_linkedin_export_zip(zip_path)
    owner_public_ids = set(
        LinkedInProfile.objects
        .filter(user__campaigns=c, self_lead__public_identifier__isnull=False)
        .values_list("self_lead__public_identifier", flat=True)
    )

    connection_summary = import_connections(str(zip_path), c)
    invitation_summary = import_invitations(str(zip_path), c)
    message_summary = import_messages(str(zip_path), c, owner_public_ids=owner_public_ids)

    _print_linkedin_import_summary(c.name, [connection_summary, invitation_summary, message_summary])


# ── crm: leads ────────────────────────────────────────────────────────────────

@crm_app.command("leads")
def crm_leads(disqualified: bool = typer.Option(False, "--disqualified", help="Show only disqualified")):
    """List all leads."""
    from crm.models.lead import Lead

    qs = Lead.objects.all().order_by("-creation_date")
    if disqualified:
        qs = qs.filter(disqualified=True)

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("ID", style="dim", width=5)
    t.add_column("Identifier")
    t.add_column("Emb", justify="center", width=4)
    t.add_column("DQ", justify="center", width=4)
    t.add_column("Created", width=11)

    for lead in qs:
        t.add_row(
            str(lead.pk),
            lead.public_identifier or lead.linkedin_url,
            "[green]✓[/green]" if lead.embedding else "[dim]·[/dim]",
            "[red]✗[/red]" if lead.disqualified else "[dim]·[/dim]",
            lead.creation_date.strftime("%Y-%m-%d"),
        )
    console.print(t)
    console.print(f"[dim]{qs.count()} leads[/dim]\n")


@crm_app.command("disqualify")
def crm_disqualify(lead_id: int = typer.Argument(..., help="Lead ID")):
    """Permanently disqualify a lead (excluded from all campaigns)."""
    from crm.models.lead import Lead
    try:
        lead = Lead.objects.get(pk=lead_id)
    except Lead.DoesNotExist:
        console.print(f"[red]Lead {lead_id} not found[/red]")
        raise typer.Exit(1)
    lead.disqualified = True
    lead.save(update_fields=["disqualified"])
    console.print(f"[yellow]Lead {lead_id} ({lead.public_identifier}) disqualified[/yellow]")


@crm_app.command("requalify")
def crm_requalify(lead_id: int = typer.Argument(..., help="Lead ID")):
    """Remove disqualification from a lead."""
    from crm.models.lead import Lead
    try:
        lead = Lead.objects.get(pk=lead_id)
    except Lead.DoesNotExist:
        console.print(f"[red]Lead {lead_id} not found[/red]")
        raise typer.Exit(1)
    lead.disqualified = False
    lead.save(update_fields=["disqualified"])
    console.print(f"[green]Lead {lead_id} ({lead.public_identifier}) requalified[/green]")


# ── crm: deals ────────────────────────────────────────────────────────────────

@crm_app.command("deals")
def crm_deals(
    state: Optional[str] = typer.Option(None, "--state", help="Filter by state"),
    campaign: Optional[str] = typer.Option(None, "--campaign", help="Filter by campaign name"),
):
    """List deals."""
    from crm.models.deal import Deal

    qs = Deal.objects.select_related("lead", "campaign").order_by("-creation_date")
    if state:
        qs = qs.filter(state__icontains=state)
    if campaign:
        qs = qs.filter(campaign__name__icontains=campaign)

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("ID", style="dim", width=5)
    t.add_column("Lead", max_width=24, no_wrap=True)
    t.add_column("Campaign", max_width=28, no_wrap=True)
    t.add_column("State", width=18, no_wrap=True)
    t.add_column("Outcome", width=14, no_wrap=True)
    t.add_column("Updated", width=11, no_wrap=True)

    for deal in qs:
        t.add_row(
            str(deal.pk),
            deal.lead.public_identifier if deal.lead else "—",
            deal.campaign.name,
            _sc(deal.state),
            _oc(deal.outcome),
            deal.update_date.strftime("%Y-%m-%d"),
        )
    console.print(t)
    console.print(f"[dim]{qs.count()} deals[/dim]\n")


@crm_app.command("deal")
def crm_deal(deal_id: int = typer.Argument(..., help="Deal ID")):
    """Full detail for a single deal."""
    from crm.models.deal import Deal
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType

    try:
        deal = Deal.objects.select_related("lead", "campaign").get(pk=deal_id)
    except Deal.DoesNotExist:
        console.print(f"[red]Deal {deal_id} not found[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Deal #{deal.pk}[/bold]  {_sc(deal.state)}"
                  + (f"  {_oc(deal.outcome)}" if deal.outcome else ""))
    console.print(f"[dim]lead[/dim]      {deal.lead.public_identifier}")
    console.print(f"[dim]campaign[/dim]  {deal.campaign.name}")
    if deal.reason:
        console.print(f"[dim]reason[/dim]    {deal.reason}")

    if deal.profile_summary:
        facts = deal.profile_summary if isinstance(deal.profile_summary, list) else []
        console.print("\n[bold]Profile summary[/bold]")
        for f in facts:
            console.print(f"  [dim]·[/dim] {f}")

    if deal.chat_summary:
        facts = deal.chat_summary if isinstance(deal.chat_summary, list) else []
        console.print("\n[bold]Chat summary[/bold]")
        for f in facts:
            console.print(f"  [dim]·[/dim] {f}")

    ct = ContentType.objects.get_for_model(deal)
    msgs = ChatMessage.objects.filter(content_type=ct, object_id=deal.pk).order_by("creation_date")
    if msgs.exists():
        console.print("\n[bold]Messages[/bold]")
        for msg in msgs:
            ts = msg.creation_date.strftime("%Y-%m-%d %H:%M")
            arrow = "[green]→[/green]" if msg.is_outgoing else "[cyan]←[/cyan]"
            console.print(f"  [dim]{ts}[/dim] {arrow} {msg.content}")
    else:
        console.print("\n[dim]no messages yet[/dim]")
    console.print()


@crm_app.command("pending")
def crm_pending(campaign: Optional[str] = typer.Option(None, "--campaign", help="Filter by campaign name")):
    """List deals with a follow-up message draft awaiting approval."""
    from crm.models.deal import Deal

    qs = (
        Deal.objects.exclude(pending_message="")
        .select_related("lead", "campaign")
        .order_by("update_date")
    )
    if campaign:
        qs = qs.filter(campaign__name__icontains=campaign)

    if not qs.exists():
        console.print("[dim]No pending drafts[/dim]\n")
        return

    for deal in qs:
        approved = "[green]approved[/green]" if deal.pending_message_approved else "[yellow]awaiting approval[/yellow]"
        console.print(f"\n[bold]Deal #{deal.pk}[/bold]  {_sc(deal.state)}  {approved}")
        console.print(f"[dim]lead[/dim]      {deal.lead.public_identifier}")
        console.print(f"[dim]campaign[/dim]  {deal.campaign.name}")
        facts = (deal.profile_summary or {}).get("facts") or []
        if facts:
            console.print("[dim]profile[/dim]   " + " · ".join(facts[:3]))
        console.print(f"[bold]draft[/bold]     {deal.pending_message}")
    console.print()


@crm_app.command("approve")
def crm_approve(deal_id: int = typer.Argument(..., help="Deal ID")):
    """Approve a pending follow-up draft — will be sent on the next daemon cycle."""
    from crm.models.deal import Deal

    try:
        deal = Deal.objects.select_related("lead").get(pk=deal_id)
    except Deal.DoesNotExist:
        console.print(f"[red]Deal {deal_id} not found[/red]")
        raise typer.Exit(1)

    if not deal.pending_message:
        console.print(f"[yellow]Deal {deal_id} has no pending draft[/yellow]")
        raise typer.Exit(1)

    deal.pending_message_approved = True
    deal.save(update_fields=["pending_message_approved"])

    from django.utils import timezone
    from linkedin.models import Task
    Task.objects.create(
        task_type=Task.TaskType.FOLLOW_UP,
        scheduled_at=timezone.now(),
        payload={"campaign_id": deal.campaign_id},
    )
    console.print(f"[green]Deal {deal_id} ({deal.lead.public_identifier}): draft approved — immediate send task queued[/green]")
    console.print(f"[dim]{deal.pending_message}[/dim]")


@crm_app.command("reject")
def crm_reject(
    deal_id: int = typer.Argument(..., help="Deal ID"),
    feedback: Optional[str] = typer.Option(None, "--feedback", "-f", help="Feedback for regeneration. When provided, dispatches an immediate regeneration instead of a hard reject."),
):
    """Discard or regenerate a pending follow-up draft.

    Without --feedback: hard reject — draft cleared, daemon generates a fresh one next cycle.
    With --feedback: reject with instructions — triggers immediate regeneration incorporating the feedback.
    """
    from crm.models.deal import Deal

    try:
        deal = Deal.objects.select_related("lead", "campaign").get(pk=deal_id)
    except Deal.DoesNotExist:
        console.print(f"[red]Deal {deal_id} not found[/red]")
        raise typer.Exit(1)

    if not deal.pending_message:
        console.print(f"[yellow]Deal {deal_id} has no pending draft[/yellow]")
        raise typer.Exit(1)

    if feedback:
        from django.utils import timezone
        from linkedin.models import Task
        from linkedin.enums import ProfileState

        deal.rejection_feedback = feedback
        deal.regeneration_count = (deal.regeneration_count or 0) + 1
        deal.pending_message = ""
        deal.pending_message_approved = False
        deal.pending_message_created_at = None
        deal.save(update_fields=["rejection_feedback", "regeneration_count", "pending_message", "pending_message_approved", "pending_message_created_at"])
        Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            scheduled_at=timezone.now(),
            payload={
                "campaign_id": deal.campaign_id,
                "deal_id": deal.pk,
                "regeneration_feedback": feedback,
            },
        )
        console.print(f"[cyan]Deal {deal_id} ({deal.lead.public_identifier}): regeneration dispatched with feedback[/cyan]")
    else:
        deal.pending_message = ""
        deal.pending_message_approved = False
        deal.pending_message_created_at = None
        deal.save(update_fields=["pending_message", "pending_message_approved", "pending_message_created_at"])
        console.print(f"[yellow]Deal {deal_id} ({deal.lead.public_identifier}): draft discarded[/yellow]")


@crm_app.command("set-state")
def crm_set_state(
    deal_id: int = typer.Argument(..., help="Deal ID"),
    state: str = typer.Argument(..., help=f"New state: {', '.join(VALID_STATES)}"),
):
    """Update the state of a deal."""
    from crm.models.deal import Deal

    matched = next((s for s in VALID_STATES if s.lower() == state.lower()), None)
    if not matched:
        console.print(f"[red]Invalid state '{state}'. Valid: {', '.join(VALID_STATES)}[/red]")
        raise typer.Exit(1)

    try:
        deal = Deal.objects.select_related("lead").get(pk=deal_id)
    except Deal.DoesNotExist:
        console.print(f"[red]Deal {deal_id} not found[/red]")
        raise typer.Exit(1)

    old = deal.state
    deal.state = matched
    deal.save(update_fields=["state"])
    console.print(f"Deal {deal_id} ({deal.lead.public_identifier}): {_sc(old)} → {_sc(matched)}")


@crm_app.command("set-outcome")
def crm_set_outcome(
    deal_id: int = typer.Argument(..., help="Deal ID"),
    outcome: str = typer.Argument(..., help=f"New outcome: {', '.join(VALID_OUTCOMES)}"),
):
    """Update the outcome of a deal."""
    from crm.models.deal import Deal

    matched = next((o for o in VALID_OUTCOMES if o.lower() == outcome.lower()), None)
    if not matched:
        console.print(f"[red]Invalid outcome '{outcome}'. Valid: {', '.join(VALID_OUTCOMES)}[/red]")
        raise typer.Exit(1)

    try:
        deal = Deal.objects.select_related("lead").get(pk=deal_id)
    except Deal.DoesNotExist:
        console.print(f"[red]Deal {deal_id} not found[/red]")
        raise typer.Exit(1)

    old = deal.outcome
    deal.outcome = matched
    deal.save(update_fields=["outcome"])
    console.print(f"Deal {deal_id} ({deal.lead.public_identifier}): outcome {_oc(old)} → {_oc(matched)}")


# ── campaign ──────────────────────────────────────────────────────────────────

@campaign_app.command("list")
def campaign_list():
    """List all campaigns."""
    from linkedin.models import Campaign
    from crm.models.deal import Deal

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("Name")
    t.add_column("Deals", justify="right", width=6)
    t.add_column("Booking link")
    t.add_column("Website")

    for c in Campaign.objects.all():
        t.add_row(
            c.name,
            str(Deal.objects.filter(campaign=c).count()),
            c.booking_link or "[dim]—[/dim]",
            c.website_url or "[dim]—[/dim]",
        )
    console.print(t)


@campaign_app.command("show")
def campaign_show(name: str = typer.Argument(..., help="Campaign name (partial match)")):
    """Show campaign details and deal breakdown."""
    from crm.models.deal import Deal
    from django.db.models import Count

    c = _get_campaign(name)
    console.print(f"\n[bold]{c.name}[/bold]")
    console.print(f"[dim]objective[/dim]   {c.campaign_objective or '—'}")
    console.print(f"[dim]booking[/dim]     {c.booking_link or '—'}")
    console.print(f"[dim]website[/dim]     {c.website_url or '—'}")
    approval = "[green]on[/green]" if c.require_message_approval else "[dim]off[/dim]"
    console.print(f"[dim]approval[/dim]    {approval}")

    console.print("\n[bold]Deals[/bold]")
    for r in Deal.objects.filter(campaign=c).values("state").annotate(n=Count("id")).order_by("state"):
        console.print(f"  {_sc(r['state'])}  {r['n']}")

    console.print("\n[bold]Product docs[/bold]")
    console.print(f"  {c.product_docs or '[dim]—[/dim]'}")
    console.print()


@campaign_app.command("create")
def campaign_create(
    name: str = typer.Option(..., prompt="Campaign name"),
    objective: str = typer.Option(..., prompt="Campaign objective"),
    booking: str = typer.Option(..., prompt="Booking link"),
    docs: str = typer.Option(..., prompt="Product docs"),
    website: str = typer.Option("", "--website", help="Company website URL"),
):
    """Create a new campaign."""
    from linkedin.models import Campaign
    from django.contrib.auth.models import User

    if Campaign.objects.filter(name=name).exists():
        console.print(f"[red]Campaign '{name}' already exists[/red]")
        raise typer.Exit(1)

    c = Campaign.objects.create(
        name=name,
        campaign_objective=objective,
        booking_link=booking,
        product_docs=docs,
        website_url=website,
    )
    # Add all existing users to the campaign
    for user in User.objects.all():
        c.users.add(user)

    console.print(f"[green]Campaign '{c.name}' created (id={c.pk})[/green]")


@campaign_app.command("update")
def campaign_update(
    name: str = typer.Argument(..., help="Campaign name (partial match)"),
    objective: Optional[str] = typer.Option(None, "--objective"),
    booking: Optional[str] = typer.Option(None, "--booking"),
    docs: Optional[str] = typer.Option(None, "--docs"),
    website: Optional[str] = typer.Option(None, "--website"),
    new_name: Optional[str] = typer.Option(None, "--name"),
    require_approval: Optional[bool] = typer.Option(None, "--require-approval/--no-require-approval"),
):
    """Update campaign fields."""
    c = _get_campaign(name)
    changed = []

    if objective is not None:
        c.campaign_objective = objective
        changed.append("campaign_objective")
    if booking is not None:
        c.booking_link = booking
        changed.append("booking_link")
    if docs is not None:
        c.product_docs = docs
        changed.append("product_docs")
    if website is not None:
        c.website_url = website
        changed.append("website_url")
    if new_name is not None:
        c.name = new_name
        changed.append("name")
    if require_approval is not None:
        c.require_message_approval = require_approval
        changed.append("require_message_approval")

    if not changed:
        console.print("[yellow]Nothing to update — pass at least one option[/yellow]")
        raise typer.Exit(0)

    c.save(update_fields=changed)
    console.print(f"[green]Updated: {', '.join(changed)}[/green]")


@campaign_app.command("delete")
def campaign_delete(
    name: str = typer.Argument(..., help="Campaign name (partial match)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a campaign and all its deals."""
    c = _get_campaign(name)
    if not yes:
        typer.confirm(f"Delete campaign '{c.name}' and all its deals?", abort=True)
    c.delete()
    console.print(f"[red]Campaign '{c.name}' deleted[/red]")


# ── task ──────────────────────────────────────────────────────────────────────

@task_app.command("list")
def task_list(
    status: Optional[str] = typer.Option(None, "--status", help="pending/running/completed/failed"),
    limit: int = typer.Option(20, "--limit"),
):
    """List tasks in the queue."""
    from linkedin.models import Task, Campaign

    qs = Task.objects.order_by("scheduled_at")
    if status:
        qs = qs.filter(status__icontains=status)
    qs = qs[:limit]

    campaign_map = {c.pk: c.name for c in Campaign.objects.all()}
    STATUS_COLOR = {"pending": "yellow", "running": "green", "completed": "dim", "failed": "red"}

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("ID", style="dim", width=6)
    t.add_column("Type", width=14)
    t.add_column("Status", width=10)
    t.add_column("Scheduled", width=17)
    t.add_column("Campaign", max_width=30, no_wrap=True)

    for task in qs:
        sc = STATUS_COLOR.get(task.status, "white")
        cname = campaign_map.get(task.payload.get("campaign_id"), "—")
        t.add_row(
            str(task.pk),
            task.task_type,
            f"[{sc}]{task.status}[/{sc}]",
            task.scheduled_at.strftime("%Y-%m-%d %H:%M") if task.scheduled_at else "—",
            cname,
        )
    console.print(t)


@task_app.command("cancel")
def task_cancel(task_id: int = typer.Argument(..., help="Task ID to cancel")):
    """Cancel a pending task."""
    from linkedin.models import Task

    try:
        task = Task.objects.get(pk=task_id, status="pending")
    except Task.DoesNotExist:
        console.print(f"[red]Task {task_id} not found or not pending[/red]")
        raise typer.Exit(1)

    task.status = "failed"
    task.save(update_fields=["status"])
    console.print(f"[yellow]Task {task_id} cancelled[/yellow]")


# ── keyword ───────────────────────────────────────────────────────────────────

@keyword_app.command("list")
def keyword_list(campaign: Optional[str] = typer.Option(None, "--campaign")):
    """List search keywords."""
    from linkedin.models import SearchKeyword

    qs = SearchKeyword.objects.select_related("campaign").order_by("campaign__name", "keyword")
    if campaign:
        qs = qs.filter(campaign__name__icontains=campaign)

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("ID", style="dim", width=5)
    t.add_column("Keyword")
    t.add_column("Campaign", max_width=30, no_wrap=True)
    t.add_column("Used", justify="center", width=5)
    t.add_column("Used at", width=11)

    for kw in qs:
        t.add_row(
            str(kw.pk),
            kw.keyword,
            kw.campaign.name,
            "[dim]✓[/dim]" if kw.used else "·",
            kw.used_at.strftime("%Y-%m-%d") if kw.used_at else "—",
        )
    console.print(t)
    console.print(f"[dim]{qs.count()} keywords[/dim]\n")


@keyword_app.command("add")
def keyword_add(
    campaign: str = typer.Argument(..., help="Campaign name (partial match)"),
    keyword: str = typer.Argument(..., help="Search keyword"),
):
    """Add a search keyword to a campaign."""
    from linkedin.models import SearchKeyword

    c = _get_campaign(campaign)
    _, created = SearchKeyword.objects.get_or_create(campaign=c, keyword=keyword)
    if created:
        console.print(f"[green]Added keyword '{keyword}' to '{c.name}'[/green]")
    else:
        console.print(f"[yellow]Keyword '{keyword}' already exists in '{c.name}'[/yellow]")


@keyword_app.command("delete")
def keyword_delete(
    keyword_id: int = typer.Argument(..., help="Keyword ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a search keyword."""
    from linkedin.models import SearchKeyword

    try:
        kw = SearchKeyword.objects.select_related("campaign").get(pk=keyword_id)
    except SearchKeyword.DoesNotExist:
        console.print(f"[red]Keyword {keyword_id} not found[/red]")
        raise typer.Exit(1)

    if not yes:
        typer.confirm(f"Delete keyword '{kw.keyword}' from '{kw.campaign.name}'?", abort=True)
    kw.delete()
    console.print(f"[red]Keyword '{kw.keyword}' deleted[/red]")


# ── prompt ────────────────────────────────────────────────────────────────────

def _load_prompt_body(body: Optional[str], file: Optional[Path], current: str = "") -> str:
    """Return prompt body from --body, --file, or $EDITOR (pre-filled with current)."""
    if body is not None:
        return body
    if file is not None:
        return Path(file).read_text(encoding="utf-8")
    import subprocess
    import tempfile
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    with tempfile.NamedTemporaryFile(suffix=".j2", mode="w", delete=False, encoding="utf-8") as f:
        f.write(current)
        tmp = Path(f.name)
    subprocess.call([editor, str(tmp)])
    text = tmp.read_text(encoding="utf-8")
    tmp.unlink(missing_ok=True)
    if not text.strip():
        console.print("[yellow]Aborted — empty prompt[/yellow]")
        raise typer.Exit(0)
    return text


def _validate_jinja2(body: str) -> None:
    import jinja2
    try:
        jinja2.Environment().parse(body)
    except jinja2.exceptions.TemplateSyntaxError as e:
        console.print(f"[red]Jinja2 syntax error: {e}[/red]")
        raise typer.Exit(1)


@prompt_app.command("list")
def prompt_list():
    """List all global prompt templates."""
    from linkedin.models import PromptTemplate

    rows = PromptTemplate.objects.order_by("key")
    if not rows.exists():
        console.print("[dim]No prompt templates found — run migrations[/dim]")
        return

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("Key", style="cyan", no_wrap=True)
    t.add_column("Name")
    t.add_column("Updated", width=11)
    t.add_column("Chars", justify="right", width=7)

    for pt in rows:
        t.add_row(pt.key, pt.name, pt.updated_at.strftime("%Y-%m-%d"), str(len(pt.body)))
    console.print(t)


@prompt_app.command("show")
def prompt_show(key: str = typer.Argument(..., help="Prompt key")):
    """Show the full body of a global prompt template."""
    from linkedin.models import PromptTemplate

    try:
        pt = PromptTemplate.objects.get(key=key)
    except PromptTemplate.DoesNotExist:
        console.print(f"[red]Prompt '{key}' not found[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]{pt.key}[/bold]  [dim]{pt.name}[/dim]")
    if pt.description:
        console.print(f"[dim]{pt.description}[/dim]")
    console.print(f"[dim]updated {pt.updated_at.strftime('%Y-%m-%d %H:%M')}  {len(pt.body)} chars[/dim]\n")
    console.print(pt.body)
    console.print()


@prompt_app.command("set")
def prompt_set(
    key: str = typer.Argument(..., help="Prompt key"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Prompt text inline"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Read prompt from file"),
):
    """Edit a global prompt template. Opens $EDITOR if --body and --file are omitted."""
    from linkedin.models import PromptTemplate

    try:
        pt = PromptTemplate.objects.get(key=key)
    except PromptTemplate.DoesNotExist:
        console.print(f"[red]Prompt '{key}' not found[/red]")
        raise typer.Exit(1)

    new_body = _load_prompt_body(body, file, current=pt.body)
    _validate_jinja2(new_body)
    pt.body = new_body
    pt.save(update_fields=["body", "updated_at"])
    console.print(f"[green]Prompt '{key}' updated ({len(new_body)} chars)[/green]")


@prompt_app.command("reset")
def prompt_reset(
    key: str = typer.Argument(..., help="Prompt key"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Reset a global prompt template to its hardcoded default."""
    from linkedin.models import PromptTemplate
    from linkedin.prompts import _load_fallback

    fallback = _load_fallback(key)
    if not fallback:
        console.print(f"[red]No hardcoded default for '{key}'[/red]")
        raise typer.Exit(1)

    if not yes:
        typer.confirm(f"Reset '{key}' to hardcoded default? This overwrites any edits.", abort=True)

    try:
        pt = PromptTemplate.objects.get(key=key)
    except PromptTemplate.DoesNotExist:
        console.print(f"[red]Prompt '{key}' not found[/red]")
        raise typer.Exit(1)

    pt.body = fallback
    pt.save(update_fields=["body", "updated_at"])
    console.print(f"[yellow]Prompt '{key}' reset to hardcoded default[/yellow]")


@prompt_app.command("override-list")
def prompt_override_list(campaign: str = typer.Argument(..., help="Campaign name (partial match)")):
    """List all prompt overrides for a campaign."""
    from linkedin.models import CampaignPromptOverride

    c = _get_campaign(campaign)
    overrides = CampaignPromptOverride.objects.filter(campaign=c).order_by("prompt_key")

    if not overrides.exists():
        console.print(f"[dim]No prompt overrides for '{c.name}' — all prompts use global defaults[/dim]")
        return

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("Key", style="cyan", no_wrap=True)
    t.add_column("Chars", justify="right", width=7)

    for ov in overrides:
        t.add_row(ov.prompt_key, str(len(ov.body)))
    console.print(t)


@prompt_app.command("override-show")
def prompt_override_show(
    campaign: str = typer.Argument(..., help="Campaign name (partial match)"),
    key: str = typer.Argument(..., help="Prompt key"),
):
    """Show a campaign prompt override."""
    from linkedin.models import CampaignPromptOverride

    c = _get_campaign(campaign)
    try:
        ov = CampaignPromptOverride.objects.get(campaign=c, prompt_key=key)
    except CampaignPromptOverride.DoesNotExist:
        console.print(f"[dim]No override for '{key}' in '{c.name}' — using global default[/dim]")
        raise typer.Exit(0)

    console.print(f"\n[bold]{c.name}[/bold] / [cyan]{key}[/cyan]\n")
    console.print(ov.body)
    console.print()


@prompt_app.command("override-set")
def prompt_override_set(
    campaign: str = typer.Argument(..., help="Campaign name (partial match)"),
    key: str = typer.Argument(..., help="Prompt key"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Prompt text inline"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Read prompt from file"),
):
    """Set a prompt override for a campaign. Opens $EDITOR if --body and --file are omitted."""
    from linkedin.models import CampaignPromptOverride, PROMPT_KEYS

    if key not in PROMPT_KEYS:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(PROMPT_KEYS)}[/red]")
        raise typer.Exit(1)

    c = _get_campaign(campaign)
    current = ""
    try:
        current = CampaignPromptOverride.objects.get(campaign=c, prompt_key=key).body
    except CampaignPromptOverride.DoesNotExist:
        pass

    new_body = _load_prompt_body(body, file, current=current)
    _validate_jinja2(new_body)
    _, created = CampaignPromptOverride.objects.update_or_create(
        campaign=c, prompt_key=key, defaults={"body": new_body}
    )
    action = "created" if created else "updated"
    console.print(f"[green]Override for '{key}' in '{c.name}' {action} ({len(new_body)} chars)[/green]")


@prompt_app.command("override-reset")
def prompt_override_reset(
    campaign: str = typer.Argument(..., help="Campaign name (partial match)"),
    key: str = typer.Argument(..., help="Prompt key"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a campaign prompt override (reverts to global default)."""
    from linkedin.models import CampaignPromptOverride

    c = _get_campaign(campaign)
    if not yes:
        typer.confirm(f"Remove override for '{key}' in '{c.name}'? It will revert to the global default.", abort=True)

    deleted, _ = CampaignPromptOverride.objects.filter(campaign=c, prompt_key=key).delete()
    if deleted:
        console.print(f"[yellow]Override for '{key}' in '{c.name}' removed — now using global default[/yellow]")
    else:
        console.print(f"[dim]No override found for '{key}' in '{c.name}'[/dim]")


# ── config ────────────────────────────────────────────────────────────────────

_CONFIG_FIELDS: dict[str, tuple[str, str]] = {
    "follow_up_cooldown_hours":    ("int",   "Min hours between follow-up nudges"),
    "reengagement_greeting_days":  ("int",   "Days of silence before re-greeting"),
    "gpr_qualification_threshold": ("float", "Min GPR score to qualify a lead (0.0–1.0)"),
    "connect_daily_limit":         ("int",   "Max connection requests per day"),
    "follow_up_daily_limit":       ("int",   "Max follow-up messages per day"),
    "check_pending_daily_cap":     ("int",   "Max check_pending tasks per day"),
    "max_followups_without_reply": ("int",   "Follow-ups without reply before auto-FAILED"),
    "min_qualification_observations_before_connect": ("int", "Min labels before cold connect candidates"),
    "preconnect_qualification_batch_size": ("int", "Pending leads to qualify before cold connects"),
}


def _parse_config_value(field: str, raw: str):
    type_, _ = _CONFIG_FIELDS[field]
    if type_ == "int":
        try:
            val = int(raw)
        except ValueError:
            console.print(f"[red]'{field}' expects an integer[/red]")
            raise typer.Exit(1)
        if val < 0:
            console.print(f"[red]'{field}' must be non-negative[/red]")
            raise typer.Exit(1)
        return val
    else:
        try:
            val = float(raw)
        except ValueError:
            console.print(f"[red]'{field}' expects a float[/red]")
            raise typer.Exit(1)
        if field == "gpr_qualification_threshold" and not 0.0 <= val <= 1.0:
            console.print(f"[red]'{field}' must be between 0.0 and 1.0[/red]")
            raise typer.Exit(1)
        return val


@config_app.command("show")
def config_show():
    """Show global pipeline configuration (SiteConfig)."""
    from linkedin.models import SiteConfig

    cfg = SiteConfig.load()

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("Field", style="cyan", no_wrap=True)
    t.add_column("Value", justify="right", width=10)
    t.add_column("Description", style="dim")

    for field, (_, desc) in _CONFIG_FIELDS.items():
        t.add_row(field, str(getattr(cfg, field)), desc)
    console.print(t)


@config_app.command("set")
def config_set(
    field: str = typer.Argument(..., help=f"Config field to update"),
    value: str = typer.Argument(..., help="New value"),
):
    """Set a global pipeline config value."""
    from linkedin.models import SiteConfig

    if field not in _CONFIG_FIELDS:
        console.print(f"[red]Unknown field '{field}'. Valid fields:[/red]")
        for f, (_, desc) in _CONFIG_FIELDS.items():
            console.print(f"  [cyan]{f}[/cyan]  [dim]{desc}[/dim]")
        raise typer.Exit(1)

    val = _parse_config_value(field, value)
    cfg = SiteConfig.load()
    setattr(cfg, field, val)
    cfg.save(update_fields=[field])
    console.print(f"[green]SiteConfig.{field} = {val}[/green]")


@config_app.command("campaign-show")
def config_campaign_show(campaign: str = typer.Argument(..., help="Campaign name (partial match)")):
    """Show pipeline config for a campaign: overrides, global defaults, and effective values."""
    from linkedin.models import SiteConfig
    from linkedin.pipeline_config import get_campaign_config

    c = _get_campaign(campaign)
    cfg = SiteConfig.load()
    effective = get_campaign_config(c)

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("Field", style="cyan", no_wrap=True)
    t.add_column("Override", justify="right", width=10)
    t.add_column("Global", justify="right", width=10, style="dim")
    t.add_column("Effective", justify="right", width=10)

    for field, (_, _desc) in _CONFIG_FIELDS.items():
        override_val = getattr(c, field, None)
        global_val = getattr(cfg, field)
        effective_val = getattr(effective, field)
        override_str = str(override_val) if override_val is not None else "[dim]—[/dim]"
        effective_str = f"[bold]{effective_val}[/bold]" if override_val is not None else str(effective_val)
        t.add_row(field, override_str, str(global_val), effective_str)

    console.print(f"\n[bold]{c.name}[/bold] pipeline config\n")
    console.print(t)
    console.print()


@config_app.command("campaign-set")
def config_campaign_set(
    campaign: str = typer.Argument(..., help="Campaign name (partial match)"),
    field: str = typer.Argument(..., help="Config field to override"),
    value: str = typer.Argument(..., help="New value"),
):
    """Set a pipeline config override for a specific campaign."""
    if field not in _CONFIG_FIELDS:
        console.print(f"[red]Unknown field '{field}'. Valid fields:[/red]")
        for f, (_, desc) in _CONFIG_FIELDS.items():
            console.print(f"  [cyan]{f}[/cyan]  [dim]{desc}[/dim]")
        raise typer.Exit(1)

    c = _get_campaign(campaign)
    val = _parse_config_value(field, value)
    setattr(c, field, val)
    c.save(update_fields=[field])
    console.print(f"[green]Campaign '{c.name}': {field} = {val}[/green]")


@config_app.command("campaign-reset")
def config_campaign_reset(
    campaign: str = typer.Argument(..., help="Campaign name (partial match)"),
    field: str = typer.Argument(..., help="Config field to reset"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Clear a campaign config override (reverts to global SiteConfig value)."""
    if field not in _CONFIG_FIELDS:
        console.print(f"[red]Unknown field '{field}'. Valid fields:[/red]")
        for f, (_, desc) in _CONFIG_FIELDS.items():
            console.print(f"  [cyan]{f}[/cyan]  [dim]{desc}[/dim]")
        raise typer.Exit(1)

    c = _get_campaign(campaign)
    if not yes:
        typer.confirm(f"Reset '{field}' for '{c.name}' to global default?", abort=True)

    setattr(c, field, None)
    c.save(update_fields=[field])
    console.print(f"[yellow]Campaign '{c.name}': {field} reset to global default[/yellow]")


if __name__ == "__main__":
    app()
