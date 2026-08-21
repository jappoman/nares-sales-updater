"""Fixture condivise: config e mapping risolti dai file di esempio."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nares_sales_updater import config as cfg  # noqa: E402
from nares_sales_updater import excel_io, mapping  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "docs" / "res" / "file di esempio"
DB_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "docs" / "res" / "esempi_tabelle_sql"


@pytest.fixture(scope="session")
def config():
    return cfg.load_config(Path(__file__).resolve().parent.parent / "config.json")


@pytest.fixture(scope="session")
def export_rows(config):
    """Legge i 4 file di esempio una volta sola."""
    result = {}
    for key, spec in config["exports"].items():
        result[key] = excel_io.read_excel(SAMPLE_DIR / spec["download_name"], spec.get("sheet"))
    return result


@pytest.fixture(scope="session")
def export_headers(config):
    result = {}
    for key, spec in config["exports"].items():
        result[key] = excel_io.read_headers(SAMPLE_DIR / spec["download_name"], spec.get("sheet"))
    return result


@pytest.fixture(scope="session")
def mappings(config, export_headers):
    result = {}
    for key in config["exports"]:
        column_map, _ignored = mapping.resolve_mapping(config, key, export_headers[key])
        result[key] = column_map
    return result
