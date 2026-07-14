"""
End-to-end pipeline orchestration: extract -> clean -> load, plus a CLI.

Usage (see README.md for full details):

    python run_pipeline.py
    python run_pipeline.py --input data/raw/orders_2023.csv
    python run_pipeline.py --input file1.csv file2.csv --reset
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .clean import clean_orders
from .config import DEFAULT_DB_PATH, DEFAULT_INPUT_PATH, REJECTS_DIR
from .extract import ExtractionError, extract
from .load import load_facts, upsert_customers, upsert_dates, upsert_products
from .schema import create_all, drop_all, get_connection


def _write_rejects(rejects_df: pd.DataFrame, source_file: str) -> Path:
    REJECTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(source_file).stem
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = REJECTS_DIR / f"{stem}_rejects_{timestamp}.csv"
    rejects_df.to_csv(out_path, index=False)
    return out_path


def run_pipeline(input_paths, db_path=DEFAULT_DB_PATH, reset: bool = False) -> list:
    """Run the full ETL pipeline for one or more input files.

    Returns a list of per-file summary dicts, useful for tests and for the
    CLI's printed output. A problem in one file (bad rows, or the whole file
    failing to parse) does not stop the other files from being processed.
    """
    conn = get_connection(db_path)
    try:
        if reset:
            drop_all(conn)
        create_all(conn)

        summaries = []
        for input_path in input_paths:
            summary = {"file": str(input_path)}
            try:
                raw_df = extract(input_path)
            except ExtractionError as exc:
                summary["status"] = "failed"
                summary["error"] = str(exc)
                summaries.append(summary)
                print(f"[FAILED] {input_path}: {exc}")
                continue

            clean_df, rejects_df = clean_orders(raw_df)

            summary["rows_read"] = len(raw_df)
            summary["rows_valid"] = len(clean_df)
            summary["rows_rejected"] = len(rejects_df)

            if not rejects_df.empty:
                rejects_path = _write_rejects(rejects_df, Path(input_path).name)
                summary["rejects_file"] = str(rejects_path)
                print(
                    f"[WARNING] {input_path}: {len(rejects_df)} row(s) rejected, "
                    f"details written to {rejects_path}"
                )

            if clean_df.empty:
                summary["status"] = "no_valid_rows"
                summaries.append(summary)
                print(f"[SKIPPED] {input_path}: no valid rows to load")
                continue

            warnings = []
            customer_map = upsert_customers(conn, clean_df, warnings)
            product_map = upsert_products(conn, clean_df, warnings)
            date_map = upsert_dates(conn, clean_df)
            rows_loaded = load_facts(conn, clean_df, customer_map, product_map, date_map)

            for w in warnings:
                print(f"[WARNING] {input_path}: {w}")

            summary["status"] = "success"
            summary["rows_loaded"] = rows_loaded
            summaries.append(summary)
            print(
                f"[OK] {input_path}: {rows_loaded} row(s) loaded "
                f"({len(rejects_df)} rejected out of {len(raw_df)} read)"
            )

        return summaries
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Load ABC Musical Instruments order data into the SQLite warehouse."
    )
    parser.add_argument(
        "--input",
        nargs="+",
        default=[str(DEFAULT_INPUT_PATH)],
        help="One or more CSV/XLSX files to load (default: data/raw/orders_2023.csv)",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file (default: warehouse.db)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate all tables before loading (full rebuild).",
    )
    args = parser.parse_args(argv)

    summaries = run_pipeline(args.input, db_path=args.db, reset=args.reset)
    failed = [s for s in summaries if s.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
