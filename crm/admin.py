from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.contrib.contenttypes.admin import GenericTabularInline
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.html import escape, format_html, mark_safe
from django.utils.timezone import localtime as _localtime

from chat.models import ChatMessage
from crm.models.campaign_lead import CampaignLead
from crm.models.deal import Deal, Outcome
from crm.models.lead import Lead
from linkedin.enums import ProfileState

class PendingApprovalFilter(SimpleListFilter):
    title = "Autorización"
    parameter_name = "aprobacion"

    def lookups(self, request, model_admin):
        return [
            ("pendiente", "⏳ Esperando autorización"),
            ("aprobado", "✓ Aprobado"),
            ("sin_borrador", "Sin borrador"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "pendiente":
            return queryset.filter(pending_message_approved=False).exclude(pending_message="").exclude(pending_message__isnull=True)
        if self.value() == "aprobado":
            return queryset.filter(pending_message_approved=True).exclude(pending_message="").exclude(pending_message__isnull=True)
        if self.value() == "sin_borrador":
            return queryset.filter(pending_message_approved=False).filter(pending_message__in=["", None])
        return queryset


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
        date_str = _localtime(msg.creation_date).strftime("%Y-%m-%d %H:%M")
        content_html = escape(msg.content).replace("\n", "<br>")
        bubbles.append(
            f'<div style="margin-bottom:10px;text-align:{align}">'
            f'<div style="display:inline-block;max-width:75%;text-align:left;'
            f'background:{bg};color:#212529;padding:8px 12px;border-radius:8px;border:{border}">'
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
    list_display = (
        "linkedin_link", "headline_col", "company_col",
        "location_col", "languages_col", "industry_col",
        "disqualified", "deal_count", "creation_date",
    )
    list_filter = ("disqualified", "country_code", "industry")
    search_fields = (
        "public_identifier", "linkedin_url",
        "full_name", "headline", "current_company", "current_title",
    )
    readonly_fields = (
        "public_identifier", "linkedin_url", "urn",
        "full_name", "first_name", "headline", "industry",
        "current_company", "current_title",
        "location", "country_code", "languages",
        "embedding", "creation_date", "update_date",
    )
    inlines = [ChatMessageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_deal_count=Count("deal"))

    def linkedin_link(self, obj):
        label = obj.full_name or obj.public_identifier
        return format_html('<a href="{}" target="_blank">{}</a>', obj.linkedin_url, label)
    linkedin_link.short_description = "Lead"
    linkedin_link.admin_order_field = "full_name"

    def headline_col(self, obj):
        return obj.headline or "—"
    headline_col.short_description = "Título"
    headline_col.admin_order_field = "headline"

    def company_col(self, obj):
        if not obj.current_company:
            return "—"
        label = obj.current_company
        if obj.current_title:
            label = f"{obj.current_title} @ {obj.current_company}"
        return label
    company_col.short_description = "Empresa / Cargo"
    company_col.admin_order_field = "current_company"

    def location_col(self, obj):
        return obj.location or "—"
    location_col.short_description = "Ubicación"
    location_col.admin_order_field = "location"

    def languages_col(self, obj):
        if not obj.languages:
            return "—"
        return ", ".join(obj.languages)
    languages_col.short_description = "Idiomas"

    def industry_col(self, obj):
        return obj.industry or "—"
    industry_col.short_description = "Industria"
    industry_col.admin_order_field = "industry"

    def deal_count(self, obj):
        return obj._deal_count
    deal_count.short_description = "Deals"
    deal_count.admin_order_field = "_deal_count"


@admin.register(CampaignLead)
class CampaignLeadAdmin(admin.ModelAdmin):
    list_display = (
        "lead_link",
        "lead_title_company",
        "lead_location",
        "campaign",
        "source",
        "relationship_status",
        "connected_on",
        "creation_date",
    )
    list_filter = ("campaign", "source", "relationship_status", "lead__country_code")
    search_fields = (
        "lead__public_identifier",
        "lead__full_name",
        "lead__headline",
        "lead__current_company",
        "lead__linkedin_url",
        "campaign__name",
    )
    list_select_related = ("lead", "campaign")
    readonly_fields = ("creation_date", "update_date")
    date_hierarchy = "creation_date"
    ordering = ("campaign", "priority", "creation_date")

    def lead_link(self, obj):
        label = obj.lead.full_name or obj.lead.public_identifier
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            obj.lead.linkedin_url,
            label,
        )
    lead_link.short_description = "Lead"
    lead_link.admin_order_field = "lead__full_name"

    def lead_title_company(self, obj):
        parts = [p for p in (obj.lead.current_title, obj.lead.current_company) if p]
        return " @ ".join(parts) if parts else "—"
    lead_title_company.short_description = "Cargo / Empresa"
    lead_title_company.admin_order_field = "lead__current_company"

    def lead_location(self, obj):
        return obj.lead.location or "—"
    lead_location.short_description = "Ubicación"
    lead_location.admin_order_field = "lead__location"


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = (
        "lead_name", "li_icon", "campaign", "state_badge", "outcome_badge",
        "conv_status", "days_idle", "message_count", "pending_status",
    )
    list_display_links = ("lead_name",)
    list_filter = ("state", "outcome", "campaign", PendingApprovalFilter)
    search_fields = ("lead__public_identifier",)
    list_select_related = ["lead", "campaign"]
    readonly_fields = (
        "lead", "campaign", "state", "outcome", "reason",
        "connect_attempts", "backoff_hours", "next_check_pending_at",
        "profile_summary_display", "chat_summary_display",
        "conversation_thread", "creation_date", "update_date",
        "rejection_feedback", "regeneration_count",
    )
    fields = readonly_fields + ("pending_message", "pending_message_approved")
    date_hierarchy = "creation_date"

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.pending_message and not obj.pending_message_approved:
            fields.append("reject_regen_widget")
        return fields

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if obj and obj.pending_message and not obj.pending_message_approved:
            if "pending_message" in fields:
                fields.insert(fields.index("pending_message") + 1, "reject_regen_widget")
            else:
                fields.append("reject_regen_widget")
        return fields

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST" and request.POST.get("_action") == "reject_regen":
            return self._handle_reject_regen(request, object_id)
        return super().changeform_view(request, object_id, form_url, extra_context)

    def _handle_reject_regen(self, request, object_id):
        from django.contrib import messages
        from django.utils import timezone as tz
        from linkedin.models import Task

        try:
            deal = Deal.objects.select_related("lead", "campaign").get(pk=object_id)
        except Deal.DoesNotExist:
            messages.error(request, "Deal not found.")
            return HttpResponseRedirect("../")

        feedback = request.POST.get("_regen_feedback", "").strip()
        if not feedback:
            messages.error(request, "Feedback is required for Reject & Regenerate.")
            return HttpResponseRedirect(request.path)

        deal.rejection_feedback = feedback
        deal.regeneration_count = (deal.regeneration_count or 0) + 1
        deal.pending_message = ""
        deal.pending_message_approved = False
        deal.save(update_fields=["rejection_feedback", "regeneration_count", "pending_message", "pending_message_approved"])

        Task.objects.create(
            task_type=Task.TaskType.FOLLOW_UP,
            scheduled_at=tz.now(),
            payload={"campaign_id": deal.campaign_id, "deal_id": deal.pk, "regeneration_feedback": feedback},
        )
        messages.success(request, f"Draft rejected. Regeneration dispatched for {deal.lead.public_identifier}.")
        return HttpResponseRedirect(request.path)

    def reject_regen_widget(self, obj):
        return mark_safe(
            '<div style="margin-top:4px">'
            '<p style="margin:0 0 6px;color:#dc3545;font-weight:600">Rechazar y regenerar</p>'
            '<textarea name="_regen_feedback" rows="4" '
            'style="width:100%;max-width:600px;font-family:monospace;font-size:13px" '
            'placeholder="Ej: Demasiado formal. Menciona su publicación reciente sobre IA."></textarea>'
            '<p style="margin:6px 0 0">'
            '<button type="submit" name="_action" value="reject_regen" '
            'style="background:#dc3545;color:#fff;border:none;padding:5px 14px;'
            'border-radius:4px;cursor:pointer;font-size:13px;font-weight:600">'
            'Rechazar &amp; Regenerar</button>'
            '<span style="margin-left:8px;font-size:12px;color:#666">'
            'El borrador actual se descarta y se genera uno nuevo con este feedback.</span>'
            '</p></div>'
        )
    reject_regen_widget.short_description = "Feedback para regeneración"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "pending_message_approved" in form.changed_data and obj.pending_message_approved and obj.pending_message:
            from django.utils import timezone as tz
            from linkedin.models import Task
            Task.objects.create(
                task_type=Task.TaskType.FOLLOW_UP,
                scheduled_at=tz.now(),
                payload={"campaign_id": obj.campaign_id},
            )

    def get_queryset(self, request):
        from chat.models import ChatMessage
        from django.contrib.contenttypes.models import ContentType
        from django.db.models import OuterRef, Subquery

        qs = super().get_queryset(request)
        lead_ct_id = ContentType.objects.get_for_model(Lead).id
        last_msg_qs = ChatMessage.objects.filter(
            content_type_id=lead_ct_id,
            object_id=OuterRef("lead_id"),
        ).order_by("-creation_date")
        return qs.annotate(
            _last_msg_is_outgoing=Subquery(last_msg_qs.values("is_outgoing")[:1]),
            _last_msg_date=Subquery(last_msg_qs.values("creation_date")[:1]),
        )

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

    def conv_status(self, obj):
        if not obj.lead_id:
            return "—"
        is_outgoing = obj._last_msg_is_outgoing
        msg_date = obj._last_msg_date
        if is_outgoing is None:
            return mark_safe('<span style="color:#6c757d;font-size:11px">Sin mensajes</span>')
        now = timezone.now()
        if msg_date:
            delta = now - msg_date
            age = f"{delta.days}d" if delta.days >= 1 else f"{max(int(delta.total_seconds() // 3600), 1)}h"
        else:
            age = "?"
        if not is_outgoing:
            return format_html(
                '<span style="background:#d1fae5;color:#065f46;padding:1px 6px;'
                'border-radius:4px;font-size:11px;font-weight:600">← Respondió</span> '
                '<span style="color:#6c757d;font-size:11px">{}</span>',
                age,
            )
        return format_html(
            '<span style="background:#fef3c7;color:#92400e;padding:1px 6px;'
            'border-radius:4px;font-size:11px;font-weight:600">→ Enviado</span> '
            '<span style="color:#6c757d;font-size:11px">{}</span>',
            age,
        )
    conv_status.short_description = "Último msg"
    conv_status.admin_order_field = "_last_msg_date"

    def pending_status(self, obj):
        if not obj.pending_message:
            return "—"
        if obj.pending_message_approved:
            return mark_safe(
                '<span style="background:#d1fae5;color:#065f46;padding:1px 6px;'
                'border-radius:4px;font-size:11px;font-weight:600">✓ Aprobado</span>'
            )
        return mark_safe(
            '<span style="background:#fef3c7;color:#92400e;padding:1px 6px;'
            'border-radius:4px;font-size:11px;font-weight:600">⏳ Borrador</span>'
        )
    pending_status.short_description = "Draft"

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
