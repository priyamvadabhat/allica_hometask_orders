"""Transformation helpers for validating and shaping order rows before loading."""

from typing import Any

from .loading import prepare_fact_row
from .utils import logger
from .validation import validate_row


def transform_rows(connection: Any, rows: list[dict[str, Any]], source_file_name: str) -> tuple[list[tuple[Any, ...]], list[str], int]:
    """Validate rows, prepare fact rows, and collect rejection reasons."""
    prepared_rows: list[tuple[Any, ...]] = []
    reject_reasons: list[str] = []
    valid_rows = 0

    for row in rows:
        valid, issues = validate_row(row)
        if not valid:
            reject_reasons.append("; ".join(issues))
            logger.warning("Rejected row in %s: %s", source_file_name, "; ".join(issues))
            continue

        prepared_row = prepare_fact_row(connection, row, source_file_name)
        if prepared_row is None:
            continue

        prepared_rows.append(prepared_row)
        valid_rows += 1

    return prepared_rows, reject_reasons, valid_rows
