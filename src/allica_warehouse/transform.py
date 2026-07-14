"""
Transform helpers that don't require a database round-trip.

Customer and product transformations are SCD-aware and need to compare
against what's already in the database, so that logic lives in `load.py`
alongside the upsert code. This module only covers the date dimension,
which is a pure function of the dates present in the batch.
"""
import pandas as pd


def build_date_rows(dates) -> list:
    """Build one dim_date row per unique date in `dates` (an iterable of date objects)."""
    unique_dates = sorted(set(dates))
    rows = []
    for d in unique_dates:
        ts = pd.Timestamp(d)
        rows.append(
            {
                "date_key": int(ts.strftime("%Y%m%d")),
                "full_date": d,
                "year": ts.year,
                "quarter": int((ts.month - 1) // 3 + 1),
                "month": ts.month,
                "month_name": ts.strftime("%B"),
                "day": ts.day,
                "day_of_week": ts.dayofweek,
                "day_name": ts.strftime("%A"),
                "is_weekend": ts.dayofweek >= 5,
            }
        )
    return rows
