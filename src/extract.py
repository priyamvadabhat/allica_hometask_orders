"""Extraction helpers for discovering and reading raw order CSV files."""

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def discover_files(input_dir: str | Path) -> list[Path]:
    """Return all CSV files in the input directory in a stable sorted order."""
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
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
