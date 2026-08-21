"""Generate config.json from the sample files in docs/res.

This is a development helper: it re-derives the column mappings from the
reference exports ([dbo].*.xlsx = target DB schema) and the NARES sample
exports (file di esempio/*) so config.json stays in sync with the real files.
Run from the repo root:  python tools/generate_config.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl
import xlrd

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "res"

SAMPLES = {
    "orders": {
        "export": DOCS / "file di esempio" / "orderExport.xlsx",
        "sheet": "orders",
        "db": DOCS / "esempi_tabelle_sql" / "[GenesiRetail].[dbo].[orders].xlsx",
        "renames": {"Pricelist": "GrossPice", "TotalPrice": "NetPrice"},
    },
    "ordersByDate": {
        "export": DOCS / "file di esempio" / "OrdersByOrderDate.xlsx",
        "sheet": "Orders by Order Date",
        "db": DOCS / "esempi_tabelle_sql" / "[GenesiRetail].[dbo].[ordersByDate].xlsx",
        "renames": {},
    },
}


def load_xlsx_headers(path: Path, sheet: str | None = None) -> list[str]:
    wb = openpyxl.load_workbook(path)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    headers = [str(c.value) for c in ws[1]]
    wb.close()
    return headers


def match_columns(db_cols: list[str], src_cols: list[str], renames: dict[str, str]) -> list[dict]:
    """Return explicit mapping list [{target, source}] in DB order."""
    used: set[int] = set()
    result: list[dict] = []
    for dbc in db_cols:
        src = None
        for i, s in enumerate(src_cols):
            if i in used:
                continue
            if s == dbc:
                src = s
                used.add(i)
                break
        if src is None:
            for i, s in enumerate(src_cols):
                if i in used:
                    continue
                if renames.get(s) == dbc:
                    src = s
                    used.add(i)
                    break
        if src is None:
            # prefix tolerance for truncated headers / duplicate date columns
            for i, s in enumerate(src_cols):
                if i in used:
                    continue
                if len(s) >= 8 and dbc.startswith(s):
                    src = s
                    used.add(i)
                    break
        if src is None:
            raise SystemExit(f"CRITICAL: no source column for DB column {dbc!r}")
        result.append({"target": dbc, "source": src})
    return result


def build_config() -> dict:
    config = {
        "nares": {
            "portal_base": "https://www.nares.natuzzi.com/naresportal",
            "login_url": "https://www.nares.natuzzi.com/naresportal/pages/login",
            "main_url": "https://nares.natuzzi.com/naresportal/pages/main.jsf",
            "username_env": "NARES_USERNAME",
            "password_env": "NARES_PASSWORD",
            "societa_orders_by_date": "GENESI RETAIL SRL",
            "selectors": {
                "username_input": "input[name='username']",
                "password_input": "input[name='password']",
                "login_button": "input[type='submit']",
                "export_type_select": "select[name='exp']",
                "export_date_from": "input[name='datada']",
                "export_date_to": "input[name='dataa']",
                "export_anno_from": "input[name='annoda']",
                "export_anno_to": "input[name='annoa']",
                "export_societa": "select[name='soc']",
                "export_submit": "input[type='submit'][value*='export' i]",
            },
        },
        "sql": {
            "server_env": "SQL_SERVER",
            "database": "GenesiRetail",
            "username_env": "SQL_USERNAME",
            "password_env": "SQL_PASSWORD",
            "driver": "",
            "server_default": "btsrv-qr.bteam.local",
        },
        "exports": {
            "orders": {
                "label": "ordini",
                "download_name": "orderExport.xlsx",
                "sheet": "orders",
                "table": "orders",
                "date_from_offset_days": 120,
                "date_to_offset_days": 1,
                "delete": {"key": "OrderDate", "mode": "range"},
                "strategy": "delete_insert",
                "numeric_columns": ["TotalDeposits", "Balance", "Seats", "Volume", "GrossPice", "DiscountAmount", "NetPrice", "InvoicedNetPrice", "GrossWeight"],
            },
            "ordersByDate": {
                "label": "ordini x data ordine",
                "download_name": "OrdersByOrderDate.xlsx",
                "sheet": "Orders by Order Date",
                "table": "ordersByDate",
                "date_from_offset_days": 120,
                "date_to_offset_days": 1,
                "delete": {"key": "dtOrdine", "mode": "range"},
                "strategy": "delete_insert",
                "numeric_columns": ["qtaOrdinata", "totaleSedute", "totalePesoNetto", "totalePesoLordo", "totaleVolume", "selloutTeorico", "sconto", "importoScontatoNetto", "importoScontato", "selloutRealeNetto", "selloutReale", "Acconto", "AccontoContabilizzato", "saldo", "valoreAcquisto"],
            },
            "preventivi": {
                "label": "preventivi",
                "download_name": "quotations.xls",
                "sheet": "Quotation",
                "table": "Preventivi",
                "date_from_offset_days": 30,
                "date_to_offset_days": 1,
                "delete": {"key": "quotation_date", "mode": "open_ended_from"},
                "strategy": "upsert",
                "key_columns": ["quotation_nr", "row_nr", "proposal_nr"],
                "mapping": {"rule": "snake_case", "drop_columns": ["Movement ID"]},
                "numeric_columns": ["quotation_nr", "seller_id", "consumer_id", "order_nr", "no_sale_reason_id", "proposal_nr", "row_nr", "from_stock", "article_type_id", "quantities", "seats", "row_amount", "proposal_amount"],
            },
            "ingressi": {
                "label": "rapportino visite",
                "download_name": "Rapportinovisite.xlsx",
                "sheet": "Rapportino visite",
                "table": "ingressi",
                "anno_from_offset_years": 0,
                "anno_to_offset_years": 0,
                "delete": {"key": "anno", "mode": "year_range"},
                "strategy": "upsert",
                "key_columns": ["cdStore", "data"],
                "mapping": {"rule": "derive_ingressi"},
                "numeric_columns": ["cdStore", "anno", "mese", "ingressi"],
            },
        },
        "orders_blocklist": [
            "15345527", "15375154", "15480497", "15503397", "15471071",
            "15547189", "15568336", "15580894", "14337195", "15642881",
            "15653167", "15692949", "15710991",
        ],
        "stored_procedure": "Create_ordersGlobal",
        "mappings": {},
    }

    for key, spec in SAMPLES.items():
        src = load_xlsx_headers(spec["export"], spec["sheet"])
        db = load_xlsx_headers(spec["db"])
        config["mappings"][key] = {
            "mode": "explicit",
            "columns": match_columns(db, src, spec["renames"]),
        }

    # preventivi: DB columns for reference (rule-based mapping)
    db_prev = load_xlsx_headers(DOCS / "esempi_tabelle_sql" / "[GenesiRetail].[dbo].[Preventivi].xlsx")
    config["mappings"]["preventivi"] = {"mode": "rule", "rule": "snake_case", "db_columns": db_prev}

    # ingressi: DB columns for reference (derived)
    db_ing = load_xlsx_headers(DOCS / "esempi_tabelle_sql" / "[GenesiRetail].[dbo].[ingressi].xlsx")
    config["mappings"]["ingressi"] = {"mode": "rule", "rule": "derive_ingressi", "db_columns": db_ing}

    return config


def main() -> None:
    config = build_config()
    out = ROOT / "config.json"
    out.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    orders_n = len(config["mappings"]["orders"]["columns"])
    obd_n = len(config["mappings"]["ordersByDate"]["columns"])
    print(f"config.json written: orders={orders_n} cols, ordersByDate={obd_n} cols")
    print(f"preventivi db cols: {len(config['mappings']['preventivi']['db_columns'])}")
    print(f"ingressi db cols: {len(config['mappings']['ingressi']['db_columns'])}")


if __name__ == "__main__":
    main()
