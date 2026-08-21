"""Generazione script SQL (per revisione e per l'esecuzione live)."""
from __future__ import annotations

import datetime


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "'True'" if value else "'False'"
    if isinstance(value, datetime.datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(value, datetime.date):
        return "'" + value.strftime("%Y-%m-%d") + "'"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return "'" + text + "'"


def build_range_condition(key: str, date_from, date_to, mode: str) -> str:
    """WHERE-clause della condizione di range (T-SQL)."""
    if mode == "range":
        return f"[{key}] >= {sql_literal(date_from)} AND [{key}] <= {sql_literal(date_to)}"
    if mode == "open_ended_from":
        return f"[{key}] > {sql_literal(date_from)}"
    if mode == "year_range":
        return f"[{key}] >= {int(date_from)} AND [{key}] <= {int(date_to)}"
    raise ValueError(f"Modalità delete sconosciuta: {mode}")


def build_delete_sql(table: str, key: str, date_from, date_to, mode: str) -> str:
    return f"DELETE FROM [{table}] WHERE {build_range_condition(key, date_from, date_to, mode)};"


def build_insert_statements(table: str, columns: list[str], rows: list[dict]) -> list[str]:
    col_list = ", ".join(f"[{c}]" for c in columns)
    statements = []
    for row in rows:
        values = ", ".join(sql_literal(row.get(c)) for c in columns)
        statements.append(f"INSERT INTO [{table}] ({col_list}) VALUES ({values});")
    return statements


def build_insert_batch(table: str, columns: list[str], rows: list[dict]) -> str:
    statements = build_insert_statements(table, columns, rows)
    return "\n".join(statements) + ("\n" if statements else "")
