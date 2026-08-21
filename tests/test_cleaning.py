"""Verifica delle trasformazioni di pulizia sui file di esempio."""
from __future__ import annotations

from nares_sales_updater import cleaning


def test_orders_columns_and_row_fixes(config, mappings, export_rows):
    cleaned, stats = cleaning.clean_orders(
        export_rows["orders"], mappings["orders"],
        config["orders_blocklist"], config["exports"]["orders"]["numeric_columns"],
    )
    assert stats["output_rows"] > 0
    assert stats["dropped_promo"] > 0  # il file di esempio contiene righe BLOCCO PROMO
    assert all(set(row) == set(mappings["orders"].target_columns) for row in cleaned)

    # ConsumerCity copiata da ConsumerPlace (macro T->S)
    assert all(
        row["ConsumerCity"] == row["ConsumerPlace"] for row in cleaned[:50]
    )
    # Quantities / InvoicedQuantities arrotondati a interi
    for row in cleaned[:20]:
        q = row["Quantities"]
        assert q is None or float(q).is_integer()
    # nessuna riga con DeliveryNote contenente blocco promo
    for row in cleaned:
        note = str(row["DeliveryNote"] or "").lower()
        assert "bloccopromo" not in note and "blocco promo" not in note
    # nessun ordine in blocklist
    blocked = {str(b) for b in config["orders_blocklist"]}
    for row in cleaned:
        assert str(row["OrderNumber"]).rstrip(".0") not in blocked


def test_orders_blocklist_filtering(config, mappings):
    sample = {
        "OrderStatus": "Test",
        "OrderNumber": 15345527,
        "DeliveryNote": "note",
        "OrderType": "x", "QuotationNumber": "", "Brand": "", "OrderCreationDate": "",
        "TotalDeposits": "", "Balance": "", "SeatsTradeIn": "", "SalesConsultandSurname": "",
        "SalesConsultantName": "", "ConsumerID": "", "ConsumerSurname": "", "ConsumerName": "",
        "ConsumerAddressType": "", "ConsumerAddress": "", "ConsumerAddressNr": "",
        "ConsumerZipCode": "", "ConsumerCity": "", "ConsumerPlace": "",
        "ConsumerTelHome": "", "ConsumerTelMobile": "", "ConsumerTelOffice": "",
        "ConsumerEMail": "", "ConsumerMarketingAgreement": "", "ConsumerProfilingAgreement": "",
        "ConsumerTeleMarketingAgreement": "", "ConsumerThirdPartiesAgreement": "",
        "ConsumerPrivacyAgreement": "", "ConsumerType": "", "FiscalIdCompany": "",
        "FiscalIdPrivate": "", "Payer": "", "Store": "", "OrderDate": "",
        "RequestedDeliveryDate": "", "RequestedDeliveryDateToConsumer": "",
        "MakeDefinitiveDate": "", "CancelDate": "", "OrderSAPCreationDate": "",
        "DeliveryNumber": "", "DeliveryDateCreation": "", "WharehouseLastLoadDate": "",
        "CompleteReceivingDate": "", "AgreedDeliveryDate": "", "GITDate": "",
        "DeliveryDate": "", "DeliveryDateInsert": "", "PricelistCode": "",
        "ArticleType": "", "SoldFromWarehouse": "", "Gift": "", "ArticleCode": "",
        "Article": "", "PO": "", "AliasCode": "", "CoveringCode": "",
        "CoveringCategoryCode": "", "TaxDescription": "", "TaxRate": "", "Seats": "",
        "Packages": "", "Volume": "", "VolumeUnitMesaure": "", "Quantities": "",
        "GrossPice": "", "Discount": "", "DiscountAmount": "", "NetPrice": "",
        "InvoicedQuantities": "", "InvoicedNetPrice": "", "ConsumerProfile": "",
        "ArchitectPurchaseOrder": "", "Note": "", "DeliveryNote": "ok", "HistoryNote": "",
        "GrossWeight": "",
    }
    cleaned, stats = cleaning.clean_orders(
        [sample, {**sample, "OrderNumber": "99999999"}], mappings["orders"],
        config["orders_blocklist"], config["exports"]["orders"]["numeric_columns"],
    )
    assert stats["dropped_blocklist"] == 1
    assert len(cleaned) == 1
    assert str(cleaned[0]["OrderNumber"]) == "99999999"


def test_ordersbydate_fixes(config, mappings, export_rows):
    cleaned, stats = cleaning.clean_orders_by_date(
        export_rows["ordersByDate"], mappings["ordersByDate"],
        config["orders_blocklist"], config["exports"]["ordersByDate"]["numeric_columns"],
    )
    assert stats["output_rows"] > 0
    # descrComune copiata da localita (macro BK->BM)
    for row in cleaned[:30]:
        assert row["descrComune"] == row["localita"]
    # cap e cdCategoriaRivestimento: solo numerici (i 23 non numerici cancellati)
    assert stats["cleared_categoria"] > 0
    for row in cleaned:
        for col in ("cap", "cdCategoriaRivestimento"):
            value = row[col]
            if value is not None:
                assert str(value).replace(".", "", 1).isdigit() or str(value).lstrip("-").isdigit()


def test_preventivi_drops_movement_id(config, mappings, export_rows):
    cleaned, stats = cleaning.clean_preventivi(
        export_rows["preventivi"], mappings["preventivi"],
        config["exports"]["preventivi"]["numeric_columns"],
    )
    assert stats["output_rows"] > 0
    assert all(set(row) == set(mappings["preventivi"].target_columns) for row in cleaned)


def test_ingressi_derivation(config, mappings, export_rows):
    cleaned, stats = cleaning.derive_ingressi(
        export_rows["ingressi"], mappings["ingressi"],
        config["exports"]["ingressi"]["numeric_columns"],
    )
    assert stats["output_rows"] > 0
    assert stats["dropped_unparsable"] == 0
    first = cleaned[0]
    assert set(first) == {"cdStore", "store", "data", "anno", "mese", "ingressi"}
    assert isinstance(first["cdStore"], int) and first["cdStore"] > 0
    assert "(" not in first["store"]
    assert isinstance(first["anno"], int) and isinstance(first["mese"], int)
