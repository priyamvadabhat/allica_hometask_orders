# Orders Data Warehouse

This project builds a small analytical warehouse in SQLite from CSV order files.

## Features covered
- Reads CSV files from an input folder
- Validates and cleans incoming rows
- Normalizes whitespace and special characters in names and addresses
- Removes duplicate orders and prevents repeated loads of the same file
- Loads data into a star-schema style warehouse with dimensions and a fact table
- Tracks processed files using file hashes and modification times
- Archives successfully processed files into an archive folder
- Writes timestamped pipeline logs
- Sends optional email notifications when SMTP settings are configured

## Test coverage
- Happy-path load into the warehouse
- Validation of invalid rows
- Normalization of whitespace and special characters
- Multi-file processing
- Idempotency on rerun
- Existing schema migration for the load log table
- Environment loading from .env
- Archival of processed files

## Input and output locations
- Input folder: `data/raw`
- Archived files: `data/raw/archive`
- SQLite database: `data/orders_warehouse.db`
- Pipeline logs: `data/pipeline_YYYYMMDD_HHMMSS.log`

## Setup
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
- Create a local environment file for optional email notifications:
  ```bash
  cp .env.example .env
  ```
- Update the values in `.env` as needed for SMTP and notification settings.

## How to run the pipeline
- Run with the default settings:
  ```bash
  python run_pipeline.py
  ```
- Run against a custom input folder and database path:
  ```bash
  python run_pipeline.py --input-dir data/raw --db-path data/orders_warehouse.db
  ```
- Force reprocessing of a specific file name:
  ```bash
  python run_pipeline.py --force-reprocess orders_2023.csv
  ```

## Expected behavior
- Valid rows are loaded into the warehouse tables
- Invalid rows are rejected and counted in the run summary
- Re-running the pipeline with the same unchanged file will not duplicate data
- Successfully processed files are moved to the archive folder
- If SMTP is not configured, the pipeline continues normally and logs the notification attempt instead of failing
- If SMTP is configured, notification emails are sent for processed or skipped files
