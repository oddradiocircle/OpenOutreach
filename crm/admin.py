from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.contrib.contenttypes.models import ContentType
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


def _render_chat_thread(messages, highlight_pk=None):
    """Render a queryset of ChatMessage rows as chat bubbles HTML."""
    if not messages:
        return "<em>Sin mensajes.</em>"
    bubbles = []
    for msg in messages:
        if msg.is_outgoing:
            bg, align, label, label_color = "#dbeafe", "right", "→ Enviado", "#1d4ed8"
        else:
            bg, align, label, label_color = "#dcfce7", "left", "← Recibido", "#15803d"
        border = "2px solid #1d4ed8" if msg.pk == highlight_pk else "1px solid transparent"
        date_str = msg.creation_date.strftime("%Y-%m-%d %H:%M")
        content_html = escape(msg.content).replace("\n", "<br>")
        bubbles.append(
            f'<div style="margin-bottom:10px;text-align:{align}">'
            f'<div style="display:inline-block;max-width:75%;text-align:left;'
            f'background:{bg};padding:8px 12px;border-radius:8px;border:{border}">'
            f'<div style="font-size:11px;color:{label_color};font-weight:600;margin-bottom:4px">'
            f'{label} &bull; {date_str}</div>'
            f'{content_html}'
            f'</div></div>'
        )
    return (
        '<div style="border:1px solid #dee2e6;border-radius:8px;padding:12px;'
        'max-height:600px;overflow-y:auto">'
        + "".join(bubbles)
        + "</div>"
    )


class ChatMessageInline(GenericTabularInline):
    """Inline that shows conversation on LeadAdmin (messages are stored per Lead)."""
    model = ChatMessage
    extra = 0
    can_delete = False
    ordering = ("creation_date",)
    fields = ("direction_col", "content", "creation_date")
    readonly_fields = ("direction_col", "content", "creation_date")
    verbose_name = "Mensaje"
    verbose_name_plural = "Conversación"

    def has_add_permission(self, request, obj=None):
        return False

    def direction_col(self, obj):
        if obj.is_outgoing:
            return mark_safe('<span style="color:#0d6efd;font-weight:600">&rarr; Enviado</span>')
        return mark_safe('<span style="color:#198754;font-weight:600">&larr; Recibido</span>')
    direction_col.short_description = "Dir"


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("linkedin_link", "disqualified", "deal_count", "has_embedding", "creation_date")
    list_filter = ("disqualified",)
    search_fields = ("public_identifier", "linkedin_url")
    readonly_fields = ("public_identifier", "linkedin_url", "urn", "embedding", "creation_date", "update_date")
    inlines = [ChatMessageInline]

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
        "lead_name", "li_icon", "campaign", "state_badge", "outcome_badge",
        "days_idle", "message_count", "has_pending_message", "creation_date",
    )
    list_display_links = ("lead_name",)
    list_filter = ("state", "outcome", "campaign", "pending_message_approved")
    search_fields = ("lead__public_identifier",)
    list_select_related = ["lead", "campaign"]
    readonly_fields = (
        "lead", "campaign", "state", "outcome", "reason",
        "connect_attempts", "backoff_hours", "next_check_pending_at",
        "profile_summary_display", "chat_summary_display",
        "conversation_thread", "creation_date", "update_date",
    )
    fields = readonly_fields + ("pending_message", "pending_message_approved")
    date_hierarchy = "creation_date"

    def lead_name(self, obj):
        return obj.lead.public_identifier if obj.lead_id else "—"
    lead_name.short_description = "Lead"
    lead_name.admin_order_field = "lead__public_identifier"

    def li_icon(self, obj):
        if not obj.lead_id:
            return ""
        return format_html('<a href="{}" target="_blank" title="Ver en LinkedIn">↗</a>', obj.lead.linkedin_url)
    li_icon.short_description = "Li"

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

    def message_count(self, obj):
        if not obj.lead_id:
            return "—"
        ct = ContentType.objects.get_for_model(Lead)
        n = ChatMessage.objects.filter(content_type=ct, object_id=obj.lead_id).count()
        if not n:
            return "—"
        msgs_url = f"/admin/chat/chatmessage/?object_id={obj.lead_id}"
        return format_html('<a href="{}">{} 💬</a>', msgs_url, n)
    message_count.short_description = "Msgs"

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
        items = "".join(f'<li style="margin-bottom:4px">{fact}</li>' for fact in facts)
        return mark_safe(f'<ul style="margin:0;padding-left:18px">{items}</ul>')

    def profile_summary_display(self, obj):
        return self._render_facts(obj.profile_summary)
    profile_summary_display.short_description = "Profile Summary"

    def chat_summary_display(self, obj):
        return self._render_facts(obj.chat_summary)
    chat_summary_display.short_description = "Chat Summary"

    def conversation_thread(self, obj):
        if not obj.lead_id:
            return "—"
        ct = ContentType.objects.get_for_model(Lead)
        messages = (
            ChatMessage.objects
            .filter(content_type=ct, object_id=obj.lead_id)
            .order_by("creation_date")
        )
        return mark_safe(_render_chat_thread(messages))
    conversation_thread.short_description = "Conversación"
