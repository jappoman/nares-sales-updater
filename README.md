# nares-sales-updater

Automatizza il caricamento dei dati NARES nella Power BI aziendale (Genesi Retail).

Sostituisce il flusso manuale descritto in `docs/what-to-do.txt`:
1. **download** delle 4 estrazioni dal portale NARES (ordini, ordini per data ordine, preventivi, rapportino visite)
2. **pulizia** dei file (replica delle macro VBA `puliziaorders` / `puliziaordersbydate` / `puliziapreventivi` e del file `Rapportovisite` con le formule F-K)
3. **caricamento** su SQL Server (`GenesiRetail`): cancellazione del range di dati, inserimento, esecuzione della stored procedure `Create_ordersGlobal`

Il progetto si ispira a [recupero-dati-barbiere](https://github.com/jappoman/recupero-dati-barbiere):
stessa architettura (config-driven, sessione browser in cache, `--skip-db`/dry-run,
backend SQL Server con `pyodbc`, logging in `logs/`).

## Differenza chiave rispetto alle macro

Le macro VBA lavorano per **posizione di colonna** (lettere tipo `C:D`, `BO`, `CI:CV`) e
sono state scritte quando l'export NARES aveva un layout diverso da quello attuale
(il doc indica come ultima colonna `CH`/HistoryNote, ma oggi l'export arriva a 118 colonne
fino a `IdUserCreate`). Applicandole al layout attuale le colonne risultanti NON
corrispondono più alle tabelle del DB.

Questo programma lavora invece per **nome di colonna**: il mapping export → tabella DB
è dichiarato in `config.json` (ordinato come le tabelle del DB, verificato contro gli
esempi `docs/res/esempi_tabelle_sql`). Se Natuzzi aggiunge/rinomina colonne, il programma
segnala un warning con l'elenco delle colonne ignorate invece di produrre dati errati.

## Installazione

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  |  source .venv/bin/activate (Linux/macOS)
pip install -r requirements.txt
```

## Configurazione

### `config.json`
Contiene: definizione delle 4 estrazioni (nomi file, fogli, tabelle, regole DELETE),
mapping colonne export → DB, blocklist ordini, stored procedure, selettori NARES.

> Rigenera le sezioni mapping con `python tools/generate_config.py` quando l'export
> NARES cambia (lo script le ri-deriva dagli esempi in `docs/res`).

### `.env` (segrete — non committare)
```bash
NARES_USERNAME=...          # credenziali portale NARES
NARES_PASSWORD=...          # cambia ogni 3 mesi: si aggiorna SOLO qui
SQL_SERVER=btsrv-qr.bteam.local
SQL_USERNAME=gen
SQL_PASSWORD=...
```
Il `.env` esistente nel vecchio formato JSON (`{"username":..., "password":..., "host":...}`)
viene comunque letto (backward compatible).

## Utilizzo

```bash
# DRY-RUN: elabora i file e genera gli script SQL in out/sql/ (nessuna scrittura DB)
python main.py --use-files "docs/res/file di esempio" --date-from 2026-04-21 --date-to 2026-08-20

# DRY-RUN + demo end-to-end su SQLite (nessun write sul DB vero)
python main.py --use-files "docs/res/file di esempio" --demo-db

# Download reale da NARES + scrittura sul DB SQL Server (richiede conferma)
python main.py --live

# Come sopra, senza conferma interattiva (per Task Scheduler)
python main.py --live --yes

# Solo download + pulizia, senza toccare il DB
python main.py --no-download --use-files <dir>
```

Le date di default sono calcolate da oggi (orders/ordersByDate: 4 mesi indietro → ieri;
preventivi: 30 giorni → ieri; ingressi: anno corrente). Si possono sovrascrivere con
`--date-from/--date-to`.

Output:
- `out/downloaded/` — file scaricati da NARES
- `out/cleaned/` — file puliti (xlsx, per ispezione)
- `out/sql/` — script SQL generati (DELETE + INSERT) da revisionare prima del live
- `logs/` — log di ogni esecuzione

## Cosa fa la pulizia (per file)

| File | Operazioni |
|------|------------|
| `orderExport.xlsx` | tiene solo le 77 colonne della tabella `orders` (rename `Pricelist`→`GrossPice`, `TotalPrice`→`NetPrice`); `ConsumerCity := ConsumerPlace`; arrotonda `Quantities`/`InvoicedQuantities`; elimina righe con "blocco promo" in `DeliveryNote` e ordini in blocklist |
| `OrdersByOrderDate.xlsx` | tiene le 75 colonne di `ordersByDate`; `cap` e `cdCategoriaRivestimento` solo numerici; `descrComune := localita`; elimina ordini in blocklist |
| `quotations.xls` | elimina la colonna `Movement ID`, rinomina in snake_case (46 colonne di `Preventivi`) |
| `Rapportinovisite.xlsx` | estrae `cdStore`/`store` dal campo `Negozio` (replica delle formule F-K del file Rapportovisite) e produce le 6 colonne di `ingressi` |

Il blocklist ordini è in `config.json -> orders_blocklist` (aggiornabile: i numeri cambiano
nel tempo, vedi `Cancellare OrderNumber in (...)` nei doc).

## Caricamento sul DB

Per ogni tabella la strategia è configurabile in `config.json` (`exports.<key>.strategy`):

- **`delete_insert`** (orders, ordersByDate): come nel flusso manuale — DELETE del range
  esportato, poi INSERT di tutto. È l'unica strategia garantita corretta per queste
  tabelle: l'export non ha una chiave univoca affidabile (contiene righe duplicate,
  es. stesso ordine+articolo con rivestimenti diversi, e persino righe identiche).
  Con il vecchio flusso i duplicati sono già nel DB, quindi un MERGE fallirebbe
  ("attempted to update the same row more than once").
- **`upsert`** (Preventivi, ingressi): UPDATE+INSERT per chiave + delete delle righe
  "stale" nel range (righe che non sono più nell'export, es. preventivo rimosso da
  NARES). Le chiavi sono verificate uniche nei dati e negli esempi del DB:
  - `Preventivi`: `(quotation_nr, row_nr, proposal_nr)`
  - `ingressi`: `(cdStore, data)`

Le regole di range (usate sia dal DELETE che dalla cancellazione delle righe stale):

- `orders`: `DELETE ... WHERE OrderDate BETWEEN da AND a` (chiave configurabile)
- `ordersByDate`: idem su `dtOrdine`
- `Preventivi`: `WHERE quotation_date > da` (come indicato nei doc)
- `ingressi`: `WHERE anno BETWEEN ...`

Nota: un upsert "semplice" (solo update+insert) NON è equivalente al delete+insert:
l'export è uno snapshot, quindi le righe sparite da NARES (ordini cancellati o fuori
range) resterebbero stale nel DB. Per questo l'upsert qui include sempre anche la
cancellazione delle righe stale nel range. Le righe con chiave parzialmente nulla
(es. ordini senza `ArticleCode`) non possono usare l'upsert (in SQL `NULL != NULL`):
vengono gestite con delete+insert per-riga, così il caricamento resta idempotente.

Poi viene eseguita `Create_ordersGlobal` (file di riferimento: `sql/Create_ordersGlobal.sql`).
La modalità demo esegue una traduzione Python fedele del merger su SQLite.

## Automazione portale NARES

Il download usa Edge + Chrome DevTools Protocol (stesso approccio di recupero-dati-barbiere):
- login con username/password, sessione salvata in `.nares_session.json` (scadenza ~2 mesi, sotto i 3 mesi di rotazione password)
- i selettori della pagina sono in `config.json -> nares.selectors`: **vanno calibrati sul portale reale** alla prima esecuzione live (il portale è un'app JSF e può cambiare)

## Test

```bash
.venv\Scripts\python.exe -m pytest tests/
```

I test verificano: completezza del mapping contro gli esempi, tutte le trasformazioni di
pulizia, il filtro blocklist e la demo SQLite end-to-end (delete + insert + merger).

## Sicurezza

- Niente credenziali nel codice o in `config.json`: stanno in `.env` (gitignored).
- La password NARES gira ogni 3 mesi → si aggiorna solo `.env`, nessuna modifica al codice.
- Di default il programma è in **dry-run**: non scrive nulla sul DB. Il `--live` richiede
  conferma esplicita (`--yes` per l'automazione).

## Eseguibili Windows (GUI + Task Scheduler)

Come in recupero-dati-barbiere, la build produce **due eseguibili**:

| Eseguibile | Tipo | Uso |
|------------|------|-----|
| `dist\NaresSalesUpdater.exe` | GUI (windowed) | doppio clic: inserisci le date custom e premi "Avvia estrazione" |
| `dist\NaresSalesUpdaterAuto.exe` | console | lanciato dal Task Scheduler con `--auto` |

La GUI di default è in **dry-run** (non scrive sul DB): per scrivere dati reali
spunta la checkbox "Scrivi sul database (SQL Server)". L'eseguibile AUTO usa i
range di default (orders/ordersByDate: 4 mesi → ieri; preventivi: 30 giorni → ieri;
ingressi: anno corrente), scarica da NARES, carica sul DB ed esegue la stored
procedure — pensato per l'esecuzione schedulata.

### Build

```powershell
.\build.ps1          # aggiungi -Clean per pulire build/ e dist/
```

Lo script crea/riusa `.venv`, installa le dipendenze (incluso `pyinstaller`) e
genera i due onefile in `dist\`.

**Cosa consegnare all'utente** (config.json e .env NON sono inclusi nella build,
per sicurezza vanno copiati manualmente accanto all'eseguibile):

```text
dist\NaresSalesUpdater.exe
dist\NaresSalesUpdaterAuto.exe
config.json
.env
```

### Task Scheduler (Windows Server)

1. Copia i 4 file qui sopra in una cartella (es. `C:\NaresSalesUpdater\`).
2. Task Scheduler → `Create Task...`:
   - **General**: `Run whether user is logged on or not`, `Run with highest privileges`
   - **Triggers**: `On a schedule` → `Daily` (es. 07:00)
   - **Actions**: `Start a program`
     - `Program/script`: `C:\NaresSalesUpdater\NaresSalesUpdaterAuto.exe`
     - `Add arguments`: `--auto`
     - `Start in`: `C:\NaresSalesUpdater`
3. Esegui il task manualmente la prima volta e controlla `logs\nares_*.log`.

Nota: al primo avvio l'automazione del portale NARES potrebbe richiedere la
calibrazione dei selettori in `config.json -> nares.selectors` (il portale è
un'app JSF): in caso di errore il log indica quale campo non viene trovato.
