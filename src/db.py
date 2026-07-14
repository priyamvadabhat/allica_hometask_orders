"""Database schema creation and SQLite connection helpers for the warehouse."""

import sqlite3
from pathlib import Path

from .utils import logger


def create_schema(connection: sqlite3.Connection) -> None:
    # Create the warehouse tables if they do not already exist.
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS dim_client (
            client_id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL UNIQUE,
            delivery_address TEXT,
            delivery_city TEXT,
            delivery_postcode TEXT,
            delivery_country TEXT,
            delivery_contact_number TEXT
        );

        CREATE TABLE IF NOT EXISTS dim_product (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL UNIQUE,
            product_type TEXT,
            unit_price REAL
        );

        CREATE TABLE IF NOT EXISTS dim_payment (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_type TEXT NOT NULL UNIQUE,
            payment_billing_code TEXT
        );

        CREATE TABLE IF NOT EXISTS fact_orders (
            order_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL UNIQUE,
            client_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            payment_id INTEGER NOT NULL,
            order_date TEXT,
            currency TEXT,
            quantity INTEGER,
            unit_price REAL,
            total_price REAL,
            source_file_name TEXT,
            load_timestamp TEXT,
            FOREIGN KEY (client_id) REFERENCES dim_client(client_id),
            FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
            FOREIGN KEY (payment_id) REFERENCES dim_payment(payment_id)
        );

        CREATE TABLE IF NOT EXISTS load_log (
            load_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file_name TEXT NOT NULL UNIQUE,
            loaded_at TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            file_hash TEXT,
            modified_at TEXT,
            comment TEXT
        );
        """
    )

    # Older databases may not have the newer load_log columns, so add them if missing.
    try:
        connection.execute("SELECT file_hash FROM load_log LIMIT 1")
    except sqlite3.OperationalError:
        connection.execute("ALTER TABLE load_log ADD COLUMN file_hash TEXT")
        connection.execute("ALTER TABLE load_log ADD COLUMN modified_at TEXT")
        connection.execute("ALTER TABLE load_log ADD COLUMN comment TEXT")

    connection.commit()
    logger.info("Warehouse schema initialized")


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    # Open a SQLite connection and return rows as dictionary-like objects.
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection
