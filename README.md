# PivotDesk

PivotDesk is a FastAPI + Pandas web application used to import business data, build dynamic pivots, and explore results in an interactive UI.

![PivotDesk app logo](static/img/pivotdesk-logo.png)

## Language docs

- **Primary docs (EN):** this file + [`docs/WIKI.md`](docs/WIKI.md)
- **Italian docs:** [`README.it.md`](README.it.md), [`docs/WIKI.it.md`](docs/WIKI.it.md)

---

## Project status

This repository is a working local-development baseline. Main components:

- FastAPI server (`app.py`)
- desktop/web launchers (`main.py`, `run_pivotdesk.py`, `tray.py`)
- pivot/data services (`services/`)
- module registry + manifests (`modules/`)
- plugin registry + extensions (`plugins/`)
- licensing modules (`licensing/`)
- Jinja templates (`templates/`)

### Modules vs Plugins (maintenance structure)

- `modules/` contains **functional modules** (business pages/features) described by `module.json` manifests.
- `plugins/` contains **technical extensions** that can enrich modules (providers/tools/endpoints).
- Runtime module metadata is available via `GET /modules`; plugin metadata remains under `GET /plugins` and `GET /plugins/status`.

---

## Requirements

- Python 3.10+
- updated pip

Install core dependencies:

```bash
python -m pip install -r requirements-core.txt
```

Optional desktop/tray dependencies:

```bash
python -m pip install -r requirements-desktop.txt
```

---

## Run / startup modes

### Source mode (repository / development)

Canonical server bootstrap is `main.py`:

```bash
python main.py [--host 127.0.0.1] [--port 8091] [--no-browser]
```

Desktop companion launcher:

```bash
python tray.py
```

Developer note: keep local launcher scripts outside the public repository when needed for internal workflow.

### Compiled mode (PyInstaller one-dir)

- `PivotDesk.exe` is the canonical packaged server/bootstrap executable.
- `PivotDeskTray.exe` is a companion desktop launcher that starts `PivotDesk.exe --host ... --port ... --no-browser`.
- Compiled executables are distributed via official sales channels; do not commit public batch wrappers for end users in this repository.

Default URL:

- `http://127.0.0.1:8091/login`

Packaging note: **PyInstaller one-dir** is the recommended first packaging target.
Runtime resources (templates/static/licenses) are resolved with a frozen-safe `_MEIPASS` fallback, while writable runtime data uses the app user area in packaged mode.

### Built-in demo content (first-time onboarding)

- Demo CSV datasets: `demo/demo_sales.csv`, `demo/demo_voting_results.csv`
- Demo source seed: `sources.json` (`default_source: demo_voting`, includes `demo_sales` and `demo_voting`)
- Demo pivot presets: `pivots/demo_sales/demo_sales_overview.json`, `pivots/demo_voting/demo_voting_overview.json`
- Voting Analytics quick demo thresholds (saved in `demo_voting_overview` options): `120` (Eletto) / `80` (Riserva)

On first startup in source mode, `sources.json` is used as the legacy seed and migrated to the user runtime source bundle, so new users can immediately run a working pivot demo.

If you migrate/copy pivot folders from another PivotDesk instance, missing sources are inferred from the imported preset folders (`pivots/<source_id>/*`) and added as editable migration placeholders, so preset/source relinking can be completed directly from Source Management. For Excel-oriented migrated presets, source hints such as `sheet_name` and `skip_rows` are also retained when present in migration payloads.

---

## Default credentials

First run creates admin user:

- username: `admin`
- password: `admin`

Change this password immediately in shared environments.

---

## Quick feature overview

- Source ingestion: CSV, Excel (sheet selection), ODS, MySQL, HTTP JSON/HTTPS API, Google Drive/Google Sheet links.
- Pivot builder with saved presets.
- Calculated fields (server-side formula engine + UI assistant).
- Numeric-safe filtering and optional subtotals/totals.
- Pivot text grouping is case-insensitive by default (`A` and `a` are grouped together), with a global setting to enable case-sensitive mode when needed.
- Chart modal (column/bar/line/pie) with print support.
- Pivot export (Pro/Full): CSV, XLSX, ODS, HTML.
- Chart export (Pro/Full): standalone HTML artifact (interactive-ready payload embedded as JSON + rendered chart image).
- Chart extraction ignores interactive cell controls/icons so numeric values are detected correctly.
- Drilldown/detail modal with column visibility presets.
- Pivot print output excludes interactive UI controls (e.g., drilldown buttons and column filter inputs) for clean report exports.
- Compact home layout with collapsible Source/Preset/Filters/Layout panels to keep the pivot table visible higher on screen.
- User bar and primary menu are aligned on a single row on wide screens to reduce vertical space in the header area.
- Responsive menu adaptation for tablet/smartphone: top menu buttons reflow and their submenus open inline (not clipped).
- On smartphone layouts, the branding header and license area stack into a compact vertical flow (full-width license card + wrapped actions) to avoid overflow/cropping.
- Developer logo in the header now scales responsively on smaller screens (same adaptive behavior style as the app logo).
- Layout quickbar now includes an inline view summary plus a **Wiki** button that opens a slide-out side panel with quick guidance links.
- Pivot success summary is now shown directly in the quickbar (duplicate lower status row removed); the Wiki panel embeds scrollable WIKI content with adjustable width while keeping the main UI usable.
- Wiki side panel content is served in-app via `GET /wiki/content?lang=it|en`, with draggable edge resize support.
- Wiki is opened from a visible **❓ Aiuto** button in the top bar and renders embedded images/logos from docs/static paths.
- License-aware feature gating (including Free tier policy).
- LAN diagnostics/probe/firewall helper endpoints.
- Customer branding (logo upload + rendering in UI/print contexts).
- Backup/restore endpoints for presets/settings.
- Settings screen with accordion sections and dedicated visibility for both module registry (`/modules`) and plugin runtime status.
- Catalog module for unified listing of all data sources and pivot presets (uses `GET /pivots/all` for cross-source preset inventory).
- Source loading now applies a runtime duplicate guard on source IDs in UI, and pivot listing supports legacy source mapping fallback to preserve older source/preset associations.
- Catalog actions include quick edit/delete buttons (with visual icon/color cues) for both sources and pivot presets.
- XML Structured Import plugin (`/plugin/xml-structured-import/upload`) is a quick tool for **single-file** structured XML import, flattening data to CSV in `import_data`.
- XML Batch Import module (`/module/xml-batch-import/upload`) handles **multi-file** XML ingestion with optional unique-key deduplication (`rows_in`, `rows_out`, `duplicates_dropped`) and writes the generated CSV in `import_data` for source auto-detection.
- Voting Analytics plugin/module (`/plugin/voting-analytics/process`) adds ranking, thresholds (`eletti/riserva/esclusi`), multi-column comparison view, pivot-style grouped counts and chart datasets from existing sources.
- Source delete endpoint (`POST /sources/delete`) supports optional `delete_linked_presets=true` to remove JSON presets belonging only to that source in the same confirmation workflow.
- UI localization (English/Italian).

## UI structure previews

The following diagrams are visual examples derived from the HTML layout structure, useful for onboarding and user documentation:

![Home/Pivot main screen](docs/images/screen-home.svg)
![Preset builder screen](docs/images/screen-builder.svg)
![Drilldown modal screen](docs/images/screen-drilldown.svg)
![User management screen](docs/images/screen-users.svg)

---

## Licensing notes (important)

- **Free tier:** CSV-based on-screen pivots only.
- Premium features such as print, charts, and drilldown are available only for paid/dev licenses (based on feature flags/policy).
- LAN exposure is license-controlled and validated by diagnostics endpoints.

---

## Useful paths

- `app.py` – main API/web entrypoint
- `services/pivot_engine.py` – pivot transformation logic
- `services/source_manager.py` – source loading pipeline
- `plugins/calculated_fields/backend.py` – formula engine
- `plugins/cross_source_lookup/plugin.py` – lookup/VLOOKUP-like join between two sources (optional plugin, disabled by default)
- `plugins/multi_source_merge/plugin.py` – multi-source schema merge/union builder (optional plugin, disabled by default)
- `plugins/api_data_scheduler/plugin.py` – scheduler per scarico dati da API (manuale o a intervalli), con supporto auth basic/bearer (optional plugin, disabled by default)
- `plugins/multi_pivot_derived/plugin.py` – derive/cross data from multiple pivots (optional plugin, disabled by default; demo output is watermarked)
- `templates/` – frontend pages
- `static/js/` – frontend logic
- `docs/WIKI.md` – full internal wiki (EN)
- Source-level calculated fields are stored in source config (`calculated_fields`) and are automatically applied during source loading; this makes them available to all plugins (including cross-source lookup and multi-source merge) without redefining formulas per plugin request.
- Optional plugin `google_account_sheets` (disabled by default) enables OAuth device-flow authentication for private Google Drive Sheets and can be licensed as a Pro/Full add-on.
- For direct Google connect from Source Manager, set OAuth credentials once via env (`PIVOTDESK_GOOGLE_CLIENT_ID`, `PIVOTDESK_GOOGLE_CLIENT_SECRET`) or `config.json` under `google_oauth.client_id` / `google_oauth.client_secret`.
- Multi-source merge plugin can now persist merge output as a generated CSV source in `DATA_DIR/generated_sources`, so merged datasets can be reused like normal sources.
- Merge save endpoint (`POST /plugin/multi-source-merge/build-and-save-source`) now also accepts `save_mode=sqlite` to mirror merged rows into `DATA_DIR/generated_sources/merge_outputs.db`, while still generating the CSV source file for compatibility.
- Merge save operations now persist merge definitions in `DATA_DIR/generated_sources/merge_definitions.json` (save mode, columns, selected sources, and source file fingerprints) to support incremental refresh/rebuild flows.
- Multi-source merge plugin also exposes template helpers: `POST /plugin/multi-source-merge/template/headers` (derive template columns from source or CSV/XLSX/ODS headers) and `POST /plugin/multi-source-merge/template/suggest-map` (auto-suggest target/source field mapping for guided drag/drop linking UX).
- Multi-source merge plugin now supports template persistence + execution: create/list/get/delete templates (`/template/save`, `/template/list`, `/template/{id}`) and run append/union merges from a selected template (`POST /plugin/multi-source-merge/build-from-template`) so mapped rows from selected sources are appended under the same target headers.
- Merge UI now includes `Salva template completo` in fase 3 (azioni finali), and template save prioritizes builder mappings/sources over raw JSON textarea content to ensure all linked sources + `column_map` associations are persisted.
- Core fallback now also exposes merge template CRUD endpoints (`/plugin/multi-source-merge/template/list`, `/template/{id}`, `/template/save`, `/template/{id}` DELETE) so template save/load works even when external plugin routes are unavailable.
- Core fallback template CRUD now auto-migrates legacy `DATA_DIR/merge_templates.json` into SQLite (`DATA_DIR/app_data/merge_templates.db`) when DB is empty, preserving previously saved template structures.
- If no dedicated template records are found, merge UI template list can fallback to entries in `DATA_DIR/generated_sources/merge_definitions.json` (saved merge definitions) when they contain reusable output columns.
- Merge CSV export/save now defaults to semicolon (`;`) delimiter, configurable via global settings (`merge_csv_delimiter`), and the saved merge source keeps the selected delimiter in source config metadata.
- Dedicated module screens (Merge/API Scheduler) now keep the homepage top chrome (branding + user/menu bar) visible while hiding only the pivot workspace area, for consistent navigation context.
- Multi-source merge now automatically generates a deterministic unique key column (`_merge_key` by default) and removes duplicates during union/append (`deduplicate=true` by default), reducing duplicate-risk in merged outputs.
- Merge preview now exposes an on-demand duplicate-discard table (“tabella scarti duplicati”) and explicit status messaging when duplicates are detected/removed, for audit/control checks.
- Source Manager alias editor now supports quick-add from detected source headers (clickable header chips), preserves empty/new alias rows correctly, and allows row reordering (↑/↓) for easier alias maintenance.
- When editing a source launched from Merge module, saving now refreshes merge-source field chips/mappings with updated aliases and closing Source Manager returns to the originating module (Merge/API Scheduler) instead of forcing home view.
- Module pages are also available in an inline panel anchored to `mainView` (home chrome visible: logo/menu/license bar), improving continuity while working inside Merge/API Scheduler workflows.
- Multi-source merge now also supports direct CSV export of the unified dataset (`POST /plugin/multi-source-merge/export-csv`), so users can download and transfer merged data as a standalone source file.
- Multi-source merge is managed as an installable/enableable add-on module (disabled by default), with a dedicated top-menu entry (`Moduli > Merge sorgenti (plugin)`) and independent license gating (`plugin_multi_source_merge` / `plugins.multi_source_merge`, plus global `plugins` fallback).
- API Data Scheduler is also an installable/enableable add-on module (disabled by default), with dedicated menu entry (`Moduli > Scheduler API (plugin)`), multi-endpoint configuration, manual run (`/plugin/api-scheduler/run/{job_id}`) and scheduled batch execution (`/plugin/api-scheduler/run-due`) supporting schedule modes: monthly (day+time), weekly (weekday+time), daily (time), every N hours, every N minutes (discouraged for server load).
- I moduli add-on Merge/API Scheduler hanno pagine dedicate (non il tab plugin generico) e generano file in `DATA_DIR/import_data` per import manuale/automatico.
- PivotDesk esegue auto-censimento colonne sui file in `DATA_DIR/import_data` (`csv/xlsx/ods`) e li registra automaticamente come sorgenti (`config.auto_import_data=true`, `config.detected_columns=[...]`); endpoint di refresh: `POST /sources/scan-import-data`.
- Backup/restore (`/admin/backup/export`, `/admin/backup/restore`) supporta ora sezioni selettive per migrazione installazioni: `settings`, `presets`, `sources`, `merge` (definitions+templates), `users`, `plugins`, `api_scheduler`.
- In Source Manager, selecting a merge template now reloads full template details (`/template/{id}`), restoring every saved source block and `column_map`; running from template also works even when no builder blocks are manually re-added (server falls back to template sources).
- Merge templates can now also persist source blocks and field mappings (`sources` + `column_map`), so reloading a template restores both selected sources and saved associations in the guided merge UI.
- Merge templates are stored in SQLite under `DATA_DIR/app_data/merge_templates.db` (application metadata) with legacy auto-migration from `merge_templates.json`, keeping app-state separated from runtime/source user files.
- Core app now exposes built-in fallback endpoints for multi-source merge build/run/save (`/plugin/multi-source-merge/build*`) to guarantee deterministic behavior even when external plugin copies are stale or partially customized.
- Multi-source template ids are handled as numeric index keys (auto-assigned when omitted/invalid, hidden in UI except preview), consistent with source/pivot indexing strategy.
- Source Manager plugin panel includes a guided template-first merge flow with drag&drop mapping (save/load template headers, drag source fields onto template slots, auto-suggest mappings per source, run merge from template), source-header import to bootstrap template columns, and quick catalog views (templates/sources/pivots) for large workspaces.
- Source management now supports optional `column_aliases` (header alias map) so previews/pivots/plugins can show user-defined column names without changing source files.
- For Excel sources (`xlsx`), base Source Manager now includes `import_all_sheets` flag to union all worksheets into one source (with `_sheet` column), so users don't need to run a separate plugin tool when this feature is enabled.
- Source IDs are normalized to numeric keys on startup/save; legacy non-numeric ids are preserved in source config as `legacy_source_id` for backward lookup compatibility.
- During startup migration, PivotDesk also remaps legacy pivot folders/preset payloads to the new numeric source IDs so existing presets remain linked after restart.
- Merge panel action area includes explicit preview/update flow: preview merge output, save as generated source, then refresh the same merge source id when upstream rows/sources change.

Plugin visibility/enablement:
- `GET /plugins/status` shows runtime status + license allow/deny flags.
- `POST /plugins/config/save` persists plugin enable/disable map (`plugins.json`, restart required).
- Plugin discovery scans these folders (first match by plugin id wins): runtime `plugins/`, `APP_HOME/plugins`, bundled `resource/plugins`.
- Source management includes guided plugin forms (dropdown + drag/drop for lookup fields, guided merge builder to generate JSON mapping).

Startup UX:
- `main.py` now shows a startup splash (logo + progress bar) while waiting for server readiness.
- Windows launcher/tray set an explicit AppUserModelID and load PivotDesk icon in startup windows to avoid generic Python taskbar icon in embedded/runtime launches.

---

## Troubleshooting

- Missing dependencies: reinstall requirements.
- Port already in use: update `config.json` or stop the running process.
- Missing templates/static assets: verify repository structure is intact.
- LAN issues: check `/lan/status`, run probe endpoints, and verify firewall state.

## License

PivotDesk source code is publicly available under the Business Source License 1.1.

Official commercial builds, activation licenses, support services and authorized distribution are provided exclusively by IlTuoConsulenteIT.

The internal runtime licensing system implemented in the software is part of the product architecture and is not affected by this repository license change.
