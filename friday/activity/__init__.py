"""Activity awareness — ActivityWatch (optional) and consent-gated local sampling."""

from friday.activity.aw import ActivityWatchClient
from friday.activity.metrics import compute_metrics

__all__ = ["ActivityWatchClient", "compute_metrics"]
