# PivotDesk

PivotDesk è una piattaforma web (FastAPI + Pandas) per importare dati aziendali da file o sorgenti configurate, analizzarli con pivot dinamiche e visualizzare risultati in tabella HTML.

## Stato del progetto

Questo repository è una base funzionante per sviluppo locale. Include:

- server FastAPI (`app.py`);
- launcher desktop/web (`main.py`, `run_pivotdesk.py`, `tray.py`);
- motore pivot e gestione sorgenti (`services/`);
- moduli licensing (`licensing/`);
- template Jinja2 (`templates/`).

## Requisiti

- Python 3.10+
- pip aggiornato

## Setup rapido

1. Crea e attiva un virtual environment.
2. Installa le dipendenze core:

```bash
python -m pip install -r requirements-core.txt
```

3. (Opzionale, desktop/tray) Installa dipendenze aggiuntive:

```bash
python -m pip install -r requirements-desktop.txt
```

## Avvio applicazione

### Opzione A (consigliata in sviluppo)

```bash
python run_pivotdesk.py
```

### Opzione B (launcher principale)

```bash
python main.py
```

Dopo l'avvio, apri il browser su:

- `http://127.0.0.1:8091`

## Credenziali di default

Alla prima esecuzione viene creato un utente admin:

- username: `admin`
- password: `admin`

> Cambiare la password il prima possibile in ambienti condivisi.

## Struttura rapida

- `app.py`: entrypoint FastAPI e route web/API.
- `services/pivot_engine.py`: trasformazioni dataframe e pivot.
- `services/source_manager.py`: caricamento dati da sorgenti.
- `templates/`: pagine HTML.
- `data/`: configurazioni runtime generate automaticamente.
- `licenses/`: file licenza demo/dev.

## Note operative

- Config host/porta da `config.json`.
- I log launcher vengono scritti in `%LOCALAPPDATA%/PivotDesk/logs` su Windows.
- Se la porta configurata è occupata, il launcher non avvia un secondo server.
- Gli endpoint `GET /fields` e `GET /filter-values` accettano anche `pivot_id` opzionale: quando presente, applicano i `calculated_fields` del preset prima di restituire colonne/valori filtro.
- Per utenze admin con licenza attiva è disponibile backup/ripristino di preset+impostazioni (`GET /admin/backup/export`, `POST /admin/backup/restore`).

## Troubleshooting veloce

- Errore dipendenze mancanti: reinstalla i requirements.
- Porta occupata: cambia `port` in `config.json` o chiudi il processo attivo.
- Template non trovati: verifica che la cartella `templates/` sia presente nella root progetto.
