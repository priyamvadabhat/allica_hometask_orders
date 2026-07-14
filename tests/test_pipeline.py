"""Regression tests for the orders ETL pipeline."""

import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from src.pipeline import run_pipeline
from src.utils import build_log_file_path, load_environment_file


def write_csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "OrderNumber",
                "ClientName",
                "ProductName",
                "ProductType",
                "UnitPrice",
                "ProductQuantity",
                "TotalPrice",
                "Currency",
                "DeliveryAddress",
                "DeliveryCity",
                "DeliveryPostcode",
                "DeliveryCountry",
                "DeliveryContactNumber",
                "PaymentType",
                "PaymentBillingCode",
                "PaymentDate",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_pipeline_creates_database_and_loads_valid_rows(tmp_path):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    write_csv(
        input_dir / "orders_20240101.csv",
        [
            {
                "OrderNumber": "PO1",
                "ClientName": "Acme Ltd",
                "ProductName": "Piano",
                "ProductType": "Keyboard",
                "UnitPrice": "500",
                "ProductQuantity": "2",
                "TotalPrice": "1000",
                "Currency": "GBP",
                "DeliveryAddress": "1 Test Street",
                "DeliveryCity": "London",
                "DeliveryPostcode": "SW1A 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 20 0000 0000",
                "PaymentType": "Debit",
                "PaymentBillingCode": "PMT-001",
                "PaymentDate": "2024-01-01",
            },
            {
                "OrderNumber": "",
                "ClientName": "",
                "ProductName": "",
                "ProductType": "Keyboard",
                "UnitPrice": "x",
                "ProductQuantity": "2",
                "TotalPrice": "1000",
                "Currency": "GBP",
                "DeliveryAddress": "",
                "DeliveryCity": "London",
                "DeliveryPostcode": "",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "",
                "PaymentType": "Debit",
                "PaymentBillingCode": "",
                "PaymentDate": "bad-date",
            },
        ],
    )

    db_path = tmp_path / "warehouse.db"
    summary = run_pipeline(input_dir, db_path)

    assert summary["rows_loaded"] == 1
    assert summary["rows_rejected"] == 1
    assert db_path.exists()

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM dim_client").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM dim_product").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM dim_payment").fetchone()[0] == 1
    finally:
        connection.close()


def test_pipeline_normalises_whitespace_and_special_characters(tmp_path):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    write_csv(
        input_dir / "orders_20240102.csv",
        [
            {
                "OrderNumber": "PO2",
                "ClientName": "  Acme & Co  ",
                "ProductName": "  Grand Piano  ",
                "ProductType": " Keyboard ",
                "UnitPrice": "600",
                "ProductQuantity": "1",
                "TotalPrice": "600",
                "Currency": " GBP ",
                "DeliveryAddress": " 10 Main St. ",
                "DeliveryCity": " London ",
                "DeliveryPostcode": "SW1A 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 20 0000 0001",
                "PaymentType": " Credit ",
                "PaymentBillingCode": "PMT-002",
                "PaymentDate": "2024-02-01",
            }
        ],
    )

    db_path = tmp_path / "warehouse.db"
    run_pipeline(input_dir, db_path)

    connection = sqlite3.connect(db_path)
    try:
        client = connection.execute("SELECT client_name, delivery_city FROM dim_client").fetchone()
        assert client[0] == "Acme & Co"
        assert client[1] == "London"

        product = connection.execute("SELECT product_name, product_type FROM dim_product").fetchone()
        assert product[0] == "Grand Piano"
        assert product[1] == "Keyboard"

        payment = connection.execute("SELECT payment_type, payment_billing_code FROM dim_payment").fetchone()
        assert payment[0] == "Credit"
        assert payment[1] == "PMT-002"
    finally:
        connection.close()


def test_pipeline_processes_multiple_files(tmp_path):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    write_csv(
        input_dir / "orders_20240101.csv",
        [
            {
                "OrderNumber": "PO3",
                "ClientName": "Beta Ltd",
                "ProductName": "Flute",
                "ProductType": "Woodwind",
                "UnitPrice": "50",
                "ProductQuantity": "3",
                "TotalPrice": "150",
                "Currency": "GBP",
                "DeliveryAddress": "2 River Road",
                "DeliveryCity": "Manchester",
                "DeliveryPostcode": "M1 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 161 000 0000",
                "PaymentType": "Credit",
                "PaymentBillingCode": "PMT-003",
                "PaymentDate": "2024-01-03",
            }
        ],
    )
    write_csv(
        input_dir / "orders_20240102.csv",
        [
            {
                "OrderNumber": "PO4",
                "ClientName": "Gamma Ltd",
                "ProductName": "Drum",
                "ProductType": "Percussion",
                "UnitPrice": "80",
                "ProductQuantity": "2",
                "TotalPrice": "160",
                "Currency": "GBP",
                "DeliveryAddress": "3 Hill Lane",
                "DeliveryCity": "Birmingham",
                "DeliveryPostcode": "B1 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 121 000 0000",
                "PaymentType": "Debit",
                "PaymentBillingCode": "PMT-004",
                "PaymentDate": "2024-01-04",
            }
        ],
    )

    db_path = tmp_path / "warehouse.db"
    summary = run_pipeline(input_dir, db_path)

    assert summary["rows_loaded"] == 2
    assert summary["rows_rejected"] == 0

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM load_log").fetchone()[0] == 2
    finally:
        connection.close()


def test_pipeline_is_idempotent_on_rerun(tmp_path):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    write_csv(
        input_dir / "orders_20240101.csv",
        [
            {
                "OrderNumber": "PO5",
                "ClientName": "Delta Ltd",
                "ProductName": "Violin",
                "ProductType": "String",
                "UnitPrice": "300",
                "ProductQuantity": "1",
                "TotalPrice": "300",
                "Currency": "GBP",
                "DeliveryAddress": "4 Park Avenue",
                "DeliveryCity": "Leeds",
                "DeliveryPostcode": "LS1 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 113 000 0000",
                "PaymentType": "Credit",
                "PaymentBillingCode": "PMT-005",
                "PaymentDate": "2024-01-05",
            }
        ],
    )

    db_path = tmp_path / "warehouse.db"
    first_summary = run_pipeline(input_dir, db_path)
    second_summary = run_pipeline(input_dir, db_path)

    assert first_summary["rows_loaded"] == 1
    assert second_summary["rows_loaded"] == 0

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0] == 1
    finally:
        connection.close()


def test_build_log_file_path_adds_timestamp_suffix():
    timestamp = datetime(2024, 1, 2, 3, 4, 5)

    assert build_log_file_path("data/pipeline.log", timestamp=timestamp) == Path("data/pipeline_20240102_030405.log")


def test_load_environment_file_sets_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NOTIFICATION_EMAIL=test@example.com\nSMTP_HOST=smtp.example.com\n", encoding="utf-8")
    monkeypatch.delenv("NOTIFICATION_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    load_environment_file(env_file)

    assert os.getenv("NOTIFICATION_EMAIL") == "test@example.com"
    assert os.getenv("SMTP_HOST") == "smtp.example.com"


def test_pipeline_archives_processed_file(tmp_path):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    source_file = input_dir / "orders_20240101.csv"
    write_csv(
        source_file,
        [
            {
                "OrderNumber": "PO7",
                "ClientName": "Eta Ltd",
                "ProductName": "Cello",
                "ProductType": "String",
                "UnitPrice": "400",
                "ProductQuantity": "1",
                "TotalPrice": "400",
                "Currency": "GBP",
                "DeliveryAddress": "6 River Street",
                "DeliveryCity": "Bristol",
                "DeliveryPostcode": "BS1 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 117 000 0000",
                "PaymentType": "Debit",
                "PaymentBillingCode": "PMT-007",
                "PaymentDate": "2024-01-07",
            }
        ],
    )

    db_path = tmp_path / "warehouse.db"
    run_pipeline(input_dir, db_path)

    archived_file = input_dir / "archive" / "orders_20240101.csv"
    assert archived_file.exists()
    assert not source_file.exists()


def test_pipeline_upgrades_existing_load_log_schema(tmp_path):
    input_dir = tmp_path / "incoming"
    input_dir.mkdir()
    write_csv(
        input_dir / "orders_20240101.csv",
        [
            {
                "OrderNumber": "PO6",
                "ClientName": "Epsilon Ltd",
                "ProductName": "Cello",
                "ProductType": "String",
                "UnitPrice": "400",
                "ProductQuantity": "1",
                "TotalPrice": "400",
                "Currency": "GBP",
                "DeliveryAddress": "5 Garden Street",
                "DeliveryCity": "Edinburgh",
                "DeliveryPostcode": "EH1 1AA",
                "DeliveryCountry": "United Kingdom",
                "DeliveryContactNumber": "+44 131 000 0000",
                "PaymentType": "Debit",
                "PaymentBillingCode": "PMT-006",
                "PaymentDate": "2024-01-06",
            }
        ],
    )

    db_path = tmp_path / "warehouse.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE load_log (
                load_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file_name TEXT NOT NULL UNIQUE,
                loaded_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    summary = run_pipeline(input_dir, db_path)

    assert summary["rows_loaded"] == 1
    assert summary["rows_rejected"] == 0

    connection = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(load_log)")]
        assert "file_hash" in columns
        assert "modified_at" in columns
        assert "comment" in columns
    finally:
        connection.close()
