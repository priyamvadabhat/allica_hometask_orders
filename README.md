# Orders Data Warehouse

This project builds a small analytical warehouse in SQLite from CSV order files.

## Tables and fields
| Table | Fields |
|---|---|
| `dim_client` | `client_id`, `client_name`, `delivery_address`, `delivery_city`, `delivery_postcode`, `delivery_country`, `delivery_contact_number`, `effective_from`, `effective_to`, `is_current` |
| `dim_product` | `product_id`, `product_name`, `product_type`, `unit_price`, `effective_from`, `effective_to`, `is_current` |
| `dim_payment` | `payment_id`, `payment_type`, `payment_billing_code`, `effective_from`, `effective_to`, `is_current` |
| `fact_orders` | `order_line_id`, `order_number`, `client_id`, `product_id`, `payment_id`, `order_date`, `currency`, `quantity`, `unit_price`, `total_price`, `source_file_name`, `load_timestamp` |
| `load_log` | `load_id`, `source_file_name`, `loaded_at`, `row_count`, `status`, `file_hash`, `modified_at`, `comment` |

## Features covered
- Reads CSV files from an input folder
- Extracts raw data through a dedicated extraction layer
- Validates and cleans incoming rows in a transformation layer
- Loads data into a star-schema style warehouse with dimensions and a fact table via a dedicated loading layer
- Normalizes whitespace and special characters in names and addresses
- Removes duplicate orders and prevents repeated loads of the same file
- Tracks processed files using file hashes and modification times
- Archives successfully processed files into an archive folder
- Writes timestamped pipeline logs
- Validates the warehouse schema before and after loading
- Sends optional email notifications when SMTP settings are configured

## Test coverage
- Happy-path load into the warehouse
- Validation of invalid rows
- Normalization of whitespace and special characters
- Multi-file processing
- Idempotency on rerun
- Existing schema migration for the load log table
- Schema validation for required warehouse tables and columns
- Environment loading from .env
- Archival of processed files
- Normalization of client_name and delivery_country
- SCD type 2 logic - tested by adding a new row to the csv file, modifying a new row to the csv file.

## Input and output locations
- Input folder: `data/raw`
- Archived files: `data/raw/archive`
- SQLite database: `data/orders_warehouse.db`
- Pipeline logs: `data/pipeline_YYYYMMDD_HHMMSS.log`
 - Raw backup files (pre-transform): `data/raw/backups/{source_file_name}_{timestamp}/` containing CSVs:
   - `{source_file_name}_raw_dim_client.csv`
   - `{source_file_name}_raw_dim_product.csv`
   - `{source_file_name}_raw_dim_payment.csv`
   - `{source_file_name}_raw_fact_orders.csv`

## Project structure
- [src/extract.py](src/extract.py): file discovery, hashing, and CSV row extraction
- [src/transform.py](src/transform.py): validation and row preparation for warehouse loading
- [src/loading.py](src/loading.py): dimension lookup/create logic, fact inserts, and load-log updates
- [src/etl.py](src/etl.py): orchestration of the extract/transform/load workflow
- [src/pipeline.py](src/pipeline.py): public entrypoint for running the pipeline
- [tests/test_schema_validation.py](tests/test_schema_validation.py): unit tests for warehouse schema validation

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

## SCD handling
This project currently implements a simple Type 2-style approach for dimension updates:
- When a dimension attribute changes, a new dimension row is created instead of overwriting the existing value.
- The warehouse preserves historical context by keeping the prior version of the dimension record intact.

Transformations, normalizations and deduplication are applied in `src/transform.py` before loading. Raw incoming data is backed up into CSVs under `data/raw/backups/` so the pre-transform state is preserved.

## Expected behavior
- Valid rows are loaded into the warehouse tables
- Invalid rows are rejected and counted in the run summary
- Re-running the pipeline with the same unchanged file will not duplicate data
- Successfully processed files are moved to the archive folder
- The warehouse schema is validated to ensure the expected tables and columns exist
- If SMTP is not configured, the pipeline continues normally and logs the notification attempt instead of failing
- If SMTP is configured, notification emails are sent for processed or skipped files


Improvisations which can be done:
Logs in a different folder. 
Improvisations in logging - such as when the code executes, the display text is not consistent enough.
Columns are hard coded in many places - consider centralizing it or having a metadata file.
Archival of data in different folder.
Backup of data before transformation can be in different folder. 
Casing and spelling variations can appear to other fields, which can be taken into consideration. Ideally, this should be checked back with source team if it can be made consistent. 
Compress raw file backups and archives.