"""Verifica del mapping colonne: ogni colonna della tabella DB ha una sorgente nell'export."""
from __future__ import annotations

from pathlib import Path

from nares_sales_updater import excel_io

from conftest import DB_SAMPLE_DIR, SAMPLE_DIR

DB_FILES = {
    "orders": "[GenesiRetail].[dbo].[orders].xlsx",
    "ordersByDate": "[GenesiRetail].[dbo].[ordersByDate].xlsx",
    "preventivi": "[GenesiRetail].[dbo].[Preventivi].xlsx",
    "ingressi": "[GenesiRetail].[dbo].[ingressi].xlsx",
}


def test_orders_mapping_covers_all_db_columns(config, mappings):
    mapping = mappings["orders"]
    db_cols = excel_io.read_headers(DB_SAMPLE_DIR / DB_FILES["orders"])
    assert mapping.target_columns == db_cols
    assert len(mapping.target_columns) == 77
    assert len(set(mapping.target_columns)) == 77  # nessun duplicato
    # tutte le colonne sorgente esistono nell'export
    headers = excel_io.read_headers(SAMPLE_DIR / "orderExport.xlsx", "orders")
    assert all(src in headers for src in mapping.source_columns)


def test_orders_renames(config, mappings):
    targets = mappings["orders"].target_columns
    assert "GrossPice" in targets and "NetPrice" in targets
    sources = mappings["orders"].source_columns
    assert "Pricelist" in sources and "TotalPrice" in sources


def test_ordersbydate_mapping_covers_all_db_columns(config, mappings):
    mapping = mappings["ordersByDate"]
    db_cols = excel_io.read_headers(DB_SAMPLE_DIR / DB_FILES["ordersByDate"])
    assert mapping.target_columns == db_cols
    assert len(mapping.target_columns) == 75
    assert len(set(mapping.target_columns)) == 75


def test_preventivi_mapping(config, mappings):
    mapping = mappings["preventivi"]
    db_cols = excel_io.read_headers(DB_SAMPLE_DIR / DB_FILES["preventivi"])
    assert mapping.target_columns == db_cols
    assert len(mapping.target_columns) == 46
    assert "movement_id" not in mapping.target_columns


def test_ingressi_mapping(config, mappings):
    assert mappings["ingressi"].target_columns == ["cdStore", "store", "data", "anno", "mese", "ingressi"]


def test_config_regenerates_identically(config):
    """tools/generate_config.py deve riprodurre le stesse colonne (export invariato)."""
    import json
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "tools/generate_config.py"], capture_output=True, text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert proc.returncode == 0, proc.stderr
    fresh = json.loads(Path("config.json").read_text(encoding="utf-8"))
    for key in ("orders", "ordersByDate"):
        assert fresh["mappings"][key]["columns"] == config["mappings"][key]["columns"]
