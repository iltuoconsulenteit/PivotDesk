# AGENTS.md - PivotDesk

Istruzioni operative per agenti (Codex) che lavorano in questa repository.

## Obiettivo

Mantenere il progetto avviabile in locale, con modifiche piccole, verificabili e coerenti con l'architettura FastAPI + servizi.

## Regole generali

- Mantieni compatibilità con Python 3.10+.
- Evita refactor ampi non richiesti.
- Non introdurre nuove dipendenze senza motivazione esplicita.
- Se tocchi logica business, aggiorna anche la documentazione minima in `README.md`.

## Flusso consigliato per modifiche

1. Leggi i file direttamente coinvolti.
2. Applica modifiche minime e mirate.
3. Esegui almeno questi check locali:
   - `python -m compileall app.py services licensing`
   - `python scripts/healthcheck.py` (se applicabile)
4. Riassumi cambi, limiti e prossimi passi.

## Convenzioni progetto

- Entrypoint web: `app.py`
- Launcher sviluppo: `run_pivotdesk.py`
- Launcher desktop/packaging: `main.py` e `tray.py`
- Motore dati: `services/pivot_engine.py`
- Gestione sorgenti: `services/source_manager.py`

## Dati e file runtime

- Non committare dati sensibili in `data/`, `licenses/` o `user_data/`.
- Mantieni `.gitignore` aggiornato se introduci nuovi artefatti runtime.

## Note per debug

- Host/porta configurabili da `config.json`.
- In caso di porta occupata, verificare processi già attivi prima di cambiare codice.
- Su Windows i log launcher sono in `%LOCALAPPDATA%/PivotDesk/logs`.
