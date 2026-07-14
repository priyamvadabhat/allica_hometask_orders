"""Main ETL orchestration for loading order CSV files into the SQLite warehouse."""

# Optional email notifications:
# The ETL pipeline will work normally without SMTP setup.
# If SMTP_HOST is configured in the environment, notifications will be sent.
import csv
import hashlib
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .db import create_schema, get_connection
from .loading import insert_fact_rows, prepare_fact_row, write_load_log
from .utils import configure_logging, logger
from .validation import validate_row


class OrdersPipeline:
    def __init__(self, connection: Any) -> None:
        # Hold the SQLite connection for all database work in this pipeline run.
        self.connection = connection

    def run(self, input_dir: str | Path, force_reprocess: list[str] | None = None) -> dict[str, int]:
        # Convert the input path to a Path object and look for CSV files to process.
        input_path = Path(input_dir)
        files = discover_files(input_path)
        if not files:
            logger.warning("No CSV files found")
            return {"rows_loaded": 0, "rows_rejected": 0}

        # Track totals for the whole run.
        rows_loaded = 0
        rows_rejected = 0
        force_set = set(force_reprocess or [])

        # Process every CSV file found in the input folder.
        for file_path in files:
            # Create a fingerprint for the file so we can detect if it changed since last load.
            file_hash, modified_at = _get_file_fingerprint(file_path)
            skip_reason = self._should_skip_file(file_path.name, file_hash, modified_at, force_set)
            if skip_reason:
                # If the file is unchanged, record it as skipped and stop processing it.
                write_load_log(self.connection, file_path.name, file_hash, modified_at, 0, status="skipped", comment=skip_reason)
                self._notify_skipped_file(file_path.name, skip_reason)
                continue

            logger.info("Processing file %s", file_path.name)
            batch_rows = []
            total_rows = 0
            reject_reasons: list[str] = []
            with file_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    total_rows += 1
                    valid, issues = validate_row(row)
                    if not valid:
                        # Reject rows that fail validation and count them in the summary.
                        rows_rejected += 1
                        reject_reasons.append("; ".join(issues))
                        logger.warning("Rejected row in %s: %s", file_path.name, "; ".join(issues))
                        continue

                    # Prepare a row for insertion into the fact table.
                    prepared_row = prepare_fact_row(self.connection, row, file_path.name)
                    if prepared_row is None:
                        # This can happen when the same order appears twice in the file.
                        continue
                    batch_rows.append(prepared_row)

            if batch_rows:
                # Load all prepared rows in one batch for efficiency.
                insert_fact_rows(self.connection, batch_rows)
                rows_loaded += len(batch_rows)

            # Record the file in the load log even if it was skipped or had zero rows.
            write_load_log(self.connection, file_path.name, file_hash, modified_at, len(batch_rows))
            # Move the file to the archive directory after it has been processed.
            self._archive_processed_file(file_path, input_path)
            self._notify_processed_file(
                file_path.name,
                total_rows,
                len(batch_rows),
                len(reject_reasons),
                reject_reasons,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )

        return {"rows_loaded": rows_loaded, "rows_rejected": rows_rejected}

    def _should_skip_file(self, source_file_name: str, file_hash: str, modified_at: str, force_set: set[str]) -> str | None:
        # If the file name was explicitly requested for reprocessing, do not skip it.
        if source_file_name in force_set:
            return None

        # Check if we already loaded this file with the same fingerprint.
        existing_file = self.connection.execute(
            "SELECT file_hash, modified_at FROM load_log WHERE source_file_name = ? AND status = 'loaded'",
            (source_file_name,),
        ).fetchone()
        if existing_file and existing_file["file_hash"] == file_hash and existing_file["modified_at"] == modified_at:
            logger.info("Skipping unchanged file %s", source_file_name)
            return "File skipped because it had the same data as a previously loaded file."
        return None

    def _archive_processed_file(self, file_path: Path, input_dir: Path) -> None:
        # Move the processed CSV into an archive folder so it is not re-processed again.
        archive_dir = input_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target_path = archive_dir / file_path.name
        if target_path.exists():
            target_path.unlink()
        file_path.replace(target_path)
        logger.info("Archived processed file %s to %s", file_path.name, target_path)

    def _notify_skipped_file(self, source_file_name: str, reason: str) -> None:
        # Send a short notification when a file is skipped due to being unchanged.
        self._send_notification(
            subject="Skipped file notification",
            body=f"Skipped file: {source_file_name}\nReason: {reason}",
            recipient=os.getenv("NOTIFICATION_EMAIL", "bhatpriyamvada@gmail.com"),
        )

    def _notify_processed_file(
        self,
        source_file_name: str,
        total_rows: int,
        loaded_rows: int,
        rejected_rows: int,
        reject_reasons: list[str],
        executed_at: str,
    ) -> None:
        # Build a human-readable summary for the processed file.
        body = (
            f"Processed file: {source_file_name}\n"
            f"Execution date: {executed_at}\n"
            f"Total rows in file: {total_rows}\n"
            f"Rows loaded: {loaded_rows}\n"
            f"Rows rejected: {rejected_rows}\n"
        )
        if reject_reasons:
            body += "Reject reasons:\n" + "\n".join(f"- {reason}" for reason in reject_reasons)
        else:
            body += "Reject reasons: None"

        self._send_notification(
            subject="Processed file notification",
            body=body,
            recipient=os.getenv("NOTIFICATION_EMAIL", "bhatpriyamvada@gmail.com"),
        )

    def _send_notification(self, subject: str, body: str, recipient: str) -> None:
        # Email notifications are optional and only run when SMTP settings are configured.
        # If no SMTP host is set, the code logs the message instead of failing.
        host = os.getenv("SMTP_HOST")
        if host:
            try:
                smtp = smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "25")))
                if os.getenv("SMTP_USER"):
                    smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
                email = EmailMessage()
                email["Subject"] = subject
                email["From"] = os.getenv("SMTP_FROM", "noreply@example.com")
                email["To"] = recipient
                email.set_content(body)
                smtp.send_message(email)
                smtp.quit()
                logger.info("Notification email sent to %s", recipient)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unable to send email notification to %s: %s", recipient, exc)
        else:
            logger.info("SMTP not configured; notification logged for %s", recipient)
        logger.info(body)


def discover_files(input_dir: str | Path) -> list[Path]:
    # Return all CSV files in the input directory in a stable sorted order.
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    return sorted(input_path.glob("*.csv"))



def _get_file_fingerprint(file_path: Path) -> tuple[str, str]:
    # Build a simple fingerprint for the file using its content hash and modification time.
    modified_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sha256 = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest(), modified_at


def run_pipeline(
    input_dir: str | Path,
    db_path: str | Path,
    log_file: str | Path | None = None,
    force_reprocess: list[str] | None = None,
) -> dict[str, int]:
    # Initialize logging, create the database directory if needed, and then run the ETL flow.
    configure_logging(log_file)
    input_path = Path(input_dir)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = get_connection(db_path)
    create_schema(connection)

    pipeline = OrdersPipeline(connection)
    result = pipeline.run(input_path, force_reprocess=force_reprocess)
    connection.close()
    return result
