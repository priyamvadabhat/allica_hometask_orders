import sqlite3
from pathlib import Path

import pytest

from abc_warehouse.extract import ExtractionError, extract
from abc_warehouse.pipeline import run_pipeline

SAMPLE_HEADER = (
    "OrderNumber,ClientName,ProductName,ProductType,UnitPrice,ProductQuantity,"
    "TotalPrice,Currency,DeliveryAddress,DeliveryCity,DeliveryPostcode,"
    "DeliveryCountry,DeliveryContactNumber,PaymentType,PaymentBillingCode,PaymentDate"
)


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text(SAMPLE_HEADER + "\n" + "\n".join(rows) + "\n")
    return path


def test_run_pipeline_creates_db_and_loads_rows(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "orders.csv",
        [
            "PO1-1,Acme Ltd,Trumpet,Brass,500,2,1000,GBP,1 A St,Bristol,BS1 1AA,"
            "United Kingdom,+44 117 000 0000,Debit,PO1-20230101,2023-01-01",
        ],
    )
    db_path = tmp_path / "warehouse.db"
    assert not db_path.exists()

    summaries = run_pipeline([str(csv_path)], db_path=str(db_path))

    assert db_path.exists()
    assert summaries[0]["status"] == "success"
    assert summaries[0]["rows_loaded"] == 1

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM fact_order_lines").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_customer").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_product").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_date").fetchone()[0] == 1
    conn.close()


def test_rerunning_pipeline_is_idempotent(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "orders.csv",
        [
            "PO1-1,Acme Ltd,Trumpet,Brass,500,2,1000,GBP,1 A St,Bristol,BS1 1AA,"
            "United Kingdom,+44 117 000 0000,Debit,PO1-20230101,2023-01-01",
        ],
    )
    db_path = tmp_path / "warehouse.db"

    run_pipeline([str(csv_path)], db_path=str(db_path))
    run_pipeline([str(csv_path)], db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM fact_order_lines").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_customer").fetchone()[0] == 1
    conn.close()


def test_pipeline_recreates_db_after_deletion(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "orders.csv",
        [
            "PO1-1,Acme Ltd,Trumpet,Brass,500,2,1000,GBP,1 A St,Bristol,BS1 1AA,"
            "United Kingdom,+44 117 000 0000,Debit,PO1-20230101,2023-01-01",
        ],
    )
    db_path = tmp_path / "warehouse.db"

    run_pipeline([str(csv_path)], db_path=str(db_path))
    db_path.unlink()  # simulate the DB file being deleted
    run_pipeline([str(csv_path)], db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM fact_order_lines").fetchone()[0] == 1
    conn.close()


def test_pipeline_handles_file_with_bad_rows(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "orders_with_errors.csv",
        [
            "PO1-1,Acme Ltd,Trumpet,Brass,500,2,1000,GBP,1 A St,Bristol,BS1 1AA,"
            "United Kingdom,+44 117 000 0000,Debit,PO1-20230101,2023-01-01",
            "PO1-2,,Trumpet,Brass,500,2,1000,GBP,1 A St,Bristol,BS1 1AA,"
            "United Kingdom,+44 117 000 0000,Debit,PO1-20230101,2023-01-01",
        ],
    )
    db_path = tmp_path / "warehouse.db"

    summaries = run_pipeline([str(csv_path)], db_path=str(db_path))

    assert summaries[0]["status"] == "success"
    assert summaries[0]["rows_valid"] == 1
    assert summaries[0]["rows_rejected"] == 1
    assert Path(summaries[0]["rejects_file"]).exists()


def test_pipeline_reports_failure_for_missing_file(tmp_path):
    missing_path = tmp_path / "does_not_exist.csv"
    db_path = tmp_path / "warehouse.db"

    summaries = run_pipeline([str(missing_path)], db_path=str(db_path))

    assert summaries[0]["status"] == "failed"


def test_scd2_versions_customer_on_address_change(tmp_path):
    csv_1 = _write_csv(
        tmp_path,
        "orders_1.csv",
        [
            "PO1-1,Acme Ltd,Trumpet,Brass,500,2,1000,GBP,1 Old St,Bristol,BS1 1AA,"
            "United Kingdom,+44 117 000 0000,Debit,PO1-20230101,2023-01-01",
        ],
    )
    csv_2 = _write_csv(
        tmp_path,
        "orders_2.csv",
        [
            "PO2-1,Acme Ltd,Trumpet,Brass,500,1,500,GBP,99 New Rd,Leeds,LS1 1AA,"
            "United Kingdom,+44 117 111 1111,Debit,PO2-20230601,2023-06-01",
        ],
    )
    db_path = tmp_path / "warehouse.db"

    run_pipeline([str(csv_1)], db_path=str(db_path))
    run_pipeline([str(csv_2)], db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM dim_customer WHERE customer_id = 'ACMELTD' ORDER BY valid_from"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0]["is_current"] == 0
    assert rows[0]["city"] == "Bristol"
    assert rows[0]["valid_to"] == "2023-05-31"
    assert rows[1]["is_current"] == 1
    assert rows[1]["city"] == "Leeds"
    assert rows[1]["valid_to"] is None


def test_extract_raises_on_missing_columns(tmp_path):
    bad_path = tmp_path / "bad.csv"
    bad_path.write_text("OrderNumber,ClientName\nPO1-1,Acme Ltd\n")

    with pytest.raises(ExtractionError):
        extract(bad_path)
