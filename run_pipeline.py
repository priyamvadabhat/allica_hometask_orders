import argparse
from pathlib import Path

from src.pipeline import run_pipeline
from src.utils import load_environment_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the orders ETL pipeline")
    parser.add_argument("--input-dir", default="data/raw")
    parser.add_argument("--db-path", default="data/orders_warehouse.db")
    parser.add_argument("--log-file", default="data/pipeline.log")
    parser.add_argument("--force-reprocess", nargs="*", default=[], help="Specific file names to reprocess even if unchanged")
    args = parser.parse_args()

    load_environment_file()

    input_dir = Path(args.input_dir)
    db_path = Path(args.db_path)
    log_file = Path(args.log_file)
    summary = run_pipeline(input_dir, db_path, log_file, force_reprocess=args.force_reprocess)
    print(summary)
