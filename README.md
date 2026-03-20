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
- Nel frontend il backup/restore è disponibile sia dal menu principale “Backup” sia dal riquadro “Backup & Restore” in Impostazioni; lato UI la funzione risulta attiva per licenze non demo (oltre al flag feature esplicito).
- Nella barra licenza è disponibile il pulsante “Attiva licenza” con scelta provider (`developer`, `gumroad`, `lemonsqueezy`, `custom` secondo configurazione). La selezione può essere preimpostata anche da URL (`?provider=gumroad`).
- Con licenza non-demo il launcher può bindare automaticamente su `0.0.0.0` (LAN). In output/log viene mostrato anche URL LAN suggerito; se non raggiungibile da altri PC verificare firewall/porta in ingresso.
- Con licenza demo/trial/community il launcher forza bind locale su `127.0.0.1` (LAN disabilitata di default).
- In startup app è attivo un controllo automatico: se la licenza abilita LAN ma il processo risulta in ascolto su `127.0.0.1`, PivotDesk rilancia uvicorn su `0.0.0.0` (override interno, indipendente dal batch di avvio).
- Il launcher ora rileva il tipo licenza anche dal percorso configurato in `data/license_settings.json` (chiave `license_file`), riducendo casi in cui restava in bind locale `127.0.0.1` nonostante licenza attiva.
- Endpoint diagnostico `GET /lan/status` disponibile per utenti autenticati: riporta host configurato, bind effettivo, URL loopback/LAN e suggerimento firewall.
- `GET /lan/status` espone anche `bind_source` (`runtime`, `socket` o `inferred`): se `inferred`, il bind mostrato è dedotto da config/licenza e può differire dal processo realmente avviato (es. avvio manuale su `127.0.0.1`).
- `GET /lan/status` include anche test socket locali (`loopback_reachable`, `lan_reachable_from_host`) e `startup_hint` per segnalare quando il server risponde su `127.0.0.1` ma rifiuta sull'IP LAN (tipico avvio localhost-only).
- `GET /lan/status` espone anche `lan_expected_by_license` per distinguere la policy licenza (LAN attesa) dallo stato di bind realmente attivo.
- Nel frontend (modale “Dettagli licenza”) è disponibile il pulsante “Diagnostica LAN” che mostra lo stato letto da `GET /lan/status`.
- Per verifica pratica firewall/LAN: `POST /lan/probe/new` (autenticato) genera una URL test, `GET /lan/probe/{id}` registra il passaggio dal client remoto e `GET /lan/probe/result` (o `GET /lan/probe/status`, autenticato) mostra se la sonda è stata raggiunta.
- Se `POST /lan/probe/new` risponde `LAN non attiva su questo avvio`, riavviare con launcher (`python run_pivotdesk.py`) oppure con uvicorn `--host 0.0.0.0`.
- Endpoint admin `POST /lan/firewall/open` tenta apertura automatica della porta app nel firewall locale (Windows via `netsh`, Linux via `ufw` se disponibile).
- Su Windows `POST /lan/firewall/open` prova anche ad avviare `netsh` con elevazione (`RunAs`): l’utente deve confermare il prompt UAC per completare la regola firewall.
- Con licenza attiva (non demo) è disponibile upload logo cliente (`POST /admin/branding/customer-logo`), mostrato su login e header principale.
- Nei campi calcolati è disponibile `token_after(testo, marcatore, case_sensitive?)` per estrarre il primo token dopo stringhe come `#` o `CRO:` (utile su descrizioni bancarie/libere). Il terzo parametro è opzionale (`false` default).
- Nei campi calcolati sono disponibili anche `minutes_diff(uscita, ingresso)` e `hours_diff(uscita, ingresso)` (input orari `HH:MM`, `HH:MM:SS`, varianti AM/PM e frazioni giorno Excel `0.x`) più `if_else(condizione, valore_true, valore_false)` con operatori di confronto (`>=`, `<=`, `==`, `!=`, `>`, `<`). Esempio: `if_else(hours_diff([Uscita], [Ingresso]) >= 8, 1, 0)`.
- Nel modal dei campi calcolati puoi trascinare i campi dalla sidebar direttamente dentro la formula (`[Nome Campo]`).
- Il modal campi calcolati include un assistente funzioni stile Excel: ricerca funzione, firma argomenti e composizione guidata della formula; i campi sono trascinabili direttamente negli argomenti funzione.
- Le funzioni nell’assistente sono divise per categoria (testo, data, numero, logica, ecc.) con sezioni espandibili/comprimibili e registro estendibile lato frontend (`registerCalculatedFunctionDefinition`) per futuri inserimenti custom.
- Nell’anteprima sorgente del builder, i campi calcolati definiti vengono mostrati come colonne aggiuntive (anteprima aggiornata al salvataggio/eliminazione campo calcolato).
- Per sorgenti Excel è disponibile caricamento elenco fogli direttamente nella maschera sorgente (selezione guidata del foglio da elaborare per anteprima e pivot, non solo primo foglio) con mantenimento del foglio salvato durante la modifica della sorgente.
- Nei filtri colonna, quando i valori sono numerici, l’ordinamento è numerico (es. `1,2,3,...,10,11`) e non lessicografico (`1,10,11,2,...`).
- Nel menu **Visualizza** è disponibile **Grafico da pivot**: apre un template grafico (colonne, barre, linea, torta) costruito dalla tabella pivot corrente con scelta campo etichetta/valore e Top N; lo stesso modal è richiamabile anche dalla quickbar layout pivot tramite pulsante “Grafico”. La stampa grafico è disponibile direttamente dentro il modal tramite pulsante “Stampa grafico” e stampa solo il grafico (con header/filtri e, se presente, logo cliente in testata).

## Troubleshooting veloce

- Errore dipendenze mancanti: reinstalla i requirements.
- Porta occupata: cambia `port` in `config.json` o chiudi il processo attivo.
- Template non trovati: verifica che la cartella `templates/` sia presente nella root progetto.
