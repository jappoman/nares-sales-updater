#!/usr/bin/env python3
"""CLI di nares-sales-updater.

Modalità:
  python main.py                          # dry-run: elabora i file e genera SQL (nessun write DB)
  python main.py --use-files DIR          # usa file già scaricati (es. docs/res/file di esempio)
  python main.py --demo-db                # dry-run + demo completa su SQLite (nessun write sul DB vero)
  python main.py --live --yes             # download reale + scrittura sul DB SQL Server
  python main.py --auto                   # esecuzione schedulata: range di default + download + DB

I file scaricati finiscono in out/downloaded/, i file puliti in out/cleaned/,
gli script SQL in out/sql/.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date
from pathlib import Path

from nares_sales_updater import cleaning
from nares_sales_updater import config as cfg
from nares_sales_updater import excel_io, mapping, sql_scripts
from nares_sales_updater.log_util import create_run_logger


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scarica, pulisce e carica i dati NARES.")
    parser.add_argument("--date-from", help="Data iniziale YYYY-MM-DD (default: calcolata da config)")
    parser.add_argument("--date-to", help="Data finale YYYY-MM-DD (default: calcolata da config)")
    parser.add_argument("--live", action="store_true", help="Esegue download reale e scrittura sul DB SQL Server")
    parser.add_argument("--yes", action="store_true", help="Salta la conferma interattiva in modalità live")
    parser.add_argument("--auto", action="store_true",
                        help="Esecuzione automatica (Task Scheduler): range di default, download e scrittura sul DB")
    parser.add_argument("--demo-db", metavar="PATH", nargs="?", const="out/demo.db",
                        help="Esegue anche la demo end-to-end su SQLite (nessun write sul DB vero)")
    parser.add_argument("--use-files", metavar="DIR", help="Usa i file esportati già presenti in DIR")
    parser.add_argument("--no-download", action="store_true", help="Non scaricare da NARES (richiede --use-files)")
    parser.add_argument("--out", default="out", help="Cartella di output (default: out/)")
    return parser.parse_args(argv[1:])


def load_export_files(use_files: str | None, no_download: bool, out_dir: Path, config: dict, ranges: dict,
                      logger) -> dict[str, Path]:
    """Ritorna {export_key: path} dei 4 file da elaborare."""
    if use_files:
        base = Path(use_files)
        found = {}
        for key, spec in config["exports"].items():
            candidate = base / spec["download_name"]
            if not candidate.exists():
                raise FileNotFoundError(f"File atteso non trovato in {base}: {spec['download_name']}")
            found[key] = candidate
        logger(f"Uso file esistenti da {base}")
        return found

    if no_download:
        raise SystemExit("--no-download richiede anche --use-files DIR (o file in out/downloaded/).")

    download_dir = out_dir / "downloaded"
    from nares_sales_updater import nares_exporter

    credentials = cfg.nares_credentials(config)
    logger("Download da NARES (richiede accesso al portale)...")
    return nares_exporter.download_all_exports(config, credentials, ranges, download_dir, logger)


def date_ranges(config: dict, date_from: str | None, date_to: str | None) -> dict:
    ranges = cfg.default_date_ranges(config)
    if date_from and date_to:
        from_date = date.fromisoformat(date_from)
        to_date = date.fromisoformat(date_to)
        for key in ("orders", "ordersByDate", "preventivi"):
            if key in ranges:
                ranges[key] = {"date_from": from_date, "date_to": to_date}
        ranges["ingressi"] = {"anno_from": from_date.year, "anno_to": to_date.year}
    return ranges


def process_export(config: dict, export_key: str, path: Path, out_dir: Path,
                   logger) -> tuple[list[dict], list[str], dict]:
    spec = config["exports"][export_key]
    rows = excel_io.read_excel(path, spec.get("sheet"))
    headers = excel_io.read_headers(path, spec.get("sheet"))
    column_map, ignored = mapping.resolve_mapping(config, export_key, headers)
    cleaned, stats = cleaning.clean_export(export_key, rows, column_map, config)

    if ignored:
        logger(f"  [warn] colonne export ignorate ({export_key}): {', '.join(ignored)}")

    cleaned_path = out_dir / "cleaned" / spec["download_name"]
    excel_io.write_cleaned_excel(cleaned_path, column_map.target_columns, cleaned)
    logger(
        f"  {export_key}: {stats['input_rows']} righe -> {stats['output_rows']} "
        f"({json.dumps({k: v for k, v in stats.items() if k not in ('input_rows', 'output_rows')})})"
    )
    return cleaned, column_map.target_columns, stats


def write_sql_script(out_dir: Path, export_key: str, table: str, columns: list[str],
                     rows: list[dict], date_range: dict, delete_cfg: dict, strategy: str | None = None,
                     key_columns: list[str] | None = None) -> Path:
    delete_sql = sql_scripts.build_delete_sql(
        table, delete_cfg["key"], date_range.get("date_from", date_range.get("anno_from")),
        date_range.get("date_to", date_range.get("anno_to")), delete_cfg["mode"],
    )
    inserts = sql_scripts.build_insert_statements(table, columns, rows)
    strategy_note = ""
    if strategy == "upsert":
        strategy_note = (
            f"-- strategia: UPSERT (chiave: {', '.join(key_columns or [])}); "
            f"le righe stale nel range vengono cancellate, il DELETE sotto è solo di riferimento\n"
        )
    else:
        strategy_note = "-- strategia: DELETE + INSERT\n"
    text = "\n".join(
        [f"-- {export_key}: {len(rows)} righe", strategy_note.rstrip(), delete_sql, ""] + inserts
    ) + "\n"
    path = out_dir / "sql" / f"{export_key}.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_demo_db(demo_path: Path, config: dict, cleaned: dict[str, tuple[list[dict], list[str]]],
                date_ranges: dict, logger) -> None:
    from nares_sales_updater.demo import run_demo

    run_demo(demo_path, config, cleaned, date_ranges, logger)


def run_live(config: dict, cleaned: dict[str, tuple[list[dict], list[str]]],
             date_ranges: dict, yes: bool, logger) -> None:
    from nares_sales_updater import db

    if not yes:
        answer = input(
            "ATTENZIONE: scriverai sul database reale (DELETE + INSERT + stored procedure). "
            "Digitare 'SI' per continuare: "
        )
        if answer.strip().upper() != "SI":
            logger("Operazione annullata dall'utente.")
            return

    sql_conf = cfg.sql_config(config)
    # se una delle 4 estrazioni è vuota (estrazione fallita) non si scrive nulla:
    # il merger ricostruirebbe ordersGlobal mescolando dati vecchi e nuovi
    empty = [k for k, (rows, _cols) in cleaned.items() if not rows]
    if empty:
        raise RuntimeError(
            f"Estrazioni vuote ({', '.join(empty)}): esecuzione interrotta, nessuna scrittura sul DB. "
            "Controlla che i download siano andati a buon fine."
        )
    backend = db.SqlServerBackend(sql_conf)
    backend.connect()
    try:
        for export_key, (rows, columns) in cleaned.items():
            spec = config["exports"][export_key]
            table = spec["table"]
            missing = backend.validate_table(table, columns)
            if missing:
                raise RuntimeError(f"Tabella {table}: colonne mancanti nel DB: {missing}")
            processed, deleted = db.apply_strategy(backend, spec, columns, rows, date_ranges[export_key], logger)
            strategy = spec.get("strategy", "delete_insert")
            logger(f"  {table} [{strategy}]: {processed} righe processate, {deleted} righe eliminate")
        proc = config["stored_procedure"]
        logger(f"Eseguo stored procedure {proc}...")
        backend.run_stored_procedure(proc)
        logger("Stored procedure completata.")
        backend.commit()
    except Exception:
        # nessuna modifica parziale: se qualcosa fallisce si annulla tutto
        try:
            backend.rollback()
        except Exception:
            pass
        raise
    finally:
        backend.close()


def run_job(date_from: str | None = None, date_to: str | None = None, *,
            live: bool = False, yes: bool = False, demo_db: str | None = None,
            use_files: str | None = None, no_download: bool = False,
            out_dir: str = "out", logger=print) -> int:
    """Esegue il flusso completo. Ritorna 0 in caso di successo."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        config = cfg.load_config(cfg.APP_DIR / "config.json")
        ranges = date_ranges(config, date_from, date_to)
        files = load_export_files(use_files, no_download, out, config, ranges, logger)

        cleaned: dict[str, tuple[list[dict], list[str]]] = {}
        for key in config["exports"]:
            rows, columns, _stats = process_export(config, key, files[key], out, logger)
            spec = config["exports"][key]
            write_sql_script(out, key, spec["table"], columns, rows,
                             ranges[key], spec["delete"], spec.get("strategy"), spec.get("key_columns"))
            cleaned[key] = (rows, columns)
        logger("Script SQL scritti in out/sql/")

        if demo_db:
            run_demo_db(Path(demo_db), config, cleaned, ranges, logger)
        elif live:
            run_live(config, cleaned, ranges, yes, logger)
        else:
            logger("DRY-RUN: nessuna scrittura su database (usa --demo-db per la demo SQLite o --live per il DB reale).")

        return 0
    except (cfg.ConfigError, RuntimeError, FileNotFoundError, KeyError) as exc:
        logger(f"Errore: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        logger(f"Errore non gestito: {exc}")
        logger(traceback.format_exc().rstrip())
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv)
    logger = create_run_logger(sink=print, prefix="nares", logs_dir=cfg.APP_DIR / "logs")
    logger(f"Log: {logger.log_path}")

    if args.auto:
        if args.date_from or args.date_to or args.demo_db or args.use_files or args.no_download:
            logger("Errore: --auto non ammette --date-from/--date-to, --demo-db, --use-files o --no-download.")
            return 1
        args.live = True
        args.yes = True
        logger("Modalità automatica: range di default, download da NARES e scrittura sul DB.")

    # I percorsi relativi (out/, demo.db) partono dalla cartella del programma,
    # così l'esito non dipende dalla directory di lancio (Task Scheduler incluso).
    out_arg = Path(args.out)
    out_dir = out_arg if out_arg.is_absolute() else cfg.APP_DIR / out_arg
    demo_db = None
    if args.demo_db:
        demo_path = Path(args.demo_db)
        demo_db = str(demo_path if demo_path.is_absolute() else cfg.APP_DIR / demo_path)

    return run_job(
        args.date_from, args.date_to,
        live=args.live, yes=args.yes, demo_db=demo_db,
        use_files=args.use_files, no_download=args.no_download,
        out_dir=str(out_dir), logger=logger,
    )


if __name__ == "__main__":
    raise SystemExit(main())
