"""
analytics/models/__init__.py
"""
from .consumption import compute_consumption_rate, days_until_empty, is_buy_soon
from .anomaly import check_environment

__all__ = [
    "compute_consumption_rate",
    "days_until_empty",
    "is_buy_soon",
    "check_environment",
]
