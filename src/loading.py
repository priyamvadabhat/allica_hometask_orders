"""Helpers for preparing dimension rows, fact rows, and load-log entries."""

from datetime import datetime, timezone
from typing import Any

from .utils import clean_text, logger, parse_date, parse_decimal


def get_or_create_dim(connection: Any, table: str, value_map: dict[str, Any]) -> int:
    # Look up a dimension row by its business key. If it does not exist, create it.
    cursor = connection.cursor()
    columns = ", ".join(value_map.keys())
    placeholders = ", ".join(["?"] * len(value_map))

    lookup_map = {
        "dim_client": ("client_id", "client_name"),
        "dim_product": ("product_id", "product_name"),
        "dim_payment": ("payment_id", "payment_type"),
    }

    try:
        lookup_column, value_key = lookup_map[table]
    except KeyError as exc:
        raise ValueError(f"Unsupported table {table}") from exc

    cursor.execute(
        f"SELECT {lookup_column} FROM {table} WHERE {value_key} = ?",
        (value_map.get(value_key, ""),),
    )

    existing = cursor.fetchone()
    if existing:
        return existing[0]

    cursor.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        list(value_map.values()),
    )
    connection.commit()
    return cursor.lastrowid


def insert_fact_rows(connection: Any, batch_rows: list[tuple[Any, ...]]) -> None:
    # Insert the prepared fact rows into the orders fact table in one bulk operation.
    if not batch_rows:
        return
    connection.executemany(
        """
        INSERT INTO fact_orders (
            order_number, client_id, product_id, payment_id, order_date,
            currency, quantity, unit_price, total_price, source_file_name, load_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch_rows,
    )
    connection.commit()


def write_load_log(connection: Any, source_file_name: str, file_hash: str, modified_at: str, row_count: int, status: str = "loaded", comment: str | None = None) -> None:
    # Record whether a file was loaded or skipped, and keep the file fingerprint for repeat checks.
    existing_log = connection.execute(
        "SELECT 1 FROM load_log WHERE source_file_name = ?",
        (source_file_name,),
    ).fetchone()
    if existing_log:
        connection.execute(
            "UPDATE load_log SET loaded_at = ?, row_count = ?, status = ?, file_hash = ?, modified_at = ?, comment = ? WHERE source_file_name = ?",
            (
                "now",
                row_count,
                status,
                file_hash,
                modified_at,
                comment or "",
                source_file_name,
            ),
        )
    else:
        connection.execute(
            "INSERT INTO load_log (source_file_name, loaded_at, row_count, status, file_hash, modified_at, comment) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source_file_name,
                "now",
                row_count,
                status,
                file_hash,
                modified_at,
                comment or "",
            ),
        )
    connection.commit()


def prepare_fact_row(connection: Any, row: dict[str, Any], source_file_name: str) -> tuple[Any, ...] | None:
    # Turn one validated CSV row into a fact-row tuple using the dimension IDs.
    client_id = get_or_create_dim(
        connection,
        "dim_client",
        {
            "client_name": clean_text(row.get("ClientName")),
            "delivery_address": clean_text(row.get("DeliveryAddress")),
            "delivery_city": clean_text(row.get("DeliveryCity")),
            "delivery_postcode": clean_text(row.get("DeliveryPostcode")),
            "delivery_country": clean_text(row.get("DeliveryCountry")),
            "delivery_contact_number": clean_text(row.get("DeliveryContactNumber")),
        },
    )
    product_id = get_or_create_dim(
        connection,
        "dim_product",
        {
            "product_name": clean_text(row.get("ProductName")),
            "product_type": clean_text(row.get("ProductType")),
            "unit_price": parse_decimal(row.get("UnitPrice")),
        },
    )
    payment_id = get_or_create_dim(
        connection,
        "dim_payment",
        {
            "payment_type": clean_text(row.get("PaymentType")),
            "payment_billing_code": clean_text(row.get("PaymentBillingCode")),
        },
    )

    order_number = clean_text(row.get("OrderNumber"))
    existing_order = connection.execute(
        "SELECT 1 FROM fact_orders WHERE order_number = ?",
        (order_number,),
    ).fetchone()
    if existing_order:
        logger.info("Skipping duplicate order %s", order_number)
        return None

    return (
        order_number,
        client_id,
        product_id,
        payment_id,
        parse_date(row.get("PaymentDate")),
        clean_text(row.get("Currency")),
        int(parse_decimal(row.get("ProductQuantity")) or 0),
        parse_decimal(row.get("UnitPrice")),
        parse_decimal(row.get("TotalPrice")),
        source_file_name,
        "now",
    )
