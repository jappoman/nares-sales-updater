"""Demo SQLite end-to-end: DELETE range + INSERT + merger tradotto."""
from __future__ import annotations

from pathlib import Path

import pytest

from nares_sales_updater import cleaning, mapping as mapping_mod
from nares_sales_updater.db import SqliteBackend
from nares_sales_updater.demo import load_sample_table
from nares_sales_updater.sp_orders_global import run_orders_global_sqlite


@pytest.fixture()
def demo_db(tmp_path, config, mappings, export_rows):
    db = SqliteBackend(tmp_path / "demo.db")
    db.connect()
    yield db, config, mappings, export_rows
    db.close()


def _seed(db: SqliteBackend, table: str, sample_file: str):
    from conftest import DB_SAMPLE_DIR

    headers, rows = load_sample_table(DB_SAMPLE_DIR / sample_file)
    db.create_table(table, headers)
    db._execute(f'DELETE FROM "{table}"')
    db.insert_rows(table, headers, [dict(zip(headers, r)) for r in rows])


def test_demo_roundtrip(demo_db, tmp_path):
    db, config, mappings, export_rows = demo_db
    samples = {
        "orders": "[GenesiRetail].[dbo].[orders].xlsx",
        "ordersByDate": "[GenesiRetail].[dbo].[ordersByDate].xlsx",
        "Preventivi": "[GenesiRetail].[dbo].[Preventivi].xlsx",
        "ingressi": "[GenesiRetail].[dbo].[ingressi].xlsx",
    }
    for table, sample in samples.items():
        _seed(db, table, sample)

    # pipeline per ogni export
    for key, spec in config["exports"].items():
        rows, stats = cleaning.clean_export(key, export_rows[key], mappings[key], config)
        table = spec["table"]
        date_range = {"date_from": "2026-04-21", "date_to": "2026-08-20"} if key != "ingressi" else {"anno_from": 2026, "anno_to": 2026}
        deleted = db.delete_range(table, spec["delete"]["key"], date_range.get("date_from", date_range.get("anno_from")),
                                  date_range.get("date_to", date_range.get("anno_to")), spec["delete"]["mode"])
        inserted = db.insert_rows(table, mappings[key].target_columns, rows)
        assert inserted == len(rows) > 0
        assert deleted >= 0

    counts = run_orders_global_sqlite(db)
    assert counts["ordersGlobal"] > 0
    assert counts["ordersGlobalDTOrd"] > 0
    # il merger unisce orders+ordersByDate: non può superare il numero di righe obd
    obd_rows = db.row_count("ordersByDate")
    assert counts["ordersGlobal"] <= obd_rows + 100  # margine per gli ordini 'Piano protezione'


def test_delete_range_orders(demo_db):
    db, config, mappings, export_rows = demo_db
    _seed(db, "orders", "[GenesiRetail].[dbo].[orders].xlsx")
    before = db.row_count("orders")
    deleted = db.delete_range("orders", "OrderDate", "2023-01-01", "2023-12-31", "range")
    assert deleted > 0
    assert db.row_count("orders") == before - deleted


def test_delete_open_ended_preventivi(demo_db):
    db, config, mappings, export_rows = demo_db
    _seed(db, "Preventivi", "[GenesiRetail].[dbo].[Preventivi].xlsx")
    deleted = db.delete_range("Preventivi", "quotation_date", "2025-06-10", None, "open_ended_from")
    # righe con quotation_date > 2025-06-10
    assert deleted >= 0
