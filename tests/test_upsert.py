"""Test della strategia upsert su SQLite (update+insert+stale delete)."""
from __future__ import annotations

import pytest

from nares_sales_updater import cleaning
from nares_sales_updater.db import SqliteBackend, apply_strategy, ensure_unique_keys
from nares_sales_updater.demo import load_sample_table

from conftest import DB_SAMPLE_DIR

ORDERS_SAMPLE = "[GenesiRetail].[dbo].[orders].xlsx"
HEADERS = None


def _headers(db: SqliteBackend) -> list[str]:
    return [d[0] for d in db.conn.cursor().execute('SELECT * FROM "orders" LIMIT 0').description]


@pytest.fixture()
def db(tmp_path):
    backend = SqliteBackend(tmp_path / "upsert.db")
    backend.connect()
    yield backend
    backend.close()


def _seed_orders(db: SqliteBackend):
    headers, rows = load_sample_table(DB_SAMPLE_DIR / ORDERS_SAMPLE)
    db.create_table("orders", headers)
    db._execute('DELETE FROM "orders"')
    db.insert_rows("orders", headers, [dict(zip(headers, r)) for r in rows])


def _count(db, where: str) -> int:
    return db.query(f'SELECT COUNT(*) FROM "orders" WHERE {where}')[0][0]


def test_upsert_updates_existing_inserts_new(db):
    """Export completo del range: nessuna riga stale, update+insert."""
    _seed_orders(db)
    headers = _headers(db)
    before = db.row_count("orders")

    all_rows = db.query('SELECT * FROM "orders"')
    export = [dict(zip(headers, r)) for r in all_rows]
    # modifico una riga esistente con chiave completa (stessa chiave)
    target = next(r for r in export if r.get("ArticleCode") not in (None, ""))
    target["OrderStatus"] = "AGGIORNATO"
    target["TotalDeposits"] = 9999
    # aggiungo una riga nuova (chiave nuova)
    new_row = dict(target)
    new_row["OrderNumber"] = "999999999"
    new_row["ArticleCode"] = "DUP00001"
    new_row["OrderStatus"] = "NUOVO"
    export.append(new_row)

    processed, deleted = db.upsert_rows(
        "orders", headers, ["OrderNumber", "ArticleCode"], export,
        "OrderDate", "2023-01-01", "2023-02-28", "range",
    )
    assert processed == len(export)
    assert deleted == 0  # export completo del range: nulla di stale
    assert db.row_count("orders") == before + 1

    updated = db.query(
        f'SELECT "OrderStatus", "TotalDeposits" FROM "orders" '
        f'WHERE "OrderNumber" = \'{target["OrderNumber"]}\' AND "ArticleCode" = \'{target["ArticleCode"]}\''
    )
    assert updated[0][0] == "AGGIORNATO"
    assert float(updated[0][1]) == 9999
    inserted = db.query(
        f'SELECT "OrderStatus" FROM "orders" WHERE "OrderNumber" = \'999999999\' AND "ArticleCode" = \'DUP00001\''
    )
    assert inserted and inserted[0][0] == "NUOVO"


def test_empty_export_guard_does_not_touch_db(db):
    """Guardia di sicurezza: un export vuoto non cancella nulla (probabile errore di estrazione)."""
    _seed_orders(db)
    headers = _headers(db)
    before = db.row_count("orders")

    # delete_insert con export vuoto: nessuna modifica
    spec = {"table": "orders", "strategy": "delete_insert", "delete": {"key": "OrderDate", "mode": "range"}}
    processed, deleted = apply_strategy(db, spec, headers, [], {"date_from": "2023-01-01", "date_to": "2023-01-31"})
    assert processed == 0 and deleted == 0
    assert db.row_count("orders") == before

    # upsert con export vuoto: nessuna modifica
    spec_u = {"table": "orders", "strategy": "upsert", "key_columns": ["OrderNumber", "ArticleCode"],
              "delete": {"key": "OrderDate", "mode": "range"}}
    processed, deleted = apply_strategy(db, spec_u, headers, [], {"date_from": "2023-01-01", "date_to": "2023-01-31"})
    assert processed == 0 and deleted == 0
    assert db.row_count("orders") == before


def test_transaction_rollback(db):
    """Il DELETE non è committato finché non chiamiamo commit(): il rollback annulla tutto."""
    _seed_orders(db)
    db.commit()  # baseline committata: il rollback deve riportare qui
    headers = _headers(db)
    before = db.row_count("orders")

    # il delete del range avviene nella transazione corrente, senza commit
    deleted = db.delete_range("orders", "OrderDate", "2023-01-01", "2023-01-31", "range")
    assert deleted > 0
    assert db.row_count("orders") == before - deleted  # visibile nella stessa connessione

    db.rollback()
    assert db.row_count("orders") == before  # il rollback ripristina il baseline

    # e con il commit le modifiche restano
    deleted = db.delete_range("orders", "OrderDate", "2023-01-01", "2023-01-31", "range")
    db.commit()
    assert db.row_count("orders") == before - deleted


def test_upsert_partial_stale(db):
    """Export con metà delle righe di gennaio: l'altra metà viene cancellata."""
    _seed_orders(db)
    headers = _headers(db)
    before = db.row_count("orders")
    jan_rows = db.query('SELECT * FROM "orders" WHERE "OrderDate" >= \'2023-01-01\' AND "OrderDate" <= \'2023-01-31\'')
    keep = [dict(zip(headers, r)) for r in jan_rows[: len(jan_rows) // 2]]
    processed, deleted = db.upsert_rows("orders", headers, ["OrderNumber", "ArticleCode"], keep,
                                        "OrderDate", "2023-01-01", "2023-01-31", "range")
    assert processed == len(keep)
    assert deleted == len(jan_rows) - len(keep)
    assert _count(db, '"OrderDate" >= \'2023-01-01\' AND "OrderDate" <= \'2023-01-31\'') == len(keep)
    assert db.row_count("orders") == before - (len(jan_rows) - len(keep))


def test_apply_strategy_upsert_via_config(db, config, mappings, export_rows):
    """La strategia di config (upsert su ingressi) applicata alla pipeline reale."""
    from nares_sales_updater.demo import load_sample_table

    headers, rows = load_sample_table(DB_SAMPLE_DIR / "[GenesiRetail].[dbo].[ingressi].xlsx")
    db.create_table("ingressi", headers)
    db._execute('DELETE FROM "ingressi"')
    db.insert_rows("ingressi", headers, [dict(zip(headers, r)) for r in rows])
    before = db.row_count("ingressi")

    cleaned, _ = cleaning.derive_ingressi(
        export_rows["ingressi"], mappings["ingressi"],
        config["exports"]["ingressi"]["numeric_columns"],
    )
    spec = config["exports"]["ingressi"]
    processed, deleted = apply_strategy(db, spec, mappings["ingressi"].target_columns, cleaned,
                                        {"anno_from": 2026, "anno_to": 2026})
    assert processed == len(cleaned)
    # nel DB di esempio le righe 2026 vengono sostituite da quelle dell'export,
    # le altre (2024/2025) restano: il totale non deve raddoppiare
    kept_2026 = db.query('SELECT COUNT(*) FROM "ingressi" WHERE "anno" = 2026')[0][0]
    assert kept_2026 == len(cleaned)


def test_ensure_unique_keys_detects_duplicates():
    rows = [
        {"OrderNumber": 1, "ArticleCode": "A"},
        {"OrderNumber": 1, "ArticleCode": "A"},
    ]
    with pytest.raises(Exception):
        ensure_unique_keys(rows, ["OrderNumber", "ArticleCode"], "orders")
    # chiavi con tipi diversi normalizzati uguale -> duplicato
    rows2 = [
        {"OrderNumber": 1.0, "ArticleCode": "A"},
        {"OrderNumber": "1", "ArticleCode": "A"},
    ]
    with pytest.raises(Exception):
        ensure_unique_keys(rows2, ["OrderNumber", "ArticleCode"], "orders")
