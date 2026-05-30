from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.db.models import Count
from django.utils import timezone
from django.utils.html import escape, format_html, mark_safe

from chat.models import ChatMessage
from crm.models.deal import Deal, Outcome
from crm.models.lead import Lead
from linkedin.enums import ProfileState

_STATE_COLORS = {
    ProfileState.QUALIFIED: "#6c757d",
    ProfileState.READY_TO_CONNECT: "#0d6efd",
    ProfileState.PENDING: "#fd7e14",
    ProfileState.CONNECTED: "#198754",
    ProfileState.COMPLETED: "#20c997",
    ProfileState.FAILED: "#dc3545",
}

_OUTCOME_LABELS = {
    Outcome.CONVERTED: ("Converted", "#20c997"),
    Outcome.NOT_INTERESTED: ("Not interested", "#6c757d"),
    Outcome.WRONG_FIT: ("Wrong fit", "#6f42c1"),
    Outcome.NO_BUDGET: ("No budget", "#fd7e14"),
    Outcome.HAS_SOLUTION: ("Has solution", "#0dcaf0"),
    Outcome.BAD_TIMING: ("Bad timing", "#ffc107"),
    Outcome.UNRESPONSIVE: ("Unresponsive", "#adb5bd"),
    Outcome.UNKNOWN: ("Unknown", "#dee2e6"),
}


class ChatMessageInline(GenericTabularInline):
    model = ChatMessage
    extra = 0
    can_delete = False
    ordering = ("creation_date",)
    fields = ("direction_col", "content", "creation_date")
    readonly_fields = ("direction_col", "content", "creation_date")
    verbose_name = "Message"
    verbose_name_plural = "Conversation"

    def has_add_permission(self, request, obj=None):
        return False

    def direction_col(self, obj):
        if obj.is_outgoing:
            return mark_safe('<span style="color:#0d6efd;font-weight:600">&rarr; Sent</span>')
        return mark_safe('<span style="color:#198754;font-weight:600">&larr; Received</span>')
    direction_col.short_description = "Dir"


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("linkedin_link", "disqualified", "deal_count", "has_embedding", "creation_date")
    list_filter = ("disqualified",)
    search_fields = ("public_identifier", "linkedin_url")
    readonly_fields = ("public_identifier", "linkedin_url", "urn", "embedding", "creation_date", "update_date")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_deal_count=Count("deal"))

    def linkedin_link(self, obj):
        return format_html('<a href="{}" target="_blank">{}</a>', obj.linkedin_url, obj.public_identifier)
    linkedin_link.short_description = "Lead"
    linkedin_link.admin_order_field = "public_identifier"

    def deal_count(self, obj):
        return obj._deal_count
    deal_count.short_description = "Deals"
    deal_count.admin_order_field = "_deal_count"

    def has_embedding(self, obj):
        return obj.embedding is not None
    has_embedding.boolean = True
    has_embedding.short_description = "Embedded"


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = (
        "linkedin_link", "campaign", "state_badge", "outcome_badge",
        "days_idle", "has_pending_message", "creation_date",
    )
    list_filter = ("state", "outcome", "campaign", "pending_message_approved")
    search_fields = ("lead__public_identifier",)
    list_select_related = ["lead", "campaign"]
    inlines = [ChatMessageInline]
    readonly_fields = (
        "lead", "campaign", "state", "outcome", "reason",
        "connect_attempts", "backoff_hours", "next_check_pending_at",
        "profile_summary_display", "chat_summary_display", "creation_date", "update_date",
    )
    fields = readonly_fields + ("pending_message", "pending_message_approved")
    date_hierarchy = "creation_date"

    def linkedin_link(self, obj):
        if not obj.lead_id:
            return "—"
        url = obj.lead.linkedin_url
        name = obj.lead.public_identifier
        return format_html('<a href="{}" target="_blank">{}</a>', url, name)
    linkedin_link.short_description = "Lead"
    linkedin_link.admin_order_field = "lead__public_identifier"

    def state_badge(self, obj):
        color = _STATE_COLORS.get(obj.state, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;white-space:nowrap">{}</span>',
            color, obj.state,
        )
    state_badge.short_description = "State"
    state_badge.admin_order_field = "state"

    def outcome_badge(self, obj):
        if not obj.outcome:
            return "—"
        label, color = _OUTCOME_LABELS.get(obj.outcome, (obj.outcome, "#6c757d"))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;white-space:nowrap">{}</span>',
            color, label,
        )
    outcome_badge.short_description = "Outcome"
    outcome_badge.admin_order_field = "outcome"

    def days_idle(self, obj):
        delta = timezone.now() - obj.update_date
        days = delta.days
        color = "#dc3545" if days > 7 else ("#fd7e14" if days > 3 else "#198754")
        return format_html('<span style="color:{};font-weight:600">{}</span>', color, f"{days}d")
    days_idle.short_description = "Idle"
    days_idle.admin_order_field = "update_date"

    def has_pending_message(self, obj):
        return bool(obj.pending_message)
    has_pending_message.boolean = True
    has_pending_message.short_description = "Draft"

    def _render_facts(self, data):
        if not data:
            return "—"
        facts = data if isinstance(data, list) else data.get("facts", [])
        if not facts:
            return "—"
        items = "".join(
            f'<li style="margin-bottom:4px">{fact}</li>' for fact in facts
        )
        return mark_safe(f'<ul style="margin:0;padding-left:18px">{items}</ul>')

    def profile_summary_display(self, obj):
        return self._render_facts(obj.profile_summary)
    profile_summary_display.short_description = "Profile Summary"

    def chat_summary_display(self, obj):
        return self._render_facts(obj.chat_summary)
    chat_summary_display.short_description = "Chat Summary"
