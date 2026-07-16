"""Transformation helpers for validating and shaping order rows before loading."""

from typing import Any

from .loading import prepare_fact_row
from .utils import logger, clean_text
from .validation import validate_row
from pathlib import Path
import csv
from datetime import datetime


def _backup_raw_rows(source_file_name: str, rows: list[dict[str, Any]]) -> None:
    # Backup incoming raw data (pre-transform) into CSVs grouped by intended
    # target: dim_client, dim_product, dim_payment, fact_orders.
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path("data/raw/backups") / f"{source_file_name}_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    client_cols = [
        "ClientName",
        "DeliveryAddress",
        "DeliveryCity",
        "DeliveryPostcode",
        "DeliveryCountry",
        "DeliveryContactNumber",
    ]
    product_cols = ["ProductName", "ProductType", "UnitPrice"]
    payment_cols = ["PaymentType", "PaymentBillingCode"]
    fact_cols = [
        "OrderNumber",
        "ClientName",
        "ProductName",
        "PaymentType",
        "PaymentDate",
        "Currency",
        "ProductQuantity",
        "UnitPrice",
        "TotalPrice",
    ]

    def _write(path: Path, cols: list[str]):
        with path.open("w", newline="") as fout:
            writer = csv.DictWriter(fout, fieldnames=cols)
            writer.writeheader()
            for r in rows:
                writer.writerow({c: r.get(c, "") for c in cols})

    _write(backup_dir / f"{source_file_name}_raw_dim_client.csv", client_cols)
    _write(backup_dir / f"{source_file_name}_raw_dim_product.csv", product_cols)
    _write(backup_dir / f"{source_file_name}_raw_dim_payment.csv", payment_cols)
    _write(backup_dir / f"{source_file_name}_raw_fact_orders.csv", fact_cols)


def transform_rows(connection: Any, rows: list[dict[str, Any]], source_file_name: str) -> tuple[list[tuple[Any, ...]], list[str], int]:
    """Validate rows, backup raw data, normalize/dedupe, prepare fact rows, and collect rejection reasons.

    Normalization rules applied here:
    - `ClientName` and `DeliveryCountry` are normalized (case-insensitive). `UK` -> `UNITED KINGDOM`.
    - Duplicate `OrderNumber` values within the same file are skipped.
    """
    # Backup raw incoming rows before any modifications.
    try:
        _backup_raw_rows(source_file_name, rows)
    except Exception:
        logger.warning("Failed to write raw backup for %s", source_file_name)

    prepared_rows: list[tuple[Any, ...]] = []
    reject_reasons: list[str] = []
    valid_rows = 0

    seen_orders: set[str] = set()

    for row in rows:
        # Basic validation
        valid, issues = validate_row(row)
        if not valid:
            reject_reasons.append("; ".join(issues))
            logger.warning("Rejected row in %s: %s", source_file_name, "; ".join(issues))
            continue

        # Deduplicate by OrderNumber within the file
        order_number = clean_text(row.get("OrderNumber"))
        if order_number in seen_orders:
            logger.info("Duplicate order in input, skipping %s", order_number)
            continue
        seen_orders.add(order_number)

        # Normalizations (business-key canonicalization)
        client_name = clean_text(row.get("ClientName"))
        # Keep the cleaned display value, but store a lookup form for matching.
        row["ClientName"] = client_name
        row["ClientName_lookup"] = client_name.upper()

        country = clean_text(row.get("DeliveryCountry"))
        country_norm = country.upper() if country else ""
        if country_norm == "UK":
            country_norm = "UNITED KINGDOM"
        row["DeliveryCountry"] = "UNITED KINGDOM" if country_norm == "UNITED KINGDOM" else country_norm
        row["DeliveryCountry_lookup"] = country_norm

        # Now prepare using loading logic
        prepared_row = prepare_fact_row(connection, row, source_file_name)
        if prepared_row is None:
            continue

        prepared_rows.append(prepared_row)
        valid_rows += 1

    return prepared_rows, reject_reasons, valid_rows
