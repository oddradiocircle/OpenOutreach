from django.core.management.base import BaseCommand, CommandError

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

        # leads
        leads_p = sub.add_parser("leads", help="List all leads")
        leads_p.add_argument("--disqualified", action="store_true", help="Show only disqualified leads")

        # deals
        deals_p = sub.add_parser("deals", help="List deals")
        deals_p.add_argument("--state", help="Filter by state (e.g. connected, pending)")
        deals_p.add_argument("--campaign", help="Filter by campaign name (partial match)")

        # deal detail
        deal_p = sub.add_parser("deal", help="Full detail for a single deal")
        deal_p.add_argument("id", type=int, help="Deal ID")

    def handle(self, *args, **options):
        from rich.console import Console
        self.console = Console()

        sub = options["subcommand"]
        if sub == "leads":
            self._leads(options)
        elif sub == "deals":
            self._deals(options)
        elif sub == "deal":
            self._deal(options["id"])
        else:
            self.console.print("[bold]Usage:[/bold]  manage.py crm [leads|deals|deal <id>]")

    # ------------------------------------------------------------------

    def _leads(self, options):
        from rich.table import Table
        from crm.models.lead import Lead

        qs = Lead.objects.all().order_by("-creation_date")
        if options["disqualified"]:
            qs = qs.filter(disqualified=True)

        table = Table(title="Leads", show_lines=False, header_style="bold")
        table.add_column("ID", style="dim", width=6)
        table.add_column("Identifier")
        table.add_column("Embedded", justify="center", width=8)
        table.add_column("Disqualified", justify="center", width=12)
        table.add_column("Created", width=12)

        for lead in qs:
            table.add_row(
                str(lead.pk),
                lead.public_identifier or lead.linkedin_url,
                "✓" if lead.embedding else "·",
                "[red]✗[/red]" if lead.disqualified else "·",
                lead.creation_date.strftime("%Y-%m-%d"),
            )

        self.console.print(table)
        self.console.print(f"[dim]{qs.count()} leads total[/dim]")

    def _deals(self, options):
        from rich.table import Table
        from crm.models.deal import Deal

        qs = Deal.objects.select_related("lead", "campaign").order_by("-creation_date")
        if options.get("state"):
            qs = qs.filter(state__icontains=options["state"])
        if options.get("campaign"):
            qs = qs.filter(campaign__name__icontains=options["campaign"])

        table = Table(title="Deals", show_lines=False, header_style="bold")
        table.add_column("ID", style="dim", width=5)
        table.add_column("Lead", max_width=22, no_wrap=True)
        table.add_column("Campaign", max_width=30, no_wrap=True)
        table.add_column("State", width=18, no_wrap=True)
        table.add_column("Outcome", width=15, no_wrap=True)
        table.add_column("Updated", width=11, no_wrap=True)

        for deal in qs:
            color = STATE_COLORS.get(deal.state, "white")
            outcome_color = OUTCOME_COLORS.get(deal.outcome, "dim")
            table.add_row(
                str(deal.pk),
                deal.lead.public_identifier if deal.lead else "—",
                deal.campaign.name,
                f"[{color}]{deal.state}[/{color}]",
                f"[{outcome_color}]{deal.outcome or '—'}[/{outcome_color}]",
                deal.update_date.strftime("%Y-%m-%d"),
            )

        self.console.print(table)
        self.console.print(f"[dim]{qs.count()} deals[/dim]")

    def _deal(self, deal_id):
        from rich.panel import Panel
        from rich.table import Table
        from rich import box
        from crm.models.deal import Deal
        from chat.models import ChatMessage
        from django.contrib.contenttypes.models import ContentType

        try:
            deal = Deal.objects.select_related("lead", "campaign").get(pk=deal_id)
        except Deal.DoesNotExist:
            raise CommandError(f"Deal {deal_id} not found")

        color = STATE_COLORS.get(deal.state, "white")

        # Header
        self.console.print(Panel(
            f"[bold]{deal.lead.public_identifier}[/bold]\n"
            f"Campaign: {deal.campaign.name}\n"
            f"State: [{color}]{deal.state}[/{color}]"
            + (f"   Outcome: {deal.outcome}" if deal.outcome else "")
            + (f"\nReason: [italic]{deal.reason}[/italic]" if deal.reason else ""),
            title=f"Deal #{deal.pk}",
            border_style=color,
        ))

        # Profile summary
        if deal.profile_summary:
            facts = deal.profile_summary if isinstance(deal.profile_summary, list) else []
            self.console.print(Panel(
                "\n".join(f"• {f}" for f in facts) or "[dim]empty[/dim]",
                title="Profile Summary",
                border_style="dim",
            ))

        # Chat summary
        if deal.chat_summary:
            facts = deal.chat_summary if isinstance(deal.chat_summary, list) else []
            self.console.print(Panel(
                "\n".join(f"• {f}" for f in facts) or "[dim]empty[/dim]",
                title="Chat Summary",
                border_style="dim",
            ))

        # Chat messages
        ct = ContentType.objects.get_for_model(deal)
        messages = (
            ChatMessage.objects.filter(content_type=ct, object_id=deal.pk)
            .order_by("creation_date")
        )
        if messages.exists():
            self.console.rule("[bold]Messages[/bold]")
            for msg in messages:
                direction = "[green]→ us[/green]" if msg.is_outgoing else "[cyan]← lead[/cyan]"
                ts = msg.creation_date.strftime("%Y-%m-%d %H:%M")
                self.console.print(f"[dim]{ts}[/dim] {direction}")
                self.console.print(f"  {msg.content}\n")
        else:
            self.console.print("[dim]No messages yet.[/dim]")
