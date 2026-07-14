"""
Loading: upserts cleaned data into the star schema, using Python's built-in
`sqlite3` module with parameterised SQL (never string-formatted values).

- dim_customer / dim_product use Slowly Changing Dimension Type 2: when a
  customer's or product's attributes differ from the currently-active
  version, the old version is closed out (valid_to / is_current) and a new
  version is inserted, so history is preserved instead of overwritten.
- dim_date is a simple "insert if not already present" dimension.
- fact_order_lines is loaded with an idempotent upsert keyed on
  order_line_id (SQLite's native `ON CONFLICT ... DO UPDATE`), so re-running
  the pipeline on the same file, or a corrected version of it, never creates
  duplicate facts.
"""
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from .clean import pick_canonical_name
from .transform import build_date_rows

CUSTOMER_ATTR_COLS = ["client_name", "address", "city", "postcode", "country", "contact_number"]


def _fetch_current_versions(conn: sqlite3.Connection, table: str, natural_key_col: str) -> dict:
    rows = conn.execute(f"SELECT * FROM {table} WHERE is_current = 1").fetchall()
    return {row[natural_key_col]: dict(row) for row in rows}


def upsert_customers(conn: sqlite3.Connection, clean_df: pd.DataFrame, warnings: list) -> dict:
    """SCD2 upsert of dim_customer. Returns {customer_id: customer_key}."""
    key_map = {}
    current_versions = _fetch_current_versions(conn, "dim_customer", "customer_id")

    for customer_id, group in clean_df.groupby("customer_id"):
        latest_row = group.loc[group["payment_date"].idxmax()]
        new_attrs = {
            "client_name": pick_canonical_name(group["client_name_raw"].tolist()),
            "address": latest_row["delivery_address"],
            "city": latest_row["delivery_city"],
            "postcode": latest_row["delivery_postcode"],
            "country": latest_row["delivery_country"],
            "contact_number": latest_row["delivery_contact_number"],
        }
        earliest_date = group["payment_date"].min()
        latest_date = group["payment_date"].max()

        existing = current_versions.get(customer_id)

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO dim_customer
                    (customer_id, client_name, address, city, postcode, country,
                     contact_number, valid_from, valid_to, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)
                """,
                (
                    customer_id,
                    new_attrs["client_name"],
                    new_attrs["address"],
                    new_attrs["city"],
                    new_attrs["postcode"],
                    new_attrs["country"],
                    new_attrs["contact_number"],
                    earliest_date.isoformat(),
                ),
            )
            key_map[customer_id] = cur.lastrowid
            continue

        unchanged = all(existing[col] == new_attrs[col] for col in CUSTOMER_ATTR_COLS)
        if unchanged:
            key_map[customer_id] = existing["customer_key"]
            continue

        existing_valid_from = datetime.fromisoformat(existing["valid_from"]).date()
        if latest_date <= existing_valid_from:
            warnings.append(
                f"Customer '{customer_id}': received an earlier-dated change "
                f"({latest_date}) than the current version ({existing_valid_from}); "
                "skipped SCD versioning to avoid corrupting history."
            )
            key_map[customer_id] = existing["customer_key"]
            continue

        conn.execute(
            "UPDATE dim_customer SET valid_to = ?, is_current = 0 WHERE customer_key = ?",
            ((latest_date - timedelta(days=1)).isoformat(), existing["customer_key"]),
        )
        cur = conn.execute(
            """
            INSERT INTO dim_customer
                (customer_id, client_name, address, city, postcode, country,
                 contact_number, valid_from, valid_to, is_current)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)
            """,
            (
                customer_id,
                new_attrs["client_name"],
                new_attrs["address"],
                new_attrs["city"],
                new_attrs["postcode"],
                new_attrs["country"],
                new_attrs["contact_number"],
                latest_date.isoformat(),
            ),
        )
        key_map[customer_id] = cur.lastrowid

    conn.commit()
    return key_map


def upsert_products(conn: sqlite3.Connection, clean_df: pd.DataFrame, warnings: list) -> dict:
    """SCD2 upsert of dim_product. Returns {product_id: product_key}."""
    key_map = {}
    current_versions = _fetch_current_versions(conn, "dim_product", "product_id")

    for product_id, group in clean_df.groupby("product_id"):
        latest_row = group.loc[group["payment_date"].idxmax()]
        new_attrs = {
            "product_name": latest_row["product_name"],
            "product_type": latest_row["product_type"],
            "unit_price": float(latest_row["unit_price"]),
        }
        earliest_date = group["payment_date"].min()
        latest_date = group["payment_date"].max()

        existing = current_versions.get(product_id)

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO dim_product
                    (product_id, product_name, product_type, unit_price,
                     valid_from, valid_to, is_current)
                VALUES (?, ?, ?, ?, ?, NULL, 1)
                """,
                (
                    product_id,
                    new_attrs["product_name"],
                    new_attrs["product_type"],
                    new_attrs["unit_price"],
                    earliest_date.isoformat(),
                ),
            )
            key_map[product_id] = cur.lastrowid
            continue

        unchanged = float(existing["unit_price"]) == new_attrs["unit_price"]
        if unchanged:
            key_map[product_id] = existing["product_key"]
            continue

        existing_valid_from = datetime.fromisoformat(existing["valid_from"]).date()
        if latest_date <= existing_valid_from:
            warnings.append(
                f"Product '{product_id}': received an earlier-dated price change "
                f"({latest_date}) than the current version ({existing_valid_from}); "
                "skipped SCD versioning to avoid corrupting history."
            )
            key_map[product_id] = existing["product_key"]
            continue

        conn.execute(
            "UPDATE dim_product SET valid_to = ?, is_current = 0 WHERE product_key = ?",
            ((latest_date - timedelta(days=1)).isoformat(), existing["product_key"]),
        )
        cur = conn.execute(
            """
            INSERT INTO dim_product
                (product_id, product_name, product_type, unit_price,
                 valid_from, valid_to, is_current)
            VALUES (?, ?, ?, ?, ?, NULL, 1)
            """,
            (
                product_id,
                new_attrs["product_name"],
                new_attrs["product_type"],
                new_attrs["unit_price"],
                latest_date.isoformat(),
            ),
        )
        key_map[product_id] = cur.lastrowid

    conn.commit()
    return key_map


def upsert_dates(conn: sqlite3.Connection, clean_df: pd.DataFrame) -> dict:
    """Insert any dates not already present in dim_date. Returns {date: date_key}."""
    rows = build_date_rows(clean_df["payment_date"].tolist())
    if not rows:
        return {}

    conn.executemany(
        """
        INSERT INTO dim_date
            (date_key, full_date, year, quarter, month, month_name,
             day, day_of_week, day_name, is_weekend)
        VALUES (:date_key, :full_date, :year, :quarter, :month, :month_name,
                :day, :day_of_week, :day_name, :is_weekend)
        ON CONFLICT(date_key) DO NOTHING
        """,
        [{**r, "full_date": r["full_date"].isoformat()} for r in rows],
    )
    conn.commit()
    return {row["full_date"]: row["date_key"] for row in rows}


def load_facts(
    conn: sqlite3.Connection,
    clean_df: pd.DataFrame,
    customer_map: dict,
    product_map: dict,
    date_map: dict,
) -> int:
    """Upsert fact rows keyed on order_line_id. Returns the number of rows loaded."""
    if clean_df.empty:
        return 0

    now = datetime.utcnow().isoformat()
    records = []
    for row in clean_df.itertuples(index=False):
        records.append(
            {
                "order_line_id": row.order_line_id,
                "order_id": row.order_id,
                "line_number": row.line_number,
                "customer_key": customer_map[row.customer_id],
                "product_key": product_map[row.product_id],
                "date_key": date_map[row.payment_date],
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "total_price": row.total_price,
                "currency": row.currency,
                "payment_type": row.payment_type,
                "payment_billing_code": row.payment_billing_code,
                "delivery_address": row.delivery_address,
                "delivery_city": row.delivery_city,
                "delivery_postcode": row.delivery_postcode,
                "delivery_country": row.delivery_country,
                "delivery_contact_number": row.delivery_contact_number,
                "loaded_at": now,
            }
        )

    conn.executemany(
        """
        INSERT INTO fact_order_lines
            (order_line_id, order_id, line_number, customer_key, product_key,
             date_key, quantity, unit_price, total_price, currency, payment_type,
             payment_billing_code, delivery_address, delivery_city,
             delivery_postcode, delivery_country, delivery_contact_number, loaded_at)
        VALUES
            (:order_line_id, :order_id, :line_number, :customer_key, :product_key,
             :date_key, :quantity, :unit_price, :total_price, :currency, :payment_type,
             :payment_billing_code, :delivery_address, :delivery_city,
             :delivery_postcode, :delivery_country, :delivery_contact_number, :loaded_at)
        ON CONFLICT(order_line_id) DO UPDATE SET
            order_id = excluded.order_id,
            line_number = excluded.line_number,
            customer_key = excluded.customer_key,
            product_key = excluded.product_key,
            date_key = excluded.date_key,
            quantity = excluded.quantity,
            unit_price = excluded.unit_price,
            total_price = excluded.total_price,
            currency = excluded.currency,
            payment_type = excluded.payment_type,
            payment_billing_code = excluded.payment_billing_code,
            delivery_address = excluded.delivery_address,
            delivery_city = excluded.delivery_city,
            delivery_postcode = excluded.delivery_postcode,
            delivery_country = excluded.delivery_country,
            delivery_contact_number = excluded.delivery_contact_number,
            loaded_at = excluded.loaded_at
        """,
        records,
    )
    conn.commit()
    return len(records)
