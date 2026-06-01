from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CampaignLead(models.Model):
    class Source(models.TextChoices):
        LINKEDIN_CONNECTION = "linkedin_connection", _("LinkedIn connection")
        LINKEDIN_INVITATION = "linkedin_invitation", _("LinkedIn invitation")
        IMPORTED_CONTACT = "imported_contact", _("Imported contact")
        LINKEDIN_SEARCH = "linkedin_search", _("LinkedIn search")
        MANUAL = "manual", _("Manual")

    class RelationshipStatus(models.TextChoices):
        CONNECTED = "connected", _("Connected")
        INVITED = "invited", _("Invited")
        UNKNOWN = "unknown", _("Unknown")

    campaign = models.ForeignKey(
        "linkedin.Campaign",
        on_delete=models.CASCADE,
        related_name="campaign_leads",
    )
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.CASCADE,
        related_name="campaign_leads",
    )
    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    relationship_status = models.CharField(
        max_length=16,
        choices=RelationshipStatus.choices,
        default=RelationshipStatus.UNKNOWN,
    )
    priority = models.IntegerField(default=100, db_index=True)
    connected_on = models.DateField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    creation_date = models.DateTimeField(default=timezone.now)
    update_date = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Campaign lead")
        verbose_name_plural = _("Campaign leads")
        constraints = [
            models.UniqueConstraint(fields=["campaign", "lead"], name="unique_campaign_lead"),
        ]
        indexes = [
            models.Index(fields=["campaign", "priority", "creation_date"]),
            models.Index(fields=["campaign", "relationship_status"]),
        ]

    def __str__(self):
        return f"{self.lead} in {self.campaign}"
