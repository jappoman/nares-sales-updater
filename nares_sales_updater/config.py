"""Configurazione: legge config.json + variabili d'ambiente (segrete in .env)."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Quando il programma è compilato con PyInstaller (sys.frozen) la cartella di
# lavoro è quella dell'eseguibile: lì devono stare config.json e .env.
APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
CONFIG_PATH = APP_DIR / "config.json"
ENV_PATH = APP_DIR / ".env"

load_dotenv(ENV_PATH)


def _load_env_json() -> None:
    """Il .env esistente è in formato JSON: carica le chiavi in os.environ."""
    if not ENV_PATH.exists():
        return
    try:
        data = json.loads(ENV_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict):
        for key, value in data.items():
            os.environ.setdefault(str(key), str(value))


_load_env_json()


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise ConfigError(f"config.json non trovato: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json non valido: {exc}") from exc


def resolve_secret(config: dict, env_key: str, default: str = "") -> str:
    """Legge una variabile d'ambiente, con fallback a chiavi 'username'/'password' in .env."""
    value = _env(env_key)
    if value:
        return value
    # backward-compat con il vecchio .env che usava chiavi generiche
    legacy = {
        "NARES_USERNAME": "username",
        "NARES_PASSWORD": "password",
        "SQL_SERVER": "host",
        "SQL_USERNAME": "sql_username",
        "SQL_PASSWORD": "sql_password",
    }.get(env_key)
    if legacy:
        value = _env(legacy)
        if value:
            return value
    return default


def nares_credentials(config: dict) -> dict:
    nares = config.get("nares", {})
    username = resolve_secret(nares, nares.get("username_env", "NARES_USERNAME"))
    password = resolve_secret(nares, nares.get("password_env", "NARES_PASSWORD"))
    if not username or not password:
        raise ConfigError(
            "Credenziali NARES mancanti: imposta NARES_USERNAME e NARES_PASSWORD in .env "
            "(la password cambia ogni 3 mesi, aggiornala solo lì)."
        )
    return {"username": username, "password": password}


def sql_config(config: dict) -> dict:
    sql = config.get("sql", {})
    server = resolve_secret(sql, sql.get("server_env", "SQL_SERVER"), sql.get("server_default", ""))
    username = resolve_secret(sql, sql.get("username_env", "SQL_USERNAME"))
    password = resolve_secret(sql, sql.get("password_env", "SQL_PASSWORD"))
    database = sql.get("database", "GenesiRetail")
    if not server or not username or not password:
        raise ConfigError(
            "Configurazione SQL Server incompleta: imposta SQL_SERVER, SQL_USERNAME, SQL_PASSWORD in .env"
        )
    return {
        "server": server,
        "database": database,
        "username": username,
        "password": password,
        "driver": str(sql.get("driver", "")).strip(),
    }


def default_date_ranges(config: dict, today: date | None = None) -> dict:
    """Date di default per le 4 estrazioni, calcolate da oggi."""
    today = today or date.today()
    result = {}
    exports = config.get("exports", {})
    for key, spec in exports.items():
        if "date_from_offset_days" in spec:
            result[key] = {
                "date_from": today - timedelta(days=int(spec["date_from_offset_days"])),
                "date_to": today - timedelta(days=int(spec["date_to_offset_days"])),
            }
        elif "anno_from_offset_years" in spec:
            year_from = today.year + int(spec["anno_from_offset_years"])
            year_to = today.year + int(spec["anno_to_offset_years"])
            result[key] = {"anno_from": year_from, "anno_to": year_to}
    return result
