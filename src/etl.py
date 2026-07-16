"""ETL orchestration helpers for the orders pipeline."""
#Implements ETL logic (extract,transform,load) for individual files

from pathlib import Path
from typing import Any

from .extract import discover_files, extract_rows, get_file_fingerprint
from .loading import insert_fact_rows, write_load_log
from .transform import transform_rows
from .utils import logger


class ETLProcessor:
    """Coordinate extract, transform, and load phases for each source file."""

#Store the DB connection and initializes counters for rows and rejection reasons.
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.last_total_rows = 0
        self.last_reject_reasons: list[str] = []

#compute file fingerprint, skip unchanged input files, extract, transform, insert valid rows, log, archive
    def process_file(self, file_path: Path, input_dir: Path, force_set: set[str]) -> tuple[int, int]:
        file_hash, modified_at = self.get_file_fingerprint(file_path)
        skip_reason = self._should_skip_file(file_path.name, file_hash, modified_at, force_set)
        if skip_reason:
            self.last_total_rows = 0
            self.last_reject_reasons = []
            self.write_load_log(file_path.name, file_hash, modified_at, 0, status="skipped", comment=skip_reason)
            return 0, 0

        logger.info("Processing file %s", file_path.name)
        rows = extract_rows(file_path) #rows are extracted from csv
        self.last_total_rows = len(rows)
        prepared_rows, reject_reasons, _ = transform_rows(self.connection, rows, file_path.name) #rows are transformed and validated
        self.last_reject_reasons = reject_reasons

        if prepared_rows: #if there are valid rows
            insert_fact_rows(self.connection, prepared_rows)

        self.write_load_log(file_path.name, file_hash, modified_at, len(prepared_rows))
        self._archive_processed_file(file_path, input_dir)
        return len(prepared_rows), len(reject_reasons)

#compute hash of file
    def get_file_fingerprint(self, file_path: Path) -> tuple[str, str]:
        return get_file_fingerprint(file_path)

#record metadata of file processed (name, hash, timestamp, row count, status)
    def write_load_log(
        self,
        source_file_name: str,
        file_hash: str,
        modified_at: str,
        row_count: int,
        status: str = "loaded",
        comment: str | None = None,
    ) -> None:
        write_load_log(self.connection, source_file_name, file_hash, modified_at, row_count, status=status, comment=comment)

#check db_log for same file. If yes, skip with reason, if not, process.
    def _should_skip_file(self, source_file_name: str, file_hash: str, modified_at: str, force_set: set[str]) -> str | None:
        if source_file_name in force_set:
            return None

        existing_file = self.connection.execute(
            "SELECT file_hash, modified_at FROM load_log WHERE source_file_name = ? AND status = 'loaded'",
            (source_file_name,),
        ).fetchone()
        if existing_file and existing_file["file_hash"] == file_hash and existing_file["modified_at"] == modified_at:
            logger.info("Skipping unchanged file %s", source_file_name)
            return "File skipped because it had the same data as a previously loaded file."
        return None

#move file to archive after successful load
    def _archive_processed_file(self, file_path: Path, input_dir: Path) -> None:
        archive_dir = input_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        target_path = archive_dir / file_path.name
        if target_path.exists():
            target_path.unlink()
        file_path.replace(target_path)
        logger.info("Archived processed file %s to %s", file_path.name, target_path)

#discover files, create an etlprocessor, loop through files, return summary. Basically, orchestrates multiple files in a directory, aggregates results
def run_etl(connection: Any, input_dir: str | Path, force_reprocess: list[str] | None = None) -> tuple[list[Path], int, int]:
    input_path = Path(input_dir)
    files = discover_files(input_path)
    if not files:
        logger.warning("No CSV files found")
        return [], 0, 0

    processor = ETLProcessor(connection)
    force_set = set(force_reprocess or [])
    rows_loaded = 0
    rows_rejected = 0

    for file_path in files:
        loaded_rows, rejected_rows = processor.process_file(file_path, input_path, force_set)
        rows_loaded += loaded_rows
        rows_rejected += rejected_rows

    return files, rows_loaded, rows_rejected
