from django.contrib import admin

from crm.models.deal import Deal
from crm.models.lead import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("public_identifier", "linkedin_url", "disqualified", "has_embedding", "creation_date")
    list_filter = ("disqualified",)
    search_fields = ("public_identifier", "linkedin_url")
    readonly_fields = ("public_identifier", "linkedin_url", "urn", "embedding", "creation_date", "update_date")

    def has_embedding(self, obj):
        return obj.embedding is not None
    has_embedding.boolean = True
    has_embedding.short_description = "Embedded"


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("lead", "campaign", "state", "outcome", "has_pending_message", "creation_date")
    list_filter = ("state", "outcome", "campaign", "pending_message_approved")
    search_fields = ("lead__public_identifier",)
    readonly_fields = (
        "lead", "campaign", "state", "outcome", "reason",
        "connect_attempts", "backoff_hours", "next_check_pending_at",
        "profile_summary", "chat_summary", "creation_date", "update_date",
    )
    fields = readonly_fields + ("pending_message", "pending_message_approved")
    date_hierarchy = "creation_date"

    def has_pending_message(self, obj):
        return bool(obj.pending_message)
    has_pending_message.boolean = True
    has_pending_message.short_description = "Draft"
