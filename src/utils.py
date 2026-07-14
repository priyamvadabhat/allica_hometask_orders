"""Shared utility functions for logging, parsing, cleaning, and environment loading."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger("orders_etl")


def load_environment_file(env_file: str | Path | None = None) -> None:
    # Read settings from a .env file if one is present so the pipeline can use SMTP and notification config.
    candidates: list[Path] = []
    if env_file is not None:
        candidates.append(Path(env_file))

    candidates.extend(
        [
            Path.cwd() / ".env",
            Path(__file__).resolve().parent.parent / ".env",
        ]
    )

    for candidate in candidates:
        if not candidate.exists():
            continue

        with candidate.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if value and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]

                os.environ.setdefault(key, value)
        break


def build_log_file_path(log_file: str | Path | None, timestamp: datetime | None = None) -> Path | None:
    # Create a timestamped log file name when the pipeline starts so each run has its own log.
    if not log_file:
        return None

    path = Path(log_file)
    if timestamp is None:
        timestamp = datetime.now()

    if path.suffix:
        stem = path.stem
        suffix = path.suffix
        return path.with_name(f"{stem}_{timestamp.strftime('%Y%m%d_%H%M%S')}{suffix}")

    return path.with_name(f"{path.name}_{timestamp.strftime('%Y%m%d_%H%M%S')}")


def configure_logging(log_file: Path | None = None) -> None:
    # Configure console logging and optionally write the same records to a file.
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    resolved_log_file = build_log_file_path(log_file) if log_file is not None else None
    if resolved_log_file:
        resolved_log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(resolved_log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def clean_text(value: Any) -> str:
    # Normalize text by removing extra whitespace and trimming edges.
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def parse_date(value: Any) -> str | None:
    # Convert common date formats into a YYYY-MM-DD string.
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_decimal(value: Any) -> float | None:
    # Convert numeric-looking values into floats, returning None for invalid input.
    if value is None:
        return None
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
