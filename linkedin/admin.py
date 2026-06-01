# linkedin/admin.py
from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import escape, format_html, mark_safe

from chat.models import ChatMessage
from linkedin.enums import ProfileState
from linkedin.models import ActionLog, Campaign, CampaignPromptOverride, LinkedInProfile, PromptTemplate, SearchKeyword, SiteConfig, Task


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "llm_provider", "ai_model", "llm_api_base")

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "updated_at")
    readonly_fields = ("description",)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["body"].widget.attrs.update({"rows": 30, "cols": 120, "style": "font-family:monospace"})
        return form

    def has_add_permission(self, request):
        return False

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


class CampaignPromptOverrideInline(admin.TabularInline):
    model = CampaignPromptOverride
    extra = 0
    fields = ("prompt_key", "body", "_global_hint")
    readonly_fields = ("_global_hint",)

    def _global_hint(self, obj):
        if not obj or not obj.prompt_key:
            return "—"
        try:
            from linkedin.models import PromptTemplate
            pt = PromptTemplate.objects.get(key=obj.prompt_key)
            preview = pt.body[:200].replace("\n", " ").strip()
            return format_html(
                '<span style="font-size:11px;color:#666;font-family:monospace">{}</span>',
                preview + ("…" if len(pt.body) > 200 else ""),
            )
        except Exception:
            return "—"
    _global_hint.short_description = "Global default (first 200 chars)"

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if "body" in formset.form.base_fields:
            formset.form.base_fields["body"].widget.attrs.update(
                {"rows": 6, "style": "font-family:monospace;width:100%"}
            )
        return formset


_PIPELINE_CONDITION_FIELDS = (
    "follow_up_cooldown_hours",
    "reengagement_greeting_days",
    "gpr_qualification_threshold",
    "connect_daily_limit",
    "follow_up_daily_limit",
    "check_pending_daily_cap",
    "max_followups_without_reply",
    "min_qualification_observations_before_connect",
    "preconnect_qualification_batch_size",
)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "deal_pipeline", "require_message_approval", "booking_link")
    filter_horizontal = ("users",)
    inlines = [CampaignPromptOverrideInline]
    fieldsets = (
        (None, {
            "fields": ("name", "users", "product_docs", "campaign_objective",
                       "booking_link", "website_url", "require_message_approval"),
        }),
        ("Pipeline Conditions (overrides)", {
            "classes": ("collapse",),
            "fields": _PIPELINE_CONDITION_FIELDS,
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        try:
            from linkedin.models import SiteConfig
            site = SiteConfig.load()
        except Exception:
            return form
        hints = {
            "follow_up_cooldown_hours": f"Global default: {site.follow_up_cooldown_hours} h",
            "reengagement_greeting_days": f"Global default: {site.reengagement_greeting_days} days",
            "gpr_qualification_threshold": f"Global default: {site.gpr_qualification_threshold}",
            "connect_daily_limit": f"Global default: {site.connect_daily_limit}/day",
            "follow_up_daily_limit": f"Global default: {site.follow_up_daily_limit}/day",
            "check_pending_daily_cap": f"Global default: {site.check_pending_daily_cap}/day",
            "max_followups_without_reply": f"Global default: {site.max_followups_without_reply}",
            "min_qualification_observations_before_connect": (
                f"Global default: {site.min_qualification_observations_before_connect} observations"
            ),
            "preconnect_qualification_batch_size": (
                f"Global default: {site.preconnect_qualification_batch_size} lead(s)"
            ),
        }
        for field, hint in hints.items():
            if field in form.base_fields:
                form.base_fields[field].help_text = hint
        return form

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
    list_display = ("action_type", "lead_col", "campaign", "daily_usage", "created_at")
    list_filter = ("action_type", "campaign")
    raw_id_fields = ("linkedin_profile", "campaign")
    date_hierarchy = "created_at"
    readonly_fields = ("linkedin_profile", "lead_detail", "campaign", "action_type", "created_at", "message_sent")
    fields = ("action_type", "linkedin_profile", "lead_detail", "campaign", "created_at", "message_sent")
    ordering = ("-created_at",)

    def lead_col(self, obj):
        if not obj.lead_id:
            return "—"
        return obj.lead.public_identifier
    lead_col.short_description = "Lead"

    def lead_detail(self, obj):
        if not obj.lead_id:
            return "—"
        lead = obj.lead
        deal_url = f"/admin/crm/deal/?lead__public_identifier={lead.public_identifier}"
        return format_html(
            '<a href="{}" target="_blank">{}</a> &nbsp;'
            '<small><a href="{}">ver deal →</a></small>',
            lead.linkedin_url, lead.public_identifier, deal_url,
        )
    lead_detail.short_description = "Lead"

    def message_sent(self, obj):
        if not obj.lead_id:
            return "—"
        from chat.models import ChatMessage
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(obj.lead.__class__)
        msg = (
            ChatMessage.objects
            .filter(
                content_type=ct,
                object_id=obj.lead_id,
                is_outgoing=True,
                creation_date__lte=obj.created_at,
            )
            .order_by("-creation_date")
            .first()
        )
        if not msg:
            return "—"
        date_str = msg.creation_date.strftime("%Y-%m-%d %H:%M") if msg.creation_date else ""
        content_html = escape(msg.content).replace("\n", "<br>")
        return mark_safe(
            f'<div style="background:#dbeafe;color:#212529;padding:10px 14px;'
            f'border-radius:8px;border-left:4px solid #1d4ed8;max-width:600px">'
            f'<div style="font-size:11px;color:#1d4ed8;font-weight:600;margin-bottom:6px">'
            f'Enviado · {date_str}</div>'
            f'{content_html}</div>'
        )
    message_sent.short_description = "Mensaje enviado"

    def get_queryset(self, request):
        from django.db.models import IntegerField, OuterRef, Subquery
        from django.utils import timezone

        qs = super().get_queryset(request).select_related("linkedin_profile", "campaign")
        today = timezone.now().date()
        daily_sq = Subquery(
            ActionLog.objects.filter(
                linkedin_profile=OuterRef("linkedin_profile"),
                action_type=OuterRef("action_type"),
                created_at__date=today,
            )
            .values("linkedin_profile", "action_type")
            .annotate(n=Count("pk"))
            .values("n"),
            output_field=IntegerField(),
        )
        return qs.annotate(_daily_count=daily_sq)

    def daily_usage(self, obj):
        count = obj._daily_count or 0
        limit_field = {
            ActionLog.ActionType.CONNECT: "connect_daily_limit",
            ActionLog.ActionType.FOLLOW_UP: "follow_up_daily_limit",
        }.get(obj.action_type)
        if not limit_field:
            return str(count)
        limit = getattr(obj.linkedin_profile, limit_field, None)
        if limit is None:
            return str(count)
        ratio = count / limit if limit else 1
        color = "#dc3545" if ratio >= 1 else ("#fd7e14" if ratio >= 0.8 else "#198754")
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>'
            '<span style="color:#6c757d"> / {}</span>',
            color, count, limit,
        )
    daily_usage.short_description = "Hoy"


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
