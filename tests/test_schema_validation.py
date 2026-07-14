import sqlite3

import pytest

from src.db import create_schema, validate_schema


def test_validate_schema_accepts_expected_tables_and_columns(tmp_path):
    db_path = tmp_path / "warehouse.db"
    connection = sqlite3.connect(db_path)
    try:
        create_schema(connection)
        validate_schema(connection)
    finally:
        connection.close()


def test_validate_schema_rejects_missing_columns(tmp_path):
    db_path = tmp_path / "warehouse.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE dim_client (
                client_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE dim_product (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE dim_payment (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_type TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE fact_orders (
                order_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL,
                client_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                payment_id INTEGER NOT NULL
            )
            """
        )
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

        with pytest.raises(ValueError, match="Missing columns"):
            validate_schema(connection)
    finally:
        connection.close()
