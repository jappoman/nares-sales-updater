"""Backend database: SQL Server (pyodbc) per la modalità live, SQLite per la demo.

Interfaccia comune:
    connect() / close()
    commit() / rollback()          # la transazione è gestita dal chiamante:
                                   # le singole operazioni NON committano da sole
                                   # (in caso di errore va chiamato rollback)
    validate_table(table, columns) -> list[str]   # colonne mancanti
    delete_range(table, key, date_from, date_to, mode) -> int  # righe cancellate
    insert_rows(table, columns, rows) -> int                     # righe inserite
    upsert_rows(table, columns, key_columns, rows, ...)          # upsert + stale delete
    run_stored_procedure(name) -> None
"""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None

from .sql_scripts import build_delete_sql

ODBC_DRIVER_CANDIDATES = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]


class DatabaseError(RuntimeError):
    pass


def _to_db_value(value):
    """Valore pronto per il backend (datetimes normalizzati per SQLite)."""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return "True" if value else "False"
    return value


def _key_part(value):
    """Normalizzazione del valore di una colonna-chiave (per confronti).

    None e stringhe vuote diventano None (trattati come chiave 'nulla',
    che in SQL non uguaglia mai nulla: per quelle righe si usa delete+insert)."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    v = _to_db_value(value)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    text = str(v)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _split_rows(rows: list[dict], key_columns: list[str]) -> tuple[list[dict], list[dict]]:
    """Separa le righe con chiave completa (upsert) da quelle con chiave nulla
    (per cui NULL != NULL in SQL: servono delete+insert per essere idempotenti)."""
    normal, null_key = [], []
    for row in rows:
        if any(_key_part(row.get(k)) is None for k in key_columns):
            null_key.append(row)
        else:
            normal.append(row)
    return normal, null_key


def _range_params(mode: str, date_from, date_to) -> list:
    if mode == "open_ended_from":
        return [date_from]
    return [int(date_from) if mode == "year_range" else date_from,
            int(date_to) if mode == "year_range" else date_to]


def ensure_unique_keys(rows: list[dict], key_columns: list[str], label: str) -> None:
    """Prima di un upsert le chiavi devono essere uniche nei dati da caricare.

    Le righe con chiave parziale nulla vengono ignorate: per quelle si usa
    comunque delete+insert (replace), quindi i duplicati non sono un problema."""
    seen: dict[tuple, int] = {}
    for index, row in enumerate(rows):
        key = tuple(_key_part(row.get(k)) for k in key_columns)
        if any(v is None for v in key):
            continue
        if key in seen:
            raise DatabaseError(
                f"{label}: chiave duplicata {key} (righe {seen[key]} e {index}). "
                "Impossibile fare upsert: verifica 'key_columns' in config.json "
                "oppure usa la strategia delete_insert."
            )
        seen[key] = index


def apply_strategy(backend, spec: dict, columns: list[str], rows: list[dict], date_range: dict,
                   logger=print):
    """Applica la strategia di caricamento configurata per la tabella.

    Ritorna (righe_processate, righe_eliminate).
    - strategy "upsert": update+insert delle righe presenti + delete delle righe
      stale nel range (le righe fuori range non vengono toccate).
    - strategy "delete_insert" (default storico): DELETE del range + INSERT di tutto.

    Guardia di sicurezza: un export VUOTO non tocca il DB (probabile estrazione
    fallita): cancelleremmo l'intero range senza reinserire nulla.
    """
    if not rows:
        logger(f"  [warn] {spec['table']}: export vuoto, nessuna modifica al database.")
        return 0, 0

    delete_cfg = spec["delete"]
    date_from = date_range.get("date_from", date_range.get("anno_from"))
    date_to = date_range.get("date_to", date_range.get("anno_to"))
    if spec.get("strategy") == "upsert":
        key_columns = spec["key_columns"]
        ensure_unique_keys(rows, key_columns, spec["table"])
        return backend.upsert_rows(
            spec["table"], columns, key_columns, rows,
            delete_cfg["key"], date_from, date_to, delete_cfg["mode"],
        )
    deleted = backend.delete_range(spec["table"], delete_cfg["key"], date_from, date_to, delete_cfg["mode"])
    inserted = backend.insert_rows(spec["table"], columns, rows)
    return inserted, deleted


def _key_convert_expr(column: str, sample_value) -> str:
    """Espressione CONVERT per il confronto delle chiavi nel MERGE (SQL Server).

    Le chiavi datetime (es. ingressi.data) richiedono lo stile 120 (ISO),
    altrimenti il default 'Jan  1 2026 12:00AM' non coincide mai con il valore
    normalizzato e l'upsert inserirebbe duplicati a ogni esecuzione."""
    if isinstance(sample_value, (datetime.datetime, datetime.date)):
        return f"CONVERT(NVARCHAR(19), t.{column}, 120)"
    return f"CONVERT(NVARCHAR(200), t.{column})"


# ---------------------------------------------------------------------------
# SQLite demo backend
# ---------------------------------------------------------------------------
class SqliteBackend:
    name = "sqlite-demo"

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def commit(self) -> None:
        if self.conn is not None:
            self.conn.commit()

    def rollback(self) -> None:
        if self.conn is not None:
            self.conn.rollback()

    def _execute(self, sql: str, params: tuple = ()):
        if self.conn is None:
            raise DatabaseError("Connessione SQLite non aperta")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def create_table(self, table: str, columns: list[str]) -> None:
        col_sql = ", ".join(f'"{c}" TEXT' for c in columns)
        self._execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({col_sql})')

    def ensure_stub_tables(self) -> None:
        """Tabelle di supporto usate dalla stored procedure (vuote in demo)."""
        for table, cols in [
            ("Anagrafica", ["Nome", "Cognome", "storeManager"]),
            ("Codifica_Store", ["nome_nares", "store_nares"]),
        ]:
            col_sql = ", ".join(f'"{c}" TEXT' for c in cols)
            self._execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({col_sql})')

    def validate_table(self, table: str, columns: list[str]) -> list[str]:
        cur = self._execute('PRAGMA table_info("%s")' % table)
        existing = {row[1] for row in cur.fetchall()}
        return [c for c in columns if c not in existing]

    def delete_range(self, table: str, key: str, date_from, date_to, mode: str) -> int:
        sql = build_delete_sql(table, key, date_from, date_to, mode)
        cur = self._execute(sql)
        return cur.rowcount if cur.rowcount != -1 else 0

    def insert_rows(self, table: str, columns: list[str], rows: list[dict]) -> int:
        if not rows:
            return 0
        col_sql = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        cur = self.conn.cursor()
        cur.executemany(
            f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
            [tuple(_to_db_value(r.get(c)) for c in columns) for r in rows],
        )
        return cur.rowcount if cur.rowcount != -1 else len(rows)

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    def _range_placeholders(self, key: str, date_from, date_to, mode: str) -> tuple[str, list]:
        if mode == "range":
            return f'"{key}" >= ? AND "{key}" <= ?', [date_from, date_to]
        if mode == "open_ended_from":
            return f'"{key}" > ?', [date_from]
        if mode == "year_range":
            return f'"{key}" >= ? AND "{key}" <= ?', [int(date_from), int(date_to)]
        raise DatabaseError(f"Modalità sconosciuta: {mode}")

    def _key_match_clause(self, key_columns: list[str], row: dict) -> tuple[str, list]:
        """WHERE per una singola riga: '= ?' per le parti di chiave, IS NULL per le nulle."""
        parts, params = [], []
        for k in key_columns:
            part = _key_part(row.get(k))
            if part is None:
                parts.append(f"({self._quote(k)} IS NULL OR {self._quote(k)} = '')")
            else:
                parts.append(f"{self._quote(k)} = ?")
                params.append(part)
        return " AND ".join(parts), params

    def _stale_delete(self, table: str, key_columns: list[str], rows: list[dict],
                      range_sql: str, range_params: list) -> int:
        """Cancella le righe nel range che non sono più presenti nell'export."""
        cur = self.conn.cursor()
        key_cols = ", ".join(self._quote(k) for k in key_columns)
        cur.execute(f'SELECT {key_cols} FROM "{table}" WHERE {range_sql}', range_params)
        existing = {tuple(_key_part(v) for v in row) for row in cur.fetchall()}
        incoming = {tuple(_key_part(r.get(k)) for k in key_columns) for r in rows}
        missing = existing - incoming
        if not missing:
            return 0
        clauses, params = [], []
        for key in sorted(missing):
            sub = []
            for col, part in zip(key_columns, key):
                if part is None:
                    sub.append(f"({self._quote(col)} IS NULL OR {self._quote(col)} = '')")
                else:
                    sub.append(f"{self._quote(col)} = ?")
                    params.append(part)
            clauses.append(" AND ".join(sub))
        sql = f'DELETE FROM "{table}" WHERE ({" OR ".join(clauses)}) AND ({range_sql})'
        cur.execute(sql, params + range_params)
        return cur.rowcount if cur.rowcount != -1 else len(missing)

    def upsert_rows(self, table: str, columns: list[str], key_columns: list[str], rows: list[dict],
                    delete_key: str, date_from, date_to, mode: str) -> tuple[int, int]:
        """Upsert (UPDATE+INSERT) per chiave + delete delle righe stale nel range."""
        range_sql, range_params = self._range_placeholders(delete_key, date_from, date_to, mode)
        if not rows:
            # export vuoto: resta solo il delete delle righe stale nel range
            return 0, self._stale_delete(table, key_columns, rows, range_sql, range_params)

        normal, null_key = _split_rows(rows, key_columns)
        cur = self.conn.cursor()

        if normal:
            idx_name = f"idx_{table}_{'_'.join(key_columns)}"
            key_def = ", ".join(self._quote(k) for k in key_columns)
            self._execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ({key_def})')
            non_keys = [c for c in columns if c not in key_columns]
            updates = ", ".join(f'{self._quote(c)} = excluded.{self._quote(c)}' for c in non_keys)
            col_sql = ", ".join(self._quote(c) for c in columns)
            placeholders = ", ".join("?" for _ in columns)
            sql = (
                f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders}) '
                f'ON CONFLICT ({key_def}) DO UPDATE SET {updates}'
            )
            # le colonne-chiave vengono normalizzate (es. 15896373.0 -> '15896373')
            # così int/float/string coincidono e l'ON CONFLICT scatta davvero
            cur.executemany(
                sql,
                [
                    tuple(
                        _key_part(r.get(c)) if c in key_columns else _to_db_value(r.get(c))
                        for c in columns
                    )
                    for r in normal
                ],
            )

        if null_key:
            # chiave parzialmente nulla: in SQL NULL != NULL, quindi per essere
            # idempotenti si fa delete (match parziale) + insert (replace)
            col_sql = ", ".join(self._quote(c) for c in columns)
            placeholders = ", ".join("?" for _ in columns)
            insert_sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})'
            for row in null_key:
                clause, key_params = self._key_match_clause(key_columns, row)
                cur.execute(f'DELETE FROM "{table}" WHERE {clause} AND ({range_sql})', key_params + range_params)
                values = tuple(_to_db_value(row.get(c)) for c in columns)
                cur.execute(insert_sql, values)

        deleted = self._stale_delete(table, key_columns, rows, range_sql, range_params)
        return len(rows), deleted

    def run_stored_procedure(self, name: str) -> None:
        from .sp_orders_global import run_orders_global_sqlite

        run_orders_global_sqlite(self)

    def row_count(self, table: str) -> int:
        cur = self._execute(f'SELECT COUNT(*) FROM "{table}"')
        return int(cur.fetchone()[0])

    def query(self, sql: str) -> list[tuple]:
        cur = self._execute(sql)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# SQL Server backend (live)
# ---------------------------------------------------------------------------
class SqlServerBackend:
    name = "sql-server"

    def __init__(self, sql_config: dict) -> None:
        self.sql_config = sql_config
        self.conn = None

    def connect(self) -> None:
        if pyodbc is None:
            raise DatabaseError(
                "pyodbc non disponibile. Installa un driver ODBC per SQL Server e "
                "'pip install pyodbc' (richiesto per la modalità live)."
            )
        available = {d.lower(): d for d in pyodbc.drivers()}
        candidates = []
        if self.sql_config.get("driver"):
            candidates.append(self.sql_config["driver"])
        candidates.extend(ODBC_DRIVER_CANDIDATES)
        errors = []
        for driver in candidates:
            matched = available.get(driver.lower(), driver)
            if matched.lower() not in available:
                continue
            parts = [
                f"DRIVER={{{matched}}}",
                f"SERVER={self.sql_config['server']}",
                f"DATABASE={self.sql_config['database']}",
                f"UID={self.sql_config['username']}",
                f"PWD={self.sql_config['password']}",
            ]
            if "ODBC Driver 17" in matched or "ODBC Driver 18" in matched:
                parts.append("TrustServerCertificate=yes")
            try:
                self.conn = pyodbc.connect(";".join(parts) + ";", timeout=30)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{matched}: {exc}")
        drivers_text = ", ".join(pyodbc.drivers()) or "nessuno"
        raise DatabaseError(
            f"Connessione SQL Server fallita (server={self.sql_config['server']}). "
            f"Driver disponibili: {drivers_text}. Tentativi: {' | '.join(errors) if errors else 'nessuno'}"
        )

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def commit(self) -> None:
        if self.conn is not None:
            self.conn.commit()

    def rollback(self) -> None:
        if self.conn is not None:
            self.conn.rollback()

    def validate_table(self, table: str, columns: list[str]) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?",
            (table,),
        )
        existing = {row[0] for row in cur.fetchall()}
        return [c for c in columns if c not in existing]

    def delete_range(self, table: str, key: str, date_from, date_to, mode: str) -> int:
        sql = build_delete_sql(table, key, date_from, date_to, mode)
        cur = self.conn.cursor()
        cur.execute(sql)
        return cur.rowcount if cur.rowcount != -1 else 0

    def insert_rows(self, table: str, columns: list[str], rows: list[dict]) -> int:
        if not rows:
            return 0
        col_list = ", ".join(f"[{c}]" for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})"
        cur = self.conn.cursor()
        cur.executemany(sql, [tuple(r.get(c) for c in columns) for r in rows])
        return cur.rowcount if cur.rowcount != -1 else len(rows)

    def _quote(self, name: str) -> str:
        return f"[{name}]"

    def _range_placeholders(self, key: str, date_from, date_to, mode: str) -> tuple[str, list]:
        if mode == "range":
            return f"[{key}] >= ? AND [{key}] <= ?", [date_from, date_to]
        if mode == "open_ended_from":
            return f"[{key}] > ?", [date_from]
        if mode == "year_range":
            return f"[{key}] >= ? AND [{key}] <= ?", [int(date_from), int(date_to)]
        raise DatabaseError(f"Modalità sconosciuta: {mode}")

    def _key_match_clause(self, key_columns: list[str], row: dict) -> tuple[str, list]:
        """WHERE per una singola riga: '= ?' per le parti di chiave, IS NULL per le nulle."""
        parts, params = [], []
        for k in key_columns:
            part = _key_part(row.get(k))
            if part is None:
                parts.append(f"({self._quote(k)} IS NULL OR {self._quote(k)} = '')")
            else:
                parts.append(f"{self._quote(k)} = ?")
                params.append(part)
        return " AND ".join(parts), params

    def _stale_delete(self, table: str, key_columns: list[str], rows: list[dict],
                      range_sql: str, range_params: list) -> int:
        """Cancella le righe nel range che non sono più presenti nell'export."""
        cur = self.conn.cursor()
        key_cols = ", ".join(self._quote(k) for k in key_columns)
        cur.execute(f"SELECT {key_cols} FROM [{table}] WHERE {range_sql}", range_params)
        existing = {tuple(_key_part(v) for v in row) for row in cur.fetchall()}
        incoming = {tuple(_key_part(r.get(k)) for k in key_columns) for r in rows}
        missing = existing - incoming
        if not missing:
            return 0
        clauses, params = [], []
        for key in sorted(missing):
            sub = []
            for col, part in zip(key_columns, key):
                if part is None:
                    sub.append(f"({self._quote(col)} IS NULL OR {self._quote(col)} = '')")
                else:
                    sub.append(f"{self._quote(col)} = ?")
                    params.append(part)
            clauses.append(" AND ".join(sub))
        sql = f"DELETE FROM [{table}] WHERE ({') OR ('.join(clauses)}) AND ({range_sql})"
        cur.execute(sql, params + range_params)
        return cur.rowcount if cur.rowcount != -1 else len(missing)

    def upsert_rows(self, table: str, columns: list[str], key_columns: list[str], rows: list[dict],
                    delete_key: str, date_from, date_to, mode: str) -> tuple[int, int]:
        """Upsert (MERGE per-riga: UPDATE+INSERT) + delete delle righe stale nel range."""
        range_sql, range_params = self._range_placeholders(delete_key, date_from, date_to, mode)
        if not rows:
            # export vuoto: resta solo il delete delle righe stale nel range
            return 0, self._stale_delete(table, key_columns, rows, range_sql, range_params)

        normal, null_key = _split_rows(rows, key_columns)
        cur = self.conn.cursor()

        if normal:
            non_keys = [c for c in columns if c not in key_columns]
            src_cols = ", ".join(f"? AS {self._quote(c)}" for c in columns)
            # le chiavi datetime richiedono CONVERT con stile 120 (ISO), altrimenti
            # il confronto non combacia mai e l'upsert duplica le righe a ogni run.
            # La scelta dello stile guarda TUTTE le righe: se una qualunque chiave
            # è una data, si usa lo stile 120 (i valori misti sono un errore dei dati).
            sample = {k: next((r.get(k) for r in normal if isinstance(r.get(k), (datetime.datetime, datetime.date))), None)
                      for k in key_columns}
            on_clause = " AND ".join(
                f"{_key_convert_expr(self._quote(k), sample[k])} = s.{self._quote(k)}"
                for k in key_columns
            )
            update_set = ", ".join(f"t.{self._quote(c)} = s.{self._quote(c)}" for c in non_keys)
            insert_cols = ", ".join(self._quote(c) for c in columns)
            insert_vals = ", ".join(f"s.{self._quote(c)}" for c in columns)
            merge_sql = (
                f"MERGE INTO [{table}] AS t "
                f"USING (SELECT {src_cols}) AS s "
                f"ON {on_clause} "
                f"WHEN MATCHED THEN UPDATE SET {update_set} "
                f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals});"
            )
            params = [
                tuple(_key_part(r.get(c)) if c in key_columns else r.get(c) for c in columns)
                for r in normal
            ]
            cur.executemany(merge_sql, params)

        if null_key:
            # chiave parzialmente nulla: in SQL NULL != NULL, quindi per essere
            # idempotenti si fa delete (match parziale) + insert (replace)
            col_list = ", ".join(f"[{c}]" for c in columns)
            placeholders = ", ".join("?" for _ in columns)
            insert_sql = f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})"
            for row in null_key:
                clause, key_params = self._key_match_clause(key_columns, row)
                cur.execute(
                    f"DELETE FROM [{table}] WHERE {clause} AND ({range_sql})", key_params + range_params
                )
                values = tuple(row.get(c) for c in columns)
                cur.execute(insert_sql, values)

        deleted = self._stale_delete(table, key_columns, rows, range_sql, range_params)
        return len(rows), deleted

    def run_stored_procedure(self, name: str) -> None:
        cur = self.conn.cursor()
        cur.execute(f"EXEC [dbo].[{name}]")
        while cur.nextset():
            pass


def create_backend(kind: str, **kwargs):
    if kind == "sqlite":
        return SqliteBackend(kwargs["db_path"])
    if kind == "sqlserver":
        return SqlServerBackend(kwargs["sql_config"])
    raise DatabaseError(f"Backend sconosciuto: {kind}")
