"""
Cleaning & validation.

Turns raw string rows from `extract.py` into typed, normalised records ready
for loading, and separates out any row that fails validation into a
"rejects" DataFrame (with a human-readable reason) instead of raising and
stopping the whole pipeline. This is what lets the pipeline keep going when
one file among several contains errors.
"""
import re

import pandas as pd

from .config import COUNTRY_NORMALISATION

REQUIRED_TEXT_FIELDS = ["OrderNumber", "ClientName", "ProductName", "ProductType"]


def normalise_country(raw) -> str:
    """Map known variants of a country name to a single canonical spelling."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    key = str(raw).strip().upper()
    if not key:
        return None
    return COUNTRY_NORMALISATION.get(key, str(raw).strip().title())


def normalise_business_key(raw_name: str) -> str:
    """Collapse a name to a case/punctuation-insensitive matching key.

    e.g. "Howell LLC" and "HOWELL LLC" both become "HOWELLLLC", so the two
    variants seen in the source data resolve to the same customer.
    """
    return re.sub(r"[^A-Z0-9]", "", str(raw_name).upper())


def pick_canonical_name(names: list) -> str:
    """Choose a single display spelling among several variants of a name.

    Prefers a variant that isn't ALL CAPS (usually the more natural-looking
    one), falling back to whichever variant is most common.
    """
    non_upper = [n for n in names if n != n.upper()]
    pool = non_upper or names
    return pd.Series(pool).mode().iloc[0]


def _parse_decimal(value) -> float:
    return float(str(value).replace(",", "").replace("£", "").strip())


def _parse_positive_int(value) -> int:
    parsed = int(float(str(value).strip()))
    return parsed


def _parse_date(value):
    parsed = pd.to_datetime(value, errors="raise")
    return parsed.date()


def _clean_row(record: dict) -> tuple:
    """Validate and normalise a single row.

    Returns (clean_record, None) on success, or (None, error_reason) on failure.
    """
    errors = []

    order_line_id = str(record.get("OrderNumber") or "").strip()
    if not order_line_id:
        errors.append("Missing OrderNumber")

    client_name_raw = str(record.get("ClientName") or "").strip()
    if not client_name_raw:
        errors.append("Missing ClientName")

    product_name = str(record.get("ProductName") or "").strip()
    if not product_name:
        errors.append("Missing ProductName")

    product_type = str(record.get("ProductType") or "").strip()
    if not product_type:
        errors.append("Missing ProductType")

    unit_price = None
    try:
        unit_price = _parse_decimal(record.get("UnitPrice"))
        if unit_price < 0:
            errors.append("UnitPrice is negative")
    except (ValueError, TypeError):
        errors.append(f"UnitPrice '{record.get('UnitPrice')}' is not numeric")

    quantity = None
    try:
        quantity = _parse_positive_int(record.get("ProductQuantity"))
        if quantity <= 0:
            errors.append("ProductQuantity must be a positive integer")
    except (ValueError, TypeError):
        errors.append(f"ProductQuantity '{record.get('ProductQuantity')}' is not a valid integer")

    total_price = None
    try:
        total_price = _parse_decimal(record.get("TotalPrice"))
    except (ValueError, TypeError):
        errors.append(f"TotalPrice '{record.get('TotalPrice')}' is not numeric")

    payment_date = None
    try:
        payment_date = _parse_date(record.get("PaymentDate"))
    except (ValueError, TypeError):
        errors.append(f"PaymentDate '{record.get('PaymentDate')}' is invalid or missing")

    if errors:
        return None, "; ".join(errors)

    # TotalPrice is derivable from UnitPrice * ProductQuantity: recompute it as
    # the trusted value rather than rejecting on a small rounding mismatch.
    total_price = round(unit_price * quantity, 2)

    currency = str(record.get("Currency") or "GBP").strip().upper()

    billing_code = str(record.get("PaymentBillingCode") or "").strip()
    order_id = billing_code.rsplit("-", 1)[0] if "-" in billing_code else (billing_code or order_line_id)

    try:
        line_number = int(order_line_id.rsplit("-", 1)[-1])
    except ValueError:
        line_number = 1

    clean_record = {
        "order_line_id": order_line_id,
        "order_id": order_id,
        "line_number": line_number,
        "client_name_raw": client_name_raw,
        "customer_id": normalise_business_key(client_name_raw),
        "product_name": product_name,
        "product_type": product_type,
        "product_id": f"{normalise_business_key(product_name)}|{normalise_business_key(product_type)}",
        "unit_price": unit_price,
        "quantity": quantity,
        "total_price": total_price,
        "currency": currency,
        "delivery_address": str(record.get("DeliveryAddress") or "").strip() or None,
        "delivery_city": str(record.get("DeliveryCity") or "").strip().title() or None,
        "delivery_postcode": str(record.get("DeliveryPostcode") or "").strip().upper() or None,
        "delivery_country": normalise_country(record.get("DeliveryCountry")),
        "delivery_contact_number": str(record.get("DeliveryContactNumber") or "").strip() or None,
        "payment_type": str(record.get("PaymentType") or "").strip() or None,
        "payment_billing_code": billing_code or None,
        "payment_date": payment_date,
    }
    return clean_record, None


def clean_orders(raw_df: pd.DataFrame):
    """Validate and normalise raw rows.

    Returns (clean_df, rejects_df). `clean_df` is ready for transform/load.
    `rejects_df` mirrors the original raw columns plus an `error_reason`
    column, and is written out by the pipeline for troubleshooting.
    """
    clean_rows = []
    reject_rows = []

    for _, row in raw_df.iterrows():
        record = row.to_dict()
        clean_record, error_reason = _clean_row(record)
        if error_reason:
            reject_rows.append({**record, "error_reason": error_reason})
        else:
            clean_rows.append(clean_record)

    clean_df = pd.DataFrame(clean_rows)
    rejects_df = pd.DataFrame(reject_rows)

    # Duplicate OrderNumber (the fact table's natural key) within the same
    # file: keep the first occurrence, reject the rest with a clear reason.
    if not clean_df.empty:
        dup_mask = clean_df.duplicated(subset=["order_line_id"], keep="first")
        if dup_mask.any():
            dup_rows = clean_df.loc[dup_mask].copy()
            dup_rows["error_reason"] = "Duplicate OrderNumber within file"
            rejects_df = pd.concat([rejects_df, dup_rows], ignore_index=True)
            clean_df = clean_df.loc[~dup_mask].reset_index(drop=True)

    return clean_df, rejects_df
