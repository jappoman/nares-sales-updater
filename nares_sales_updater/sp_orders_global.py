"""Traduzione Python della stored procedure Create_ordersGlobal per la demo SQLite.

Solo la demo usa questa implementazione: la modalità live esegue la vera stored
procedure T-SQL (sql/Create_ordersGlobal.sql) via pyodbc.
La logica replica fedelmente il merger: ordersByDate JOIN orders -> ordersGlobal,
più le tabelle derivate ordersGlobalOrd / ordersGlobalDTOrd / markupGlobal.
Le tabelle di supporto Anagrafica e Codifica_Store sono stub vuote in demo.
"""
from __future__ import annotations

import datetime

from .db import SqliteBackend

PROTECTION_TYPES = ("Piano Protezione Aggiuntiva", "Piano di protezione")

ORDERS_GLOBAL_COLUMNS = [
    "idStatoOrdine", "statoOrdine", "idTipoOrdine", "tipoOrdine", "Brand",
    "numPreventivo", "cognomeSelQuotation", "nomeSelQuotation", "numOrdine",
    "numOrdineRiferimento", "idSeller", "nomeCognome", "cognomeSel", "nomeSel",
    "idConsumer", "cognomeCns", "nomeCns", "cdStore", "store", "cdAffiliato",
    "dtOrdine", "dtRichiesta", "dtMakeDefinitive", "dtCancel",
    "CompleteReceivingDate", "tipoFinanziamento", "numRate", "importoDaFinanziare",
    "idTipoRiga", "cdListino", "tipoRiga", "isProntaConsegna", "isOmaggio",
    "cdArticolo", "Article", "po", "dtInvoiceB2B", "cdAlias", "cdRivestimento",
    "cdCategoriaRivestimento", "Iva", "aliquotaIva", "qtaOrdinata", "totaleSedute",
    "totalePesoNetto", "totalePesoLordo", "totaleVolume", "selloutTeorico", "sconto",
    "importoScontatoNetto", "importoScontato", "selloutRealeNetto", "selloutReale",
    "consensoMarketing", "consensoProfiling", "consensoTeleMarketing",
    "consensoThirdParties", "consensoPrivacy", "telefonoCasa", "telefonoMobile",
    "telefonoUfficio", "descrTipoVie", "nomeVia", "civicoVia", "localita", "cap",
    "descrComune", "Acconto", "AccontoContabilizzato", "saldo",
    "dataCaricoMagazzino", "valoreAcquisto", "cdListinoAcquisto",
    "MetodiPagamentoAccontoContabilizzato",
]

ORDERS_GLOBAL_ORD_COLUMNS = [
    "idStatoOrdine", "statoOrdine", "tipoOrdine", "numOrdine", "cognomeSel",
    "nomeSel", "cdStore", "store", "dtOrdine",
    "MetodiPagamentoAccontoContabilizzato", "tipoFinanziamento", "numRate",
    "importoDaFinanziare", "totaleSedute", "selloutTeorico",
    "importoScontatoNetto", "importoScontato", "selloutRealeNetto",
    "selloutReale", "valoreAcquisto", "Acconto", "AccontoContabilizzato", "saldo",
]

MARKUP_COLUMNS = [
    "deliverydate", "cdStore", "store", "OrderStatus", "tipoOrdine", "numOrdine",
    "selloutRealeNetto", "ArticleType", "Article", "ArticleCode", "valoreAcquisto",
    "dtOrdine", "Seats",
]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_store_manager(db: SqliteBackend, nome, cognome) -> bool:
    rows = db.query(
        'SELECT "storeManager" FROM "Anagrafica" WHERE "Nome" = \'%s\' AND "Cognome" = \'%s\''
        % (str(nome or "").replace("'", "''"), str(cognome or "").replace("'", "''"))
    )
    return bool(rows) and rows[0][0] == "1"


def _store_nares(db: SqliteBackend, nome_store):
    rows = db.query(
        "SELECT \"store_nares\" FROM \"Codifica_Store\" WHERE \"nome_nares\" = '%s'"
        % str(nome_store).replace("'", "''")
    )
    return rows[0][0] if rows else None


def _fetch_table(db: SqliteBackend, table: str) -> list[dict]:
    rows = db.query(f'SELECT * FROM "{table}"')
    cur = db.conn.cursor()
    cur.execute(f'SELECT * FROM "{table}" LIMIT 0')
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def _insert_rows(db: SqliteBackend, table: str, rows: list[dict], columns: list[str]) -> None:
    db.create_table(table, columns)
    db._execute(f'DELETE FROM "{table}"')  # TRUNCATE
    db.insert_rows(table, columns, rows)


def run_orders_global_sqlite(db: SqliteBackend) -> dict:
    db.ensure_stub_tables()
    orders = _fetch_table(db, "orders")
    obd = _fetch_table(db, "ordersByDate")

    # ---- ordersGlobal ----
    obd_by_key = {}
    for r in obd:
        obd_by_key.setdefault((r.get("dtOrdine"), r.get("numOrdine"), r.get("cdArticolo")), []).append(r)
    orders_by_key = {}
    for r in orders:
        orders_by_key.setdefault((r.get("OrderDate"), r.get("OrderNumber"), r.get("ArticleCode")), []).append(r)

    union_rows: dict[tuple, dict] = {}

    # Parte 1: ordersByDate JOIN orders, esclusi i tipi 'Piano di protezione*'
    for key, obd_rows in obd_by_key.items():
        for o in orders_by_key.get(key, []):
            for od in obd_rows:
                if od.get("tipoRiga") in PROTECTION_TYPES:
                    continue
                nome_cognome = f"{od.get('nomeSel')} {od.get('cognomeSel')}"
                if _is_store_manager(db, od.get("nomeSel"), od.get("cognomeSel")):
                    nome_cognome = f"*(S) {nome_cognome}"
                va = _num(od.get("valoreAcquisto"))
                if va == 0 or od.get("valoreAcquisto") is None:
                    va = (_num(od.get("selloutRealeNetto")) / 1.22) * 0.5
                row = {
                    "idStatoOrdine": od.get("idStatoOrdine"),
                    "statoOrdine": od.get("statoOrdine"),
                    "idTipoOrdine": od.get("idTipoOrdine"),
                    "tipoOrdine": od.get("tipoOrdine"),
                    "Brand": od.get("Brand"),
                    "numPreventivo": od.get("numPreventivo"),
                    "cognomeSelQuotation": od.get("cognomeSelQuotation"),
                    "nomeSelQuotation": od.get("nomeSelQuotation"),
                    "numOrdine": od.get("numOrdine"),
                    "numOrdineRiferimento": od.get("numOrdineRiferimento"),
                    "idSeller": od.get("idSeller"),
                    "nomeCognome": nome_cognome,
                    "cognomeSel": od.get("cognomeSel"),
                    "nomeSel": od.get("nomeSel"),
                    "idConsumer": od.get("idConsumer"),
                    "cognomeCns": od.get("cognomeCns"),
                    "nomeCns": od.get("nomeCns"),
                    "cdStore": od.get("cdStore"),
                    "store": od.get("store"),
                    "cdAffiliato": od.get("cdAffiliato"),
                    "dtOrdine": od.get("dtOrdine"),
                    "dtRichiesta": od.get("dtRichiesta"),
                    "dtMakeDefinitive": od.get("dtMakeDefinitive"),
                    "dtCancel": od.get("dtCancel"),
                    "CompleteReceivingDate": od.get("CompleteReceivingDate"),
                    "tipoFinanziamento": od.get("tipoFinanziamento"),
                    "numRate": od.get("numRate"),
                    "importoDaFinanziare": od.get("importoDaFinanziare"),
                    "idTipoRiga": od.get("idTipoRiga"),
                    "cdListino": od.get("cdListino"),
                    "tipoRiga": od.get("tipoRiga"),
                    "isProntaConsegna": od.get("isProntaConsegna"),
                    "isOmaggio": od.get("isOmaggio"),
                    "cdArticolo": od.get("cdArticolo"),
                    "Article": o.get("Article"),
                    "po": od.get("po"),
                    "dtInvoiceB2B": od.get("dtInvoiceB2B"),
                    "cdAlias": od.get("cdAlias"),
                    "cdRivestimento": od.get("cdRivestimento"),
                    "cdCategoriaRivestimento": od.get("cdCategoriaRivestimento"),
                    "Iva": od.get("Iva"),
                    "aliquotaIva": od.get("aliquotaIva"),
                    "qtaOrdinata": od.get("qtaOrdinata"),
                    "totaleSedute": od.get("totaleSedute"),
                    "totalePesoNetto": od.get("totalePesoNetto"),
                    "totalePesoLordo": od.get("totalePesoLordo"),
                    "totaleVolume": od.get("totaleVolume"),
                    "selloutTeorico": od.get("selloutTeorico"),
                    "sconto": od.get("sconto"),
                    "importoScontatoNetto": od.get("importoScontatoNetto"),
                    "importoScontato": od.get("importoScontato"),
                    "selloutRealeNetto": od.get("selloutRealeNetto"),
                    "selloutReale": od.get("selloutReale"),
                    "consensoMarketing": od.get("consensoMarketing"),
                    "consensoProfiling": od.get("consensoProfiling"),
                    "consensoTeleMarketing": od.get("consensoTeleMarketing"),
                    "consensoThirdParties": od.get("consensoThirdParties"),
                    "consensoPrivacy": od.get("consensoPrivacy"),
                    "telefonoCasa": od.get("telefonoCasa"),
                    "telefonoMobile": od.get("telefonoMobile"),
                    "telefonoUfficio": od.get("telefonoUfficio"),
                    "descrTipoVie": od.get("descrTipoVie"),
                    "nomeVia": od.get("nomeVia"),
                    "civicoVia": od.get("civicoVia"),
                    "localita": od.get("localita"),
                    "cap": od.get("cap"),
                    "descrComune": od.get("descrComune"),
                    "Acconto": od.get("Acconto"),
                    "AccontoContabilizzato": od.get("AccontoContabilizzato"),
                    "saldo": od.get("saldo"),
                    "dataCaricoMagazzino": od.get("dataCaricoMagazzino"),
                    "valoreAcquisto": va,
                    "cdListinoAcquisto": od.get("cdListinoAcquisto"),
                    "MetodiPagamentoAccontoContabilizzato": od.get("MetodiPagamentoAccontoContabilizzato"),
                }
                key_tuple = tuple(row.get(c) for c in ORDERS_GLOBAL_COLUMNS)
                union_rows[key_tuple] = row

    # Parte 2: ordini 'Piano di protezione*' da orders
    for o in orders:
        if o.get("ArticleType") not in PROTECTION_TYPES:
            continue
        nome_cognome = f"{o.get('SalesConsultantName')} {o.get('SalesConsultandSurname')}"
        if _is_store_manager(db, o.get("SalesConsultantName"), o.get("SalesConsultandSurname")):
            nome_cognome = f"*(S) {nome_cognome}"
        row = {
            "idStatoOrdine": "9999",
            "statoOrdine": o.get("OrderStatus"),
            "idTipoOrdine": "9999",
            "tipoOrdine": o.get("OrderType"),
            "Brand": o.get("Brand"),
            "numPreventivo": "9999",
            "cognomeSelQuotation": "",
            "nomeSelQuotation": "",
            "numOrdine": o.get("OrderNumber"),
            "numOrdineRiferimento": "9999",
            "idSeller": "9999",
            "nomeCognome": nome_cognome,
            "cognomeSel": o.get("SalesConsultandSurname"),
            "nomeSel": o.get("SalesConsultantName"),
            "idConsumer": o.get("ConsumerID"),
            "cognomeCns": o.get("ConsumerSurname"),
            "nomeCns": o.get("ConsumerName"),
            "cdStore": _store_nares(db, o.get("Store")),
            "store": o.get("Store"),
            "cdAffiliato": "9999",
            "dtOrdine": o.get("OrderDate"),
            "dtRichiesta": o.get("RequestedDeliveryDate"),
            "dtMakeDefinitive": o.get("MakeDefinitiveDate"),
            "dtCancel": o.get("CancelDate"),
            "CompleteReceivingDate": o.get("CompleteReceivingDate"),
            "tipoFinanziamento": "",
            "numRate": "9999",
            "importoDaFinanziare": "9999",
            "idTipoRiga": "9999",
            "cdListino": o.get("PricelistCode"),
            "tipoRiga": o.get("ArticleType"),
            "isProntaConsegna": o.get("SoldFromWarehouse"),
            "isOmaggio": o.get("Gift"),
            "cdArticolo": o.get("ArticleCode"),
            "Article": o.get("Article"),
            "po": o.get("PO"),
            "dtInvoiceB2B": "01/01/1999",
            "cdAlias": o.get("AliasCode"),
            "cdRivestimento": o.get("CoveringCode"),
            "cdCategoriaRivestimento": o.get("CoveringCategoryCode"),
            "Iva": o.get("TaxDescription"),
            "aliquotaIva": o.get("TaxRate"),
            "qtaOrdinata": 0,
            "totaleSedute": o.get("Seats"),
            "totalePesoNetto": 99.99,
            "totalePesoLordo": o.get("GrossWeight"),
            "totaleVolume": o.get("Volume"),
            "selloutTeorico": o.get("GrossPice"),
            "sconto": o.get("Discount"),
            "importoScontatoNetto": _num(o.get("DiscountAmount")) / 1.22,
            "importoScontato": o.get("DiscountAmount"),
            "selloutRealeNetto": _num(o.get("NetPrice")) / 1.22,
            "selloutReale": o.get("NetPrice"),
            "consensoMarketing": o.get("ConsumerMarketingAgreement"),
            "consensoProfiling": o.get("ConsumerProfilingAgreement"),
            "consensoTeleMarketing": o.get("ConsumerTeleMarketingAgreement"),
            "consensoThirdParties": o.get("ConsumerThirdPartiesAgreement"),
            "consensoPrivacy": o.get("ConsumerPrivacyAgreement"),
            "telefonoCasa": o.get("ConsumerTelHome"),
            "telefonoMobile": o.get("ConsumerTelMobile"),
            "telefonoUfficio": o.get("ConsumerTelOffice"),
            "descrTipoVie": o.get("ConsumerAddressType"),
            "nomeVia": o.get("ConsumerAddress"),
            "civicoVia": o.get("ConsumerAddressNr"),
            "localita": o.get("ConsumerPlace"),
            "cap": o.get("ConsumerZipCode"),
            "descrComune": o.get("ConsumerCity"),
            "Acconto": o.get("TotalDeposits"),
            "AccontoContabilizzato": o.get("TotalDeposits"),
            "saldo": o.get("Balance"),
            "dataCaricoMagazzino": o.get("WharehouseLastLoadDate"),
            "valoreAcquisto": -1.00,
            "cdListinoAcquisto": "",
            "MetodiPagamentoAccontoContabilizzato": "",
        }
        key_tuple = tuple(row.get(c) for c in ORDERS_GLOBAL_COLUMNS)
        union_rows[key_tuple] = row

    global_rows = list(union_rows.values())
    _insert_rows(db, "ordersGlobal", global_rows, ORDERS_GLOBAL_COLUMNS)

    # ---- ordersGlobalOrd (aggregazione) ----
    group_keys = [
        "idStatoOrdine", "statoOrdine", "tipoOrdine", "numOrdine", "cognomeSel",
        "nomeSel", "cdStore", "store", "dtOrdine",
        "MetodiPagamentoAccontoContabilizzato", "tipoFinanziamento", "numRate",
        "importoDaFinanziare", "Acconto", "AccontoContabilizzato", "saldo",
    ]
    sums = ["totaleSedute", "selloutTeorico", "importoScontatoNetto",
            "importoScontato", "selloutRealeNetto", "selloutReale", "valoreAcquisto"]

    def protection_extra(field: str, num_ordine, dt_ordine) -> float:
        total = 0.0
        for r in global_rows:
            if r.get("tipoRiga") in PROTECTION_TYPES and r.get("numOrdine") == num_ordine \
                    and r.get("dtOrdine") == dt_ordine:
                total += _num(r.get(field))
        return total

    agg: dict[tuple, dict] = {}
    for r in global_rows:
        if r.get("tipoRiga") in PROTECTION_TYPES:
            continue
        key = tuple(r.get(k) for k in group_keys)
        bucket = agg.setdefault(key, {k: r.get(k) for k in group_keys})
        for f in sums:
            bucket.setdefault(f"_sum_{f}", 0.0)
            bucket[f"_sum_{f}"] += _num(r.get(f))
    ord_rows = []
    for key, bucket in agg.items():
        row = {k: bucket[k] for k in group_keys}
        for f in sums:
            row[f] = bucket[f"_sum_{f}"] + protection_extra(f, row.get("numOrdine"), row.get("dtOrdine"))
        ord_rows.append(row)
    _insert_rows(db, "ordersGlobalOrd", ord_rows, ORDERS_GLOBAL_ORD_COLUMNS)

    # ---- ordersGlobalDTOrd ----
    seen = set()
    dt_rows = []
    for r in global_rows:
        pair = (r.get("dtOrdine"), r.get("numOrdine"))
        if pair not in seen:
            seen.add(pair)
            dt_rows.append({"dtOrdine": pair[0], "numOrdine": pair[1]})
    _insert_rows(db, "ordersGlobalDTOrd", dt_rows, ["dtOrdine", "numOrdine"])

    # ---- markupGlobal ----
    def _delivery_ok(o) -> bool:
        dd = o.get("DeliveryDate")
        if dd is None or dd == "":
            return False
        if isinstance(dd, datetime.datetime):
            return dd.strftime("%Y%m%d") >= "20200101"
        return str(dd).split(" ")[0].replace("-", "") >= "20200101"

    markup_rows = []
    for key, od_rows in obd_by_key.items():
        for o in orders_by_key.get(key, []):
            if not _delivery_ok(o):
                continue
            for od in od_rows:
                markup_rows.append({
                    "deliverydate": o.get("DeliveryDate"),
                    "cdStore": od.get("cdStore"),
                    "store": o.get("Store"),
                    "OrderStatus": o.get("OrderStatus"),
                    "tipoOrdine": od.get("tipoOrdine"),
                    "numOrdine": od.get("numOrdine"),
                    "selloutRealeNetto": od.get("selloutRealeNetto"),
                    "ArticleType": o.get("ArticleType"),
                    "Article": o.get("Article"),
                    "ArticleCode": o.get("ArticleCode"),
                    "valoreAcquisto": od.get("valoreAcquisto"),
                    "dtOrdine": od.get("dtOrdine"),
                    "Seats": o.get("Seats"),
                })
    _insert_rows(db, "markupGlobal", markup_rows, MARKUP_COLUMNS)

    return {
        "ordersGlobal": len(global_rows),
        "ordersGlobalOrd": len(ord_rows),
        "ordersGlobalDTOrd": len(dt_rows),
        "markupGlobal": len(markup_rows),
    }
