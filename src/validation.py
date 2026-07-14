"""Validation rules for incoming order rows before they are loaded."""

from typing import Any

from .utils import clean_text, parse_date, parse_decimal


# These are the mandatory fields that every incoming order row must contain.
REQUIRED_FIELDS = {
    "OrderNumber": "order_number",
    "ClientName": "client_name",
    "ProductName": "product_name",
    "ProductType": "product_type",
    "UnitPrice": "unit_price",
    "ProductQuantity": "product_quantity",
    "TotalPrice": "total_price",
    "Currency": "currency",
    "PaymentType": "payment_type",
}


def validate_row(row: dict[str, Any]) -> tuple[bool, list[str]]:
    # Check the row for missing values, bad numbers, invalid dates, and inconsistent totals.
    issues: list[str] = []
    for field, alias in REQUIRED_FIELDS.items():
        value = clean_text(row.get(field, ""))
        if not value:
            issues.append(f"missing {alias}")

    unit_price = parse_decimal(row.get("UnitPrice"))
    if unit_price is None:
        issues.append("invalid unit_price")

    quantity = parse_decimal(row.get("ProductQuantity"))
    if quantity is None:
        issues.append("invalid product_quantity")

    total_price = parse_decimal(row.get("TotalPrice"))
    if total_price is None:
        issues.append("invalid total_price")

    order_date = parse_date(row.get("PaymentDate"))
    if order_date is None:
        issues.append("invalid payment_date")

    if unit_price is not None and quantity is not None and total_price is not None:
        if round(unit_price * quantity, 2) != round(total_price, 2):
            issues.append("total_price mismatch")

    return len(issues) == 0, issues
