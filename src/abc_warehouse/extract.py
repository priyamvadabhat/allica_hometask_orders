"""
Extraction: read a raw orders file (CSV, or XLSX for convenience) into a
pandas DataFrame with every column as a string. Parsing/casting is deliberately
deferred to the cleaning step so that bad values (e.g. "abc" in a quantity
column) are caught and reported there rather than silently coerced by pandas
into NaN here.
"""
from pathlib import Path

import pandas as pd

from .config import EXPECTED_COLUMNS


class ExtractionError(Exception):
    """Raised when the input file cannot be read or is structurally invalid."""


def extract(file_path) -> pd.DataFrame:
    """Load a raw orders file and return it as a DataFrame of strings.

    Raises ExtractionError if the file is missing, unsupported, or missing
    required columns -- these are structural problems, distinct from the
    row-level data-quality problems handled in `clean.py`.
    """
    path = Path(file_path)
    if not path.exists():
        raise ExtractionError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(path, dtype=str, keep_default_na=False)
        else:
            raise ExtractionError(
                f"Unsupported file type '{suffix}'. Expected .csv, .xlsx or .xls."
            )
    except ExtractionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive: unreadable/corrupt file
        raise ExtractionError(f"Could not read '{path}': {exc}") from exc

    missing_columns = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ExtractionError(
            f"'{path.name}' is missing required column(s): {missing_columns}"
        )

    df = df.reset_index(drop=True)
    df["_source_file"] = path.name
    df["_source_row"] = df.index + 2  # +1 for header row, +1 for 1-indexing
    return df
