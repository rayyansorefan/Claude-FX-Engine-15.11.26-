"""Stale data must fail loudly."""
import pandas as pd


class StaleDataError(RuntimeError):
    pass


def age_seconds(last_close_time, now) -> float:
    return (pd.Timestamp(now) - pd.Timestamp(last_close_time)).total_seconds()


def check_fresh(last_close_time, now, max_age_s: int = 300, label: str = "data") -> float:
    """Return age in seconds, or raise StaleDataError if older than max_age_s
    or if the data is dated in the future (clock/look-ahead problem)."""
    age = age_seconds(last_close_time, now)
    if age < -1:
        raise StaleDataError(f"{label}: close time is {-age:.0f}s in the future")
    if age > max_age_s:
        raise StaleDataError(f"{label}: {age:.0f}s old (limit {max_age_s}s)")
    return age
