"""
Central configuration for the ABC Musical Instruments data warehouse.

Keeping paths and lookup/reference data here means every module (and every
test) imports the same single source of truth instead of hard-coding paths.
"""
from pathlib import Path

# Project root = two levels up from this file (src/abc_warehouse/config.py -> project root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEFAULT_DB_PATH = BASE_DIR / "warehouse.db"

DEFAULT_INPUT_PATH = BASE_DIR / "data" / "raw" / "orders_2023.csv"
REJECTS_DIR = BASE_DIR / "data" / "rejects"

# Known variants of "United Kingdom" seen in messy source data. Anything not
# found here is fall back to str.title() rather than dropped, so the
# pipeline never silently loses a delivery country it doesn't recognise.
COUNTRY_NORMALISATION = {
    "UK": "United Kingdom",
    "U.K.": "United Kingdom",
    "UNITED KINGDOM": "United Kingdom",
    "GREAT BRITAIN": "United Kingdom",
    "GB": "United Kingdom",
    "ENGLAND": "United Kingdom",
    "SCOTLAND": "United Kingdom",
    "WALES": "United Kingdom",
    "NORTHERN IRELAND": "United Kingdom",
}

# Columns required in every input file. Extraction fails fast if any are missing.
EXPECTED_COLUMNS = [
    "OrderNumber",
    "ClientName",
    "ProductName",
    "ProductType",
    "UnitPrice",
    "ProductQuantity",
    "TotalPrice",
    "Currency",
    "DeliveryAddress",
    "DeliveryCity",
    "DeliveryPostcode",
    "DeliveryCountry",
    "DeliveryContactNumber",
    "PaymentType",
    "PaymentBillingCode",
    "PaymentDate",
]
