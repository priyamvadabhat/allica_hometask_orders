"""Main ETL orchestration for loading order CSV files into the SQLite warehouse."""
#Discovers the files, handles notifications and logging

# Optional email notifications:
# The ETL pipeline will work normally without SMTP setup.
# If SMTP_HOST is configured in the environment, notifications will be sent.

#Imports and setup
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .db import create_schema, get_connection
from .etl import ETLProcessor
from .utils import configure_logging, logger


class OrdersPipeline:
    def __init__(self, connection: Any) -> None:
        # Hold the SQLite connection for all database work in this pipeline run.
        self.connection = connection
        self.etl_processor = ETLProcessor(connection)

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
            file_hash, modified_at = self.etl_processor.get_file_fingerprint(file_path)
            skip_reason = self.etl_processor._should_skip_file(file_path.name, file_hash, modified_at, force_set)
            if skip_reason:
                # If the file is unchanged, record it as skipped and stop processing it.
                self.etl_processor.write_load_log(file_path.name, file_hash, modified_at, 0, status="skipped", comment=skip_reason)
                self._notify_skipped_file(file_path.name, skip_reason)
                continue

            loaded_rows, rejected_rows = self.etl_processor.process_file(file_path, input_path, force_set)
            rows_loaded += loaded_rows
            rows_rejected += rejected_rows
            self._notify_processed_file(
                file_path.name,
                self.etl_processor.last_total_rows,
                loaded_rows,
                rejected_rows,
                self.etl_processor.last_reject_reasons,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )

        return {"rows_loaded": rows_loaded, "rows_rejected": rows_rejected}

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
    from .extract import discover_files as extract_discover_files

    return extract_discover_files(input_dir)


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
