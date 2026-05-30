# linkedin/admin.py
from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import escape, format_html, mark_safe

from chat.models import ChatMessage
from linkedin.enums import ProfileState
from linkedin.models import ActionLog, Campaign, LinkedInProfile, SearchKeyword, SiteConfig, Task


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "llm_provider", "ai_model", "llm_api_base")

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


def _state_pill(count, label, color):
    if not count:
        return ""
    return (
        f'<span style="background:{color};color:#fff;padding:1px 6px;'
        f'border-radius:4px;font-size:11px;margin-right:3px">'
        f'{label}&nbsp;{count}</span>'
    )


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "deal_pipeline", "require_message_approval", "booking_link")
    filter_horizontal = ("users",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _qualified=Count("deals", filter=Q(deals__state=ProfileState.QUALIFIED)),
            _ready=Count("deals", filter=Q(deals__state=ProfileState.READY_TO_CONNECT)),
            _pending=Count("deals", filter=Q(deals__state=ProfileState.PENDING)),
            _connected=Count("deals", filter=Q(deals__state=ProfileState.CONNECTED)),
            _completed=Count("deals", filter=Q(deals__state=ProfileState.COMPLETED)),
            _failed=Count("deals", filter=Q(deals__state=ProfileState.FAILED)),
        )

    def deal_pipeline(self, obj):
        pills = "".join([
            _state_pill(obj._qualified, "Qualified", "#6c757d"),
            _state_pill(obj._ready, "Ready", "#0d6efd"),
            _state_pill(obj._pending, "Pending", "#fd7e14"),
            _state_pill(obj._connected, "Connected", "#198754"),
            _state_pill(obj._completed, "Completed", "#20c997"),
            _state_pill(obj._failed, "Failed", "#dc3545"),
        ])
        return mark_safe(pills) if pills else "—"
    deal_pipeline.short_description = "Pipeline"


@admin.register(LinkedInProfile)
class LinkedInProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "linkedin_username", "contact_email", "active", "legal_accepted")
    list_filter = ("active",)
    raw_id_fields = ("user", "self_lead")


@admin.register(SearchKeyword)
class SearchKeywordAdmin(admin.ModelAdmin):
    list_display = ("keyword", "campaign", "used", "used_at")
    list_filter = ("used", "campaign")
    raw_id_fields = ("campaign",)


@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ("action_type", "linkedin_profile", "campaign", "created_at")
    list_filter = ("action_type", "campaign")
    raw_id_fields = ("linkedin_profile", "campaign")
    date_hierarchy = "created_at"
    readonly_fields = ("linkedin_profile", "campaign", "action_type", "created_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("task_type", "status", "scheduled_at", "campaign_name", "created_at")
    list_filter = ("task_type", "status")
    readonly_fields = (
        "task_type", "status", "scheduled_at", "payload",
        "created_at", "started_at", "completed_at",
    )
    date_hierarchy = "scheduled_at"
    _campaign_cache: dict = {}

    def campaign_name(self, obj):
        campaign_id = obj.payload.get("campaign_id")
        if not campaign_id:
            return "—"
        if campaign_id not in self._campaign_cache:
            try:
                self._campaign_cache[campaign_id] = Campaign.objects.get(pk=campaign_id).name
            except Campaign.DoesNotExist:
                self._campaign_cache[campaign_id] = f"Campaign #{campaign_id}"
        return self._campaign_cache[campaign_id]
    campaign_name.short_description = "Campaign"


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("message_preview", "direction", "participants", "creation_date")
    list_filter = ("is_outgoing",)
    ordering = ["object_id", "creation_date"]
    search_fields = ("content",)
    date_hierarchy = "creation_date"
    readonly_fields = (
        "conversation_thread", "direction_display",
        "content", "owner", "is_outgoing", "creation_date", "linkedin_urn",
    )
    fields = ("conversation_thread", "direction_display", "content", "owner", "creation_date", "linkedin_urn")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("owner", "content_type")

    def message_preview(self, obj):
        text = obj.content[:80] + "…" if len(obj.content) > 80 else obj.content
        return text
    message_preview.short_description = "Message"

    def direction(self, obj):
        if obj.is_outgoing:
            return mark_safe('<span style="color:#0d6efd;font-weight:600">&rarr; Enviado</span>')
        return mark_safe('<span style="color:#198754;font-weight:600">&larr; Recibido</span>')
    direction.short_description = "Dir"
    direction.admin_order_field = "is_outgoing"

    def direction_display(self, obj):
        return self.direction(obj)
    direction_display.short_description = "Dirección"

    def participants(self, obj):
        lead = obj.content_object
        if lead is None:
            return "—"
        try:
            seller = obj.owner.get_full_name() or obj.owner.username if obj.owner else "?"
            lead_url = f"/admin/crm/lead/{lead.pk}/change/"
            thread_url = f"/admin/chat/chatmessage/?object_id={obj.object_id}"
            return format_html(
                '<a href="{}">{}</a>'
                ' &harr; <strong>{}</strong>'
                ' <small style="color:#6c757d">&mdash; <a href="{}">ver hilo</a></small>',
                lead_url, lead.public_identifier, seller, thread_url,
            )
        except Exception:
            return f"Lead #{obj.object_id}"
    participants.short_description = "Conversación"

    def conversation_thread(self, obj):
        lead = obj.content_object
        if lead is None:
            return "—"
        try:
            lead_name = lead.public_identifier
            lead_li_url = lead.linkedin_url
            seller = obj.owner.get_full_name() or obj.owner.username if obj.owner else "?"
        except Exception:
            lead_name, lead_li_url, seller = f"Lead #{obj.object_id}", "", "?"

        messages = (
            ChatMessage.objects
            .filter(content_type=obj.content_type, object_id=obj.object_id)
            .order_by("creation_date")
        )

        from crm.admin import _render_chat_thread
        header = format_html(
            '<div style="margin-bottom:10px;padding:8px 12px;background:#f8f9fa;'
            'border-radius:6px;border-left:4px solid #0d6efd">'
            '<strong><a href="{}" target="_blank">{}</a></strong>'
            ' &harr; <strong>{}</strong>'
            '</div>',
            lead_li_url, lead_name, seller,
        )
        return mark_safe(str(header) + _render_chat_thread(messages, highlight_pk=obj.pk))
    conversation_thread.short_description = "Hilo de conversación"
