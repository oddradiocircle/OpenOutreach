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
    list_display = ("lead", "campaign", "state", "outcome", "creation_date")
    list_filter = ("state", "outcome", "campaign")
    search_fields = ("lead__public_identifier",)
    readonly_fields = (
        "lead", "campaign", "state", "outcome", "reason",
        "connect_attempts", "backoff_hours", "next_check_pending_at",
        "profile_summary", "chat_summary", "creation_date", "update_date",
    )
    date_hierarchy = "creation_date"
