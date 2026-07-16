"""Helpers for preparing dimension rows, fact rows, and load-log entries."""

from datetime import datetime, timezone
from typing import Any
import sqlite3

from .utils import clean_text, logger, parse_date, parse_decimal


def get_or_create_dim(connection: Any, table: str, value_map: dict[str, Any]) -> int:
    # SCD Type 2 handling for dimensions.
    # - Business key lookup targets the current row (`is_current = 1`).
    # - If the current row exists and attributes are unchanged -> return existing surrogate id.
    # - If attributes changed -> mark existing row `is_current = 0` and set `effective_to`,
    #   then insert a new row with `effective_from` and `is_current = 1`.
    # - If no current row exists -> insert a new row with `effective_from` and `is_current = 1`.

    cursor = connection.cursor()
    now_ts = datetime.now(timezone.utc).isoformat()

    lookup_map = {
        "dim_client": ("client_id", "client_name"),
        "dim_product": ("product_id", "product_name"),
            "dim_payment": ("payment_id", ["payment_type", "payment_billing_code"]),
    }

    try:
        lookup_column, value_keys = lookup_map[table]
    except KeyError as exc:
        raise ValueError(f"Unsupported table {table}") from exc
    
    # Ensure value_keys is always a list
    if isinstance(value_keys, str):
        value_keys = [value_keys]


        # Build WHERE clause dynamically for one or more keys
    where_clause = " AND ".join([f"UPPER({key}) = ?" for key in value_keys])
    values = [str(value_map.get(key, "")).upper() for key in value_keys]

    # Prepare lookup value (transform.py should have normalized business keys where
    # required). Use the provided value_map business key directly for lookup.
    # Allow a caller to provide a pre-computed lookup variant (e.g. uppercased)
    # so that display values can be preserved while matching is case-insensitive.
    #lookup_value = value_map.get(f"{value_keys}_lookup") or value_map.get(value_keys, "") or ""
    # Use case-insensitive comparison for business keys so 'Acme' and 'ACME' match.
    cursor.execute(
        f"SELECT * FROM {table} WHERE {where_clause} AND is_current = 1 ORDER BY effective_from DESC",
        values,
    )
    existing_rows = cursor.fetchall()

    # If any existing row matches the incoming attributes under normalized
    # comparison rules, treat it as a duplicate and return its id (do not insert).
    for existing in existing_rows:
        match = True
        for col, new_val in value_map.items():
            old_val = existing[col]
            # Normalize None/empty string differences
            if old_val is None and (new_val is None or new_val == ""):
                continue

            if col in ("client_name", "delivery_country"):
                old_norm = str(old_val).strip().upper() if old_val is not None else ""
                new_norm = str(new_val).strip().upper() if new_val is not None else ""
                if col == "delivery_country":
                    if old_norm == "UK":
                        old_norm = "UNITED KINGDOM"
                    if new_norm == "UK":
                        new_norm = "UNITED KINGDOM"
                if old_norm != new_norm:
                    match = False
                    break

            elif isinstance(old_val, float) or isinstance(old_val, int):
                try:
                    if float(old_val) != float(new_val if new_val not in (None, "") else 0):
                        match = False
                        break
                except Exception:
                    if str(old_val) != str(new_val):
                        match = False
                        break
            else:
                if str(old_val) != str(new_val if new_val is not None else ""):
                    match = False
                    break

        if match:
            # Found an existing row that is equivalent under normalization —
            # treat as duplicate and reuse its id (do not create another version).
            return existing[lookup_column]

    # No equivalent existing row found. If there is a current row, expire it
    # and insert a new version; otherwise insert a first row.
    current_row = existing_rows[0] if existing_rows else None
    if current_row and current_row['is_current'] == 1:
        cursor.execute(
           f"UPDATE {table} SET is_current = 0, effective_to = ? WHERE {where_clause} AND {lookup_column} = ?",
        [now_ts] + values + [current_row[lookup_column]],
        )

    # Insert new current version (covers both no-existing and changed cases).
    # Remove any lookup-only keys before inserting into the table
    insert_map = {k: v for k, v in value_map.items() if not k.endswith("_lookup")}
    insert_columns = list(insert_map.keys()) + ["effective_from", "effective_to", "is_current"]
    placeholders = ", ".join(["?"] * len(insert_columns))
    columns = ", ".join(insert_columns)
    insert_values = list(insert_map.values()) + [now_ts, None, 1]

    try:
        cursor.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            insert_values,
        )
        connection.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # If a unique constraint prevents insert (e.g. order), try to find an existing
        # matching row by the business key and return its id.
        cursor.execute(
            f"SELECT {lookup_column} FROM {table} WHERE {where_clause} LIMIT 1",
            values,
        )
        found = cursor.fetchone()
        if found:
            return found[0]
        raise


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
            # Keep the stored client_name in original cleaned form so casing is
            # preserved for display, but the SCD lookup will be case-insensitive.
            "client_name": clean_text(row.get("ClientName")),
            "delivery_address": clean_text(row.get("DeliveryAddress")),
            "delivery_city": clean_text(row.get("DeliveryCity")),
            "delivery_postcode": clean_text(row.get("DeliveryPostcode")),
            # Keep the stored delivery_country in cleaned form; SCD lookup will
            # treat 'UK' the same as 'UNITED KINGDOM' and be case-insensitive.
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

#duplicate order check
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
