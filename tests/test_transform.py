from datetime import date

from abc_warehouse.transform import build_date_rows


def test_build_date_rows_deduplicates_and_derives_attributes():
    dates = [date(2023, 1, 15), date(2023, 1, 15), date(2023, 1, 16)]
    rows = build_date_rows(dates)

    assert len(rows) == 2  # deduplicated

    first = rows[0]
    assert first["date_key"] == 20230115
    assert first["year"] == 2023
    assert first["month"] == 1
    assert first["quarter"] == 1
    assert first["day"] == 15
    assert first["day_name"] == "Sunday"
    assert first["is_weekend"] is True


def test_build_date_rows_empty_input():
    assert build_date_rows([]) == []
