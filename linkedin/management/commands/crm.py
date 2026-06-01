from django.core.management.base import BaseCommand, CommandError
from linkedin.tz import localfmt

STATE_COLORS = {
    "qualified": "cyan",
    "ready_to_connect": "blue",
    "pending": "yellow",
    "connected": "green",
    "completed": "bright_green",
    "failed": "red",
}

OUTCOME_COLORS = {
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


class Command(BaseCommand):
    help = "Browse CRM data — leads, deals, and deal details."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand")

        leads_p = sub.add_parser("leads", help="List all leads")
        leads_p.add_argument("--disqualified", action="store_true")

        deals_p = sub.add_parser("deals", help="List deals")
        deals_p.add_argument("--state", help="Filter by state")
        deals_p.add_argument("--campaign", help="Filter by campaign name (partial)")

        deal_p = sub.add_parser("deal", help="Full detail for a deal")
        deal_p.add_argument("id", type=int)

    def handle(self, *args, **options):
        from rich.console import Console
        self.console = Console(highlight=False)

        sub = options["subcommand"]
        if sub == "leads":
            self._leads(options)
        elif sub == "deals":
            self._deals(options)
        elif sub == "deal":
            self._deal(options["id"])
        else:
            self.console.print("usage: manage.py crm [leads|deals|deal <id>]")

    # ------------------------------------------------------------------

    def _leads(self, options):
        from rich.table import Table, box as rbox
        from crm.models.lead import Lead

        qs = Lead.objects.all().order_by("-creation_date")
        if options["disqualified"]:
            qs = qs.filter(disqualified=True)

        table = Table(box=rbox.SIMPLE, show_header=True, header_style="bold", pad_edge=False)
        table.add_column("ID", style="dim", width=5)
        table.add_column("Identifier")
        table.add_column("Emb", justify="center", width=4)
        table.add_column("DQ", justify="center", width=4)
        table.add_column("Created", width=11)

        for lead in qs:
            table.add_row(
                str(lead.pk),
                lead.public_identifier or lead.linkedin_url,
                "[green]✓[/green]" if lead.embedding else "[dim]·[/dim]",
                "[red]✗[/red]" if lead.disqualified else "[dim]·[/dim]",
                localfmt(lead.creation_date, "%Y-%m-%d"),
            )

        self.console.print(table)
        self.console.print(f"[dim]{qs.count()} leads[/dim]")

    def _deals(self, options):
        from rich.table import Table, box as rbox
        from crm.models.deal import Deal

        qs = Deal.objects.select_related("lead", "campaign").order_by("-creation_date")
        if options.get("state"):
            qs = qs.filter(state__icontains=options["state"])
        if options.get("campaign"):
            qs = qs.filter(campaign__name__icontains=options["campaign"])

        table = Table(box=rbox.SIMPLE, show_header=True, header_style="bold", pad_edge=False)
        table.add_column("ID", style="dim", width=5)
        table.add_column("Lead", max_width=24, no_wrap=True)
        table.add_column("Campaign", max_width=28, no_wrap=True)
        table.add_column("State", width=16, no_wrap=True)
        table.add_column("Outcome", width=14, no_wrap=True)
        table.add_column("Updated", width=11, no_wrap=True)

        for deal in qs:
            sc = STATE_COLORS.get(deal.state, "white")
            oc = OUTCOME_COLORS.get(deal.outcome, "dim")
            table.add_row(
                str(deal.pk),
                deal.lead.public_identifier if deal.lead else "—",
                deal.campaign.name,
                f"[{sc}]{deal.state}[/{sc}]",
                f"[{oc}]{deal.outcome or '—'}[/{oc}]",
                localfmt(deal.update_date, "%Y-%m-%d"),
            )

        self.console.print(table)
        self.console.print(f"[dim]{qs.count()} deals[/dim]")

    def _deal(self, deal_id):
        from rich.text import Text
        from crm.models.deal import Deal
        from chat.models import ChatMessage
        from django.contrib.contenttypes.models import ContentType

        try:
            deal = Deal.objects.select_related("lead", "campaign").get(pk=deal_id)
        except Deal.DoesNotExist:
            raise CommandError(f"Deal {deal_id} not found")

        sc = STATE_COLORS.get(deal.state, "white")
        oc = OUTCOME_COLORS.get(deal.outcome, "dim")

        self.console.print(f"\n[bold]Deal #{deal.pk}[/bold]  [{sc}]{deal.state}[/{sc}]"
                           + (f"  [{oc}]{deal.outcome}[/{oc}]" if deal.outcome else ""))
        self.console.print(f"[dim]lead[/dim]      {deal.lead.public_identifier}")
        self.console.print(f"[dim]campaign[/dim]  {deal.campaign.name}")
        if deal.reason:
            self.console.print(f"[dim]reason[/dim]    {deal.reason}")

        if deal.profile_summary:
            facts = deal.profile_summary if isinstance(deal.profile_summary, list) else []
            self.console.print("\n[bold]Profile summary[/bold]")
            for f in facts:
                self.console.print(f"  [dim]·[/dim] {f}")

        if deal.chat_summary:
            facts = deal.chat_summary if isinstance(deal.chat_summary, list) else []
            self.console.print("\n[bold]Chat summary[/bold]")
            for f in facts:
                self.console.print(f"  [dim]·[/dim] {f}")

        ct = ContentType.objects.get_for_model(deal)
        messages = ChatMessage.objects.filter(content_type=ct, object_id=deal.pk).order_by("creation_date")

        if messages.exists():
            self.console.print("\n[bold]Messages[/bold]")
            for msg in messages:
                ts = localfmt(msg.creation_date)
                direction = "[green]→[/green]" if msg.is_outgoing else "[cyan]←[/cyan]"
                self.console.print(f"  [dim]{ts}[/dim] {direction} {msg.content}")
        else:
            self.console.print("\n[dim]no messages yet[/dim]")

        self.console.print()
