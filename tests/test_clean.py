import pandas as pd

from abc_warehouse.clean import (
    clean_orders,
    normalise_business_key,
    normalise_country,
    pick_canonical_name,
)


def test_normalise_country_known_variants():
    assert normalise_country("UK") == "United Kingdom"
    assert normalise_country("UNITED KINGDOM") == "United Kingdom"
    assert normalise_country("United Kingdom") == "United Kingdom"


def test_normalise_country_unknown_falls_back_to_title_case():
    assert normalise_country("france") == "France"


def test_normalise_country_blank_is_none():
    assert normalise_country("") is None
    assert normalise_country(None) is None


def test_normalise_business_key_case_and_punctuation_insensitive():
    assert normalise_business_key("Howell LLC") == normalise_business_key("HOWELL LLC")
    assert normalise_business_key("Rath - Schroeder") == normalise_business_key("RATH-SCHROEDER")


def test_pick_canonical_name_prefers_non_uppercase_variant():
    assert pick_canonical_name(["HOWELL LLC", "Howell LLC", "Howell LLC"]) == "Howell LLC"


def test_pick_canonical_name_falls_back_to_most_common_when_all_uppercase():
    assert pick_canonical_name(["HOWELL LLC", "HOWELL LLC"]) == "HOWELL LLC"


def _base_row(**overrides):
    row = {
        "OrderNumber": "PO0000001-1",
        "ClientName": "Test Client Ltd",
        "ProductName": "Trumpet",
        "ProductType": "Brass",
        "UnitPrice": "500",
        "ProductQuantity": "2",
        "TotalPrice": "1000",
        "Currency": "GBP",
        "DeliveryAddress": "1 Test St",
        "DeliveryCity": "Bristol",
        "DeliveryPostcode": "BS1 1AA",
        "DeliveryCountry": "UK",
        "DeliveryContactNumber": "+44 117 000 0000",
        "PaymentType": "Debit",
        "PaymentBillingCode": "PO0000001-20230115",
        "PaymentDate": "2023-01-15",
    }
    row.update(overrides)
    return row


def test_clean_orders_accepts_valid_row():
    df = pd.DataFrame([_base_row()])
    clean_df, rejects_df = clean_orders(df)
    assert len(clean_df) == 1
    assert rejects_df.empty
    assert clean_df.iloc[0]["order_id"] == "PO0000001"
    assert clean_df.iloc[0]["delivery_country"] == "United Kingdom"


def test_clean_orders_rejects_missing_client_name():
    df = pd.DataFrame([_base_row(ClientName="")])
    clean_df, rejects_df = clean_orders(df)
    assert clean_df.empty
    assert len(rejects_df) == 1
    assert "Missing ClientName" in rejects_df.iloc[0]["error_reason"]


def test_clean_orders_rejects_non_numeric_price():
    df = pd.DataFrame([_base_row(UnitPrice="abc")])
    clean_df, rejects_df = clean_orders(df)
    assert clean_df.empty
    assert "not numeric" in rejects_df.iloc[0]["error_reason"]


def test_clean_orders_rejects_non_positive_quantity():
    df = pd.DataFrame([_base_row(ProductQuantity="-1")])
    clean_df, rejects_df = clean_orders(df)
    assert clean_df.empty
    assert "positive integer" in rejects_df.iloc[0]["error_reason"]


def test_clean_orders_rejects_invalid_date():
    df = pd.DataFrame([_base_row(PaymentDate="not-a-date")])
    clean_df, rejects_df = clean_orders(df)
    assert clean_df.empty
    assert "PaymentDate" in rejects_df.iloc[0]["error_reason"]


def test_clean_orders_recomputes_total_price_from_unit_price_and_quantity():
    # TotalPrice in the source is wrong (should be 1000); the pipeline trusts
    # the derived value rather than the possibly-incorrect source column.
    df = pd.DataFrame([_base_row(TotalPrice="999999")])
    clean_df, _ = clean_orders(df)
    assert clean_df.iloc[0]["total_price"] == 1000.0


def test_clean_orders_rejects_duplicate_order_number_within_file():
    df = pd.DataFrame([_base_row(), _base_row()])
    clean_df, rejects_df = clean_orders(df)
    assert len(clean_df) == 1
    assert len(rejects_df) == 1
    assert "Duplicate OrderNumber" in rejects_df.iloc[0]["error_reason"]
