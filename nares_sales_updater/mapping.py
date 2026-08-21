"""Risoluzione e validazione del mapping colonne export -> tabelle DB."""
from __future__ import annotations

import re

from .config import ConfigError


class Mapping:
    """Per una tabella: lista ordinata di (colonna_target, colonna_sorgente)."""

    def __init__(self, target_columns: list[str], source_columns: list[str]) -> None:
        self.target_columns = list(target_columns)
        self.source_columns = list(source_columns)

    def validate(self) -> list[str]:
        """Controlla che ogni colonna sorgente esista; ritorna le colonne export ignorate."""
        available = set(self.source_columns)
        for src in self.source_columns:
            if src not in available:
                raise ConfigError(f"Colonna sorgente '{src}' non trovata nell'export")
        return sorted(available - set(self.source_columns))


def snake_case(header: str) -> str:
    h = str(header).strip().replace("Nr.", "Nr").replace("eMail", "email").replace("EMail", "email")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", h)
    s = s.replace(" ", "_").lower()
    return s


def resolve_explicit(columns: list[dict], headers: list[str]) -> Mapping:
    target, source = [], []
    for item in columns:
        target.append(item["target"])
        source.append(item["source"])
    mapping = Mapping(target, source)
    mapping.validate()
    return mapping


def resolve_snake_case(db_columns: list[str], headers: list[str], drop: list[str]) -> Mapping:
    keep = [h for h in headers if h not in drop]
    renamed = [snake_case(h) for h in keep]
    if renamed != db_columns:
        for a, b in zip(renamed, db_columns):
            if a != b:
                raise ConfigError(
                    f"Mapping snake_case non allineato con le colonne DB: {a!r} != {b!r} "
                    "(l'export è cambiato? rigenera config.json con tools/generate_config.py)"
                )
        raise ConfigError(
            f"Mapping snake_case: {len(renamed)} colonne derivate vs {len(db_columns)} attese dal DB"
        )
    mapping = Mapping(db_columns, keep)
    ignored = mapping.validate()
    return mapping


def resolve_ingressi(db_columns: list[str], headers: list[str]) -> Mapping:
    expected = ["Negozio", "Data", "Anno", "Mese", "n° Visite"]
    missing = [e for e in expected if e not in headers]
    if missing:
        raise ConfigError(f"Rapportino visite: colonne attese mancanti: {missing}")
    mapping = Mapping(db_columns, ["Negozio", "Data", "Anno", "Mese", "n° Visite"])
    return mapping


def resolve_mapping(config: dict, export_key: str, headers: list[str]) -> tuple[Mapping, list[str]]:
    """Ritorna (Mapping, colonne export ignorate)."""
    mapping_cfg = config["mappings"][export_key]
    mode = mapping_cfg.get("mode", "explicit")
    if mode == "explicit":
        mapping = resolve_explicit(mapping_cfg["columns"], headers)
    elif mode == "rule" and mapping_cfg.get("rule") == "snake_case":
        drop = mapping_cfg.get("drop_columns") or config["exports"][export_key].get("mapping", {}).get("drop_columns", [])
        mapping = resolve_snake_case(mapping_cfg["db_columns"], headers, drop)
    elif mode == "rule" and mapping_cfg.get("rule") == "derive_ingressi":
        mapping = resolve_ingressi(mapping_cfg["db_columns"], headers)
    else:
        raise ConfigError(f"Modalità mapping sconosciuta per '{export_key}': {mode}")
    return mapping, sorted(set(headers) - set(mapping.source_columns))
