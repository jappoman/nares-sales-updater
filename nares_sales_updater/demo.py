"""Demo end-to-end su SQLite: simula il DB vero senza toccarlo.

- crea le tabelle target (orders, ordersByDate, Preventivi, ingressi)
- le carica con i dati di esempio (docs/res/esempi_tabelle_sql)
- esegue DELETE del range + INSERT dei dati puliti
- esegue la traduzione Python di Create_ordersGlobal
- stampa conteggi di verifica
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from .db import SqliteBackend, apply_strategy

DB_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "docs" / "res" / "esempi_tabelle_sql"

TABLES = {
    "orders": "[GenesiRetail].[dbo].[orders].xlsx",
    "ordersByDate": "[GenesiRetail].[dbo].[ordersByDate].xlsx",
    "Preventivi": "[GenesiRetail].[dbo].[Preventivi].xlsx",
    "ingressi": "[GenesiRetail].[dbo].[ingressi].xlsx",
}


def load_sample_table(path: Path) -> tuple[list[str], list[list]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers = [str(h) if h is not None else "" for h in rows[0]]
    return headers, rows[1:]


def _seed_table(backend: SqliteBackend, table: str, headers: list[str], rows: list[list]) -> int:
    backend.create_table(table, headers)
    backend._execute(f'DELETE FROM "{table}"')
    backend.insert_rows(table, headers, [dict(zip(headers, r)) for r in rows])
    return len(rows)


def run_demo(demo_path: Path, config: dict, cleaned: dict[str, tuple[list[dict], list[str]]],
             date_ranges: dict, logger) -> None:
    backend = SqliteBackend(demo_path)
    backend.connect()
    try:
        logger("Demo SQLite: preparo il database di prova...")
        for table, sample in TABLES.items():
            headers, rows = load_sample_table(DB_SAMPLE_DIR / sample)
            if not headers:
                logger(f"  [warn] nessun dato di esempio per {table}, creo tabella vuota")
                backend.create_table(table, [])
                continue
            count = _seed_table(backend, table, headers, rows)
            logger(f"  tabella {table}: {count} righe di esempio caricate")

        for export_key, (rows, columns) in cleaned.items():
            spec = config["exports"][export_key]
            table = spec["table"]
            missing = backend.validate_table(table, columns)
            if missing:
                raise RuntimeError(f"Demo: tabella {table} non ha le colonne attese: {missing}")
            strategy = spec.get("strategy", "delete_insert")
            before = backend.row_count(table)
            processed, deleted = apply_strategy(backend, spec, columns, rows, date_ranges[export_key], logger)
            after = backend.row_count(table)
            logger(
                f"  {table} [{strategy}]: prima={before}, processate={processed}, eliminate={deleted}, dopo={after}"
            )

        logger("Demo: eseguo il merger (Create_ordersGlobal tradotta in Python)...")
        from .sp_orders_global import run_orders_global_sqlite

        counts = run_orders_global_sqlite(backend)
        for table, count in counts.items():
            logger(f"  ordersGlobal pipeline -> {table}: {count} righe")

        backend.commit()
        logger(f"Demo completata. Database di prova: {demo_path}")
    except Exception:
        try:
            backend.rollback()
        except Exception:
            pass
        raise
    finally:
        backend.close()
