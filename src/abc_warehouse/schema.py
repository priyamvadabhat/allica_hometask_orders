"""
Star-schema DDL for the ABC Musical Instruments analytical warehouse, using
Python's built-in `sqlite3` module.

    dim_customer         -- SCD Type 2: one row per customer *version*
    dim_product          -- SCD Type 2: one row per product *version*
    dim_date              -- standard date dimension
    fact_order_lines      -- one row per order line (the grain of the fact table)

All DDL uses CREATE TABLE IF NOT EXISTS, so `create_all` is idempotent: safe
to run against a brand-new (or freshly-deleted) database file, and a no-op
against one that already has the tables. That idempotency is what makes the
pipeline resilient to the database file being deleted and the code rerun.
"""
import sqlite3
from pathlib import Path

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS dim_customer (
        customer_key     INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id       TEXT    NOT NULL,
        client_name       TEXT    NOT NULL,
        address           TEXT,
        city              TEXT,
        postcode          TEXT,
        country           TEXT,
        contact_number    TEXT,
        valid_from        DATE    NOT NULL,
        valid_to          DATE,
        is_current        BOOLEAN NOT NULL DEFAULT 1,
        UNIQUE (customer_id, valid_from)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_product (
        product_key       INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id        TEXT    NOT NULL,
        product_name      TEXT    NOT NULL,
        product_type      TEXT    NOT NULL,
        unit_price        NUMERIC NOT NULL,
        valid_from        DATE    NOT NULL,
        valid_to          DATE,
        is_current        BOOLEAN NOT NULL DEFAULT 1,
        UNIQUE (product_id, valid_from)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_date (
        date_key          INTEGER PRIMARY KEY,
        full_date         DATE    NOT NULL UNIQUE,
        year              INTEGER NOT NULL,
        quarter           INTEGER NOT NULL,
        month             INTEGER NOT NULL,
        month_name        TEXT    NOT NULL,
        day               INTEGER NOT NULL,
        day_of_week       INTEGER NOT NULL,
        day_name          TEXT    NOT NULL,
        is_weekend        BOOLEAN NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_order_lines (
        order_line_key           INTEGER PRIMARY KEY AUTOINCREMENT,
        order_line_id            TEXT    NOT NULL UNIQUE,
        order_id                 TEXT    NOT NULL,
        line_number              INTEGER NOT NULL,
        customer_key             INTEGER NOT NULL REFERENCES dim_customer(customer_key),
        product_key              INTEGER NOT NULL REFERENCES dim_product(product_key),
        date_key                 INTEGER NOT NULL REFERENCES dim_date(date_key),
        quantity                 INTEGER NOT NULL,
        unit_price               NUMERIC NOT NULL,
        total_price              NUMERIC NOT NULL,
        currency                 TEXT    NOT NULL,
        payment_type             TEXT,
        payment_billing_code     TEXT,
        delivery_address         TEXT,
        delivery_city            TEXT,
        delivery_postcode        TEXT,
        delivery_country         TEXT,
        delivery_contact_number  TEXT,
        loaded_at                TIMESTAMP NOT NULL
    );
    """,
]

DROP_STATEMENTS = [
    "DROP TABLE IF EXISTS fact_order_lines;",
    "DROP TABLE IF EXISTS dim_date;",
    "DROP TABLE IF EXISTS dim_product;",
    "DROP TABLE IF EXISTS dim_customer;",
]


def get_connection(db_path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement switched on."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def create_all(conn: sqlite3.Connection) -> None:
    """Create every table that doesn't already exist. Safe to call repeatedly."""
    for statement in DDL_STATEMENTS:
        conn.execute(statement)
    conn.commit()


def drop_all(conn: sqlite3.Connection) -> None:
    """Drop every table. Used only when a full schema rebuild is requested."""
    for statement in DROP_STATEMENTS:
        conn.execute(statement)
    conn.commit()
