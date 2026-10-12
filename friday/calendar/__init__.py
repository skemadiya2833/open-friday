"""Local calendar (secret iCal URL, no OAuth)."""

from friday.calendar.load import calendar_load
from friday.calendar.secrets import configured, redact_url

__all__ = ["calendar_load", "configured", "redact_url"]
