"""Trasformazioni 'pulizia' dei 4 file esportati da NARES.

Replica la logica delle macro VBA (puliziaorders / puliziaordersbydate /
puliziapreventivi + il file Rapportovisite con le formule F-K), ma basandosi
sui NOMI delle colonne invece che sulle lettere, così da essere robusto
all'evoluzione del layout di esportazione Natuzzi.
"""
from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation

from .config import ConfigError
from .mapping import Mapping


def _as_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def normalize_order_number(value) -> str:
    """'15345527.0' -> '15345527', 15345527 -> '15345527', '' -> ''."""
    return _as_string(value).strip()


def to_number(value):
    """Converte il valore in int/float/None come farebbe la macro con Replace(',', '.')."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return _coerce_numeric(value)
    text = str(value).strip().replace(",", ".")
    if text == "":
        return None
    try:
        return _coerce_numeric(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _coerce_numeric(value):
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _normalize_promo(text: str) -> str:
    """Come la macro: normalizza le varianti di 'blocco promo'."""
    lowered = text.lower()
    lowered = lowered.replace("blocco promo", "bloccopromo")
    lowered = lowered.replace("fermo promo", "bloccopromo")
    return lowered


def _is_numeric(value) -> bool:
    """Equivalente di VBA IsNumeric."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    text = str(value).strip()
    if text == "":
        return False
    try:
        Decimal(text.replace(",", "."))
        return True
    except (InvalidOperation, ValueError):
        return False


def _apply_numerics(row: dict, numeric_columns: list[str]) -> dict:
    for col in numeric_columns:
        if col in row:
            row[col] = to_number(row[col])
    return row


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------
def clean_orders(rows: list[dict], mapping: Mapping, blocklist: list[str],
                 numeric_columns: list[str]) -> list[dict]:
    block = {normalize_order_number(b) for b in blocklist}
    cleaned: list[dict] = []
    dropped_empty = dropped_promo = dropped_block = 0

    for raw in rows:
        row = {}
        for target, source in zip(mapping.target_columns, mapping.source_columns):
            row[target] = raw.get(source)

        if not _as_string(row.get("OrderStatus")).strip():
            dropped_empty += 1
            continue

        # Copia ConsumerPlace -> ConsumerCity (macro: T -> S)
        row["ConsumerCity"] = row.get("ConsumerPlace")

        # Riga con "blocco promo" in DeliveryNote -> eliminata (macro: filtra CG)
        delivery_note = _as_string(row.get("DeliveryNote"))
        if "bloccopromo" in _normalize_promo(delivery_note):
            dropped_promo += 1
            continue

        # Ordini bloccati (macro: filtra colonna D = OrderNumber)
        if normalize_order_number(row.get("OrderNumber")) in block:
            dropped_block += 1
            continue

        # Arrotonda Quantities / InvoicedQuantities (macro: ROUND(...,0))
        for qcol in ("Quantities", "InvoicedQuantities"):
            number = to_number(row.get(qcol))
            row[qcol] = int(round(number)) if number is not None else None

        cleaned.append(_apply_numerics(row, numeric_columns))

    stats = {
        "input_rows": len(rows),
        "output_rows": len(cleaned),
        "dropped_empty": dropped_empty,
        "dropped_promo": dropped_promo,
        "dropped_blocklist": dropped_block,
    }
    return cleaned, stats


# ---------------------------------------------------------------------------
# ordersByDate
# ---------------------------------------------------------------------------
def clean_orders_by_date(rows: list[dict], mapping: Mapping, blocklist: list[str],
                         numeric_columns: list[str]) -> list[dict]:
    block = {normalize_order_number(b) for b in blocklist}
    cleaned: list[dict] = []
    dropped_empty = dropped_block = cleared_cap = cleared_cat = 0

    for raw in rows:
        row = {}
        for target, source in zip(mapping.target_columns, mapping.source_columns):
            row[target] = raw.get(source)

        if not _as_string(row.get("idStatoOrdine")).strip():
            dropped_empty += 1
            continue

        if normalize_order_number(row.get("numOrdine")) in block:
            dropped_block += 1
            continue

        # Colonne che devono contenere solo numeri (macro: IsNumeric else "")
        for col in ("cap", "cdCategoriaRivestimento"):
            if not _is_numeric(row.get(col)):
                if _as_string(row.get(col)):
                    cleared_cap += 1 if col == "cap" else 0
                    cleared_cat += 1 if col == "cdCategoriaRivestimento" else 0
                row[col] = None

        # Copia localita -> descrComune (macro: BK -> BM)
        row["descrComune"] = row.get("localita")

        cleaned.append(_apply_numerics(row, numeric_columns))

    stats = {
        "input_rows": len(rows),
        "output_rows": len(cleaned),
        "dropped_empty": dropped_empty,
        "dropped_blocklist": dropped_block,
        "cleared_cap": cleared_cap,
        "cleared_categoria": cleared_cat,
    }
    return cleaned, stats


# ---------------------------------------------------------------------------
# preventivi
# ---------------------------------------------------------------------------
def clean_preventivi(rows: list[dict], mapping: Mapping, numeric_columns: list[str]) -> list[dict]:
    cleaned: list[dict] = []
    skipped = 0
    for raw in rows:
        row = {}
        for target, source in zip(mapping.target_columns, mapping.source_columns):
            row[target] = raw.get(source)
        if not any(_as_string(v).strip() for v in row.values()):
            skipped += 1
            continue
        cleaned.append(_apply_numerics(row, numeric_columns))
    stats = {"input_rows": len(rows), "output_rows": len(cleaned), "dropped_empty": skipped}
    return cleaned, stats


# ---------------------------------------------------------------------------
# ingressi (rapportino visite) — replica delle formule F-K del file Rapportovisite
# ---------------------------------------------------------------------------
_STORE_PATTERN = re.compile(r"^(.*?)\s*\((\d{5,})\)\s*$")


def derive_ingressi(rows: list[dict], mapping: Mapping, numeric_columns: list[str]) -> list[dict]:
    cleaned: list[dict] = []
    skipped = 0
    for raw in rows:
        negozio = _as_string(raw.get("Negozio"))
        match = _STORE_PATTERN.match(negozio)
        if not match:
            skipped += 1
            continue
        cd_store = int(match.group(2))
        store = match.group(1).strip()
        data = raw.get("Data")
        if isinstance(data, datetime.datetime):
            data_value = data
        elif isinstance(data, datetime.date):
            data_value = datetime.datetime(data.year, data.month, data.day)
        elif _as_string(data).strip():
            try:
                data_value = datetime.datetime.strptime(str(data).strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                data_value = str(data)
        else:
            data_value = None
        try:
            anno = int(float(_as_string(raw.get("Anno"))))
            mese = int(float(_as_string(raw.get("Mese"))))
            ingressi = int(float(_as_string(raw.get("n° Visite"))))
        except (ValueError, TypeError):
            skipped += 1
            continue
        row = {
            "cdStore": cd_store,
            "store": store,
            "data": data_value,
            "anno": anno,
            "mese": mese,
            "ingressi": ingressi,
        }
        cleaned.append(row)
    stats = {"input_rows": len(rows), "output_rows": len(cleaned), "dropped_unparsable": skipped}
    return cleaned, stats


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
CLEANERS = {
    "orders": clean_orders,
    "ordersByDate": clean_orders_by_date,
    "preventivi": clean_preventivi,
    "ingressi": derive_ingressi,
}


def clean_export(export_key: str, rows: list[dict], mapping: Mapping,
                 config: dict) -> tuple[list[dict], dict]:
    cleaner = CLEANERS.get(export_key)
    if cleaner is None:
        raise ConfigError(f"Nessuna pulizia definita per '{export_key}'")
    spec = config["exports"][export_key]
    blocklist = config.get("orders_blocklist", [])
    numeric = spec.get("numeric_columns", [])
    if export_key in ("orders", "ordersByDate"):
        return cleaner(rows, mapping, blocklist, numeric)
    return cleaner(rows, mapping, numeric)
