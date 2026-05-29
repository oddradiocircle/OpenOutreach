from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone


class Command(BaseCommand):
    help = "Show a summary of the current system state."

    def handle(self, *args, **options):
        from crm.models import Deal
        from linkedin.models import ActionLog, Campaign, Task

        now = timezone.now()
        today = now.date()

        # --- Campaigns -------------------------------------------------------
        campaigns = Campaign.objects.all()
        self.stdout.write(self._header("Campaigns"))
        if not campaigns:
            self.stdout.write("  (none)")
        for c in campaigns:
            self.stdout.write(f"  {'[freemium] ' if c.is_freemium else ''}{ c.name}")

        # --- Deals by state --------------------------------------------------
        self.stdout.write(self._header("Deals"))
        deal_counts = (
            Deal.objects.values("campaign__name", "state")
            .annotate(n=Count("id"))
            .order_by("campaign__name", "state")
        )
        if not deal_counts:
            self.stdout.write("  (none)")
        current_campaign = None
        for row in deal_counts:
            if row["campaign__name"] != current_campaign:
                current_campaign = row["campaign__name"]
                self.stdout.write(f"\n  {current_campaign}")
            self.stdout.write(f"    {row['state']:<22} {row['n']}")

        # --- Tasks -----------------------------------------------------------
        self.stdout.write(self._header("Task queue"))
        task_counts = (
            Task.objects.values("task_type", "status")
            .annotate(n=Count("id"))
            .order_by("task_type", "status")
        )
        for row in task_counts:
            self.stdout.write(f"  {row['task_type']:<18} {row['status']:<12} {row['n']}")

        next_task = (
            Task.objects.filter(status="pending")
            .order_by("scheduled_at")
            .values("task_type", "scheduled_at", "id")
            .first()
        )
        if next_task:
            delta = next_task["scheduled_at"] - now
            mins = int(delta.total_seconds() / 60)
            self.stdout.write(
                f"\n  Next: {next_task['task_type']} in {mins}m"
                f" (scheduled {next_task['scheduled_at'].strftime('%H:%M')})"
            )

        # --- Activity today --------------------------------------------------
        self.stdout.write(self._header("Activity today"))
        action_counts = (
            ActionLog.objects.filter(created_at__date=today)
            .values("action_type", "linkedin_profile__user__username")
            .annotate(n=Count("id"))
            .order_by("action_type")
        )
        if not action_counts:
            self.stdout.write("  (no actions today)")
        for row in action_counts:
            self.stdout.write(
                f"  {row['action_type']:<18} {row['n']}  ({row['linkedin_profile__user__username']})"
            )

        self.stdout.write("")

    def _header(self, title: str) -> str:
        return f"\n{'─' * 40}\n {title.upper()}"
