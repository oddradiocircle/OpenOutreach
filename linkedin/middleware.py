"""Django middleware for per-request timezone activation.

Activates the display timezone from SiteConfig so all Django Admin
datetime fields render in the configured local time rather than UTC.
"""
from django.utils import timezone


class DisplayTimezoneMiddleware:
    """Activate the SiteConfig display_timezone for the duration of each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import zoneinfo
        try:
            from linkedin.models import SiteConfig
            tz_name = (SiteConfig.load().display_timezone or "").strip() or "America/Bogota"
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo("America/Bogota")

        timezone.activate(tz)
        try:
            response = self.get_response(request)
        finally:
            timezone.deactivate()
        return response
