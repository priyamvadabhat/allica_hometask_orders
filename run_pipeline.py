#!/usr/bin/env python3
"""
Entry point for running the ETL pipeline from the project root.

    python run_pipeline.py
    python run_pipeline.py --input data/raw/orders_2023.csv
    python run_pipeline.py --input data/raw/*.csv --reset

Run `python run_pipeline.py --help` for all options.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from abc_warehouse.pipeline import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
