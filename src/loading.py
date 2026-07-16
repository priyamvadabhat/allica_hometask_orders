"""Helpers for preparing dimension rows, fact rows, and load-log entries."""

from datetime import datetime, timezone
from typing import Any

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
        "dim_payment": ("payment_id", "payment_type"),
    }

    try:
        lookup_column, value_key = lookup_map[table]
    except KeyError as exc:
        raise ValueError(f"Unsupported table {table}") from exc

    # Find the current version for this business key
    cursor.execute(
        f"SELECT * FROM {table} WHERE {value_key} = ? AND is_current = 1",
        (value_map.get(value_key, ""),),
    )

    existing = cursor.fetchone()
    if existing:
        # Compare all provided attributes to detect changes.
        changed = False
        for col, new_val in value_map.items():
            # sqlite3.Row allows dict-like access
            old_val = existing[col]
            # Normalize None/empty string differences
            if old_val is None and (new_val is None or new_val == ""):
                continue
            if isinstance(old_val, float) or isinstance(old_val, int):
                # numeric comparison via string/number cast
                try:
                    if float(old_val) != float(new_val if new_val not in (None, "") else 0):
                        changed = True
                        break
                except Exception:
                    if str(old_val) != str(new_val):
                        changed = True
                        break
            else:
                if str(old_val) != str(new_val if new_val is not None else ""):
                    changed = True
                    break

        if not changed:
            # No attribute changes — return existing surrogate id.
            return existing[lookup_column]

        # Attribute changed: expire the current record and insert a new version.
        cursor.execute(
            f"UPDATE {table} SET is_current = 0, effective_to = ? WHERE {lookup_column} = ?",
            (now_ts, existing[lookup_column]),
        )

    # Insert new current version (covers both no-existing and changed cases).
    insert_columns = list(value_map.keys()) + ["effective_from", "effective_to", "is_current"]
    placeholders = ", ".join(["?"] * len(insert_columns))
    columns = ", ".join(insert_columns)
    insert_values = list(value_map.values()) + [now_ts, None, 1]

    cursor.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        insert_values,
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
