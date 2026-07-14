"""Extraction helpers for discovering and reading raw order CSV files."""

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .utils import logger
import pandas as pd

def convert_xlsx_to_csv(input_dir: Path) -> None:
    """
    Convert all .xlsx files in the input directory to .csv files.
    The converted CSVs will be saved in the same folder.
    """
    for xlsx_file in input_dir.glob("*.xlsx"):
        csv_file = xlsx_file.with_suffix(".csv")
        try:
            df = pd.read_excel(xlsx_file)
            df.to_csv(csv_file, index=False)
            logger.info("Converted %s -> %s", xlsx_file.name, csv_file.name)
        except Exception as e:
            logger.error("Failed to convert %s: %s", xlsx_file.name, e)



def discover_files(input_dir: str | Path) -> list[Path]:
    """Return all CSV files in the input directory in a stable sorted order."""
    input_path = Path(input_dir)

    # Safety check first
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")

    # Convert any Excel files to CSV before listing
    convert_xlsx_to_csv(input_path)

    # Return all CSV files sorted
    return sorted(input_path.glob("*.csv"))


def get_file_fingerprint(file_path: Path) -> tuple[str, str]:
    """Build a simple fingerprint for the file using its content hash and modification time."""
    modified_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sha256 = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest(), modified_at


def extract_rows(file_path: Path) -> list[dict[str, Any]]:
    """Read all rows from a CSV source file into memory for processing."""
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
