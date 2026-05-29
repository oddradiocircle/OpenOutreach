"""oo — OpenOutreach local CLI."""
import os
import sys
from pathlib import Path

import typer
from typing import Optional

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
    help="OpenOutreach local CLI — manage campaigns, leads, deals, and tasks.",
    no_args_is_help=True,
    add_completion=False,
)
crm_app = typer.Typer(help="Browse CRM data.", no_args_is_help=True)
campaign_app = typer.Typer(help="Manage campaigns.", no_args_is_help=True)
task_app = typer.Typer(help="Inspect the task queue.", no_args_is_help=True)

app.add_typer(crm_app, name="crm")
app.add_typer(campaign_app, name="campaign")
app.add_typer(task_app, name="task")

# ── colour maps ────────────────────────────────────────────────────────────────

STATE_COLOR = {
    "qualified": "cyan",
    "ready_to_connect": "blue",
    "pending": "yellow",
    "connected": "green",
    "completed": "bright_green",
    "failed": "red",
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


def _sc(state: str) -> str:
    c = STATE_COLOR.get(state, "white")
    return f"[{c}]{state}[/{c}]"


def _oc(outcome: str) -> str:
    c = OUTCOME_COLOR.get(outcome, "dim")
    return f"[{c}]{outcome or '—'}[/{c}]"


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
        tag = " [dim][freemium][/dim]" if c.is_freemium else ""
        console.print(f"  {c.name}{tag}")

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
    t.add_column("State", width=16, no_wrap=True)
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


# ── crm: deal detail ──────────────────────────────────────────────────────────

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


# ── campaign ──────────────────────────────────────────────────────────────────

@campaign_app.command("list")
def campaign_list():
    """List all campaigns."""
    from linkedin.models import Campaign
    from crm.models.deal import Deal
    from django.db.models import Count

    campaigns = Campaign.objects.all()
    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("Name")
    t.add_column("Freemium", justify="center", width=9)
    t.add_column("Deals", justify="right", width=6)
    t.add_column("Booking link")

    for c in campaigns:
        deal_count = Deal.objects.filter(campaign=c).count()
        t.add_row(
            c.name,
            "[dim]✓[/dim]" if c.is_freemium else "·",
            str(deal_count),
            c.booking_link or "[dim]—[/dim]",
        )
    console.print(t)


@campaign_app.command("show")
def campaign_show(name: str = typer.Argument(..., help="Campaign name (partial match)")):
    """Show campaign details and deal breakdown."""
    from linkedin.models import Campaign
    from crm.models.deal import Deal
    from django.db.models import Count

    try:
        c = Campaign.objects.get(name__icontains=name)
    except Campaign.DoesNotExist:
        console.print(f"[red]No campaign matching '{name}'[/red]")
        raise typer.Exit(1)
    except Campaign.MultipleObjectsReturned:
        console.print(f"[yellow]Multiple campaigns match '{name}' — be more specific[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]{c.name}[/bold]")
    console.print(f"[dim]objective[/dim]   {c.campaign_objective or '—'}")
    console.print(f"[dim]booking[/dim]     {c.booking_link or '—'}")
    console.print(f"[dim]freemium[/dim]    {'yes' if c.is_freemium else 'no'}")

    console.print("\n[bold]Deals[/bold]")
    for r in Deal.objects.filter(campaign=c).values("state").annotate(n=Count("id")).order_by("state"):
        console.print(f"  {_sc(r['state'])}  {r['n']}")

    console.print(f"\n[bold]Product docs[/bold]")
    console.print(f"  {c.product_docs or '[dim]—[/dim]'}")
    console.print()


# ── task ──────────────────────────────────────────────────────────────────────

@task_app.command("list")
def task_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status (pending/running/failed)"),
    limit: int = typer.Option(20, "--limit", help="Max rows to show"),
):
    """List tasks in the queue."""
    from linkedin.models import Task

    qs = Task.objects.order_by("scheduled_at")
    if status:
        qs = qs.filter(status__icontains=status)
    qs = qs[:limit]

    t = Table(box=rbox.SIMPLE, header_style="bold", pad_edge=False)
    t.add_column("ID", style="dim", width=6)
    t.add_column("Type", width=14)
    t.add_column("Status", width=10)
    t.add_column("Scheduled", width=17)
    t.add_column("Campaign", max_width=30, no_wrap=True)

    STATUS_COLOR = {"pending": "yellow", "running": "green", "completed": "dim", "failed": "red"}
    from linkedin.models import Campaign
    campaign_map = {c.pk: c.name for c in Campaign.objects.all()}
    for task in qs:
        sc = STATUS_COLOR.get(task.status, "white")
        campaign_id = task.payload.get("campaign_id")
        campaign_name = campaign_map.get(campaign_id, "—") if campaign_id else "—"
        t.add_row(
            str(task.pk),
            task.task_type,
            f"[{sc}]{task.status}[/{sc}]",
            task.scheduled_at.strftime("%Y-%m-%d %H:%M") if task.scheduled_at else "—",
            campaign_name,
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
    console.print(f"[green]Task {task_id} cancelled[/green]")


if __name__ == "__main__":
    app()
