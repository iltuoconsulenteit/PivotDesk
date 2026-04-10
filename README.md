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
- licensing modules (`licensing/`)
- Jinja templates (`templates/`)

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

- Demo CSV dataset: `demo/demo_sales.csv`
- Demo source seed: `sources.json` (`id: demo_sales`)
- Demo pivot preset: `pivots/demo_sales/demo_sales_overview.json`

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
- `plugins/multi_pivot_derived/plugin.py` – derive/cross data from multiple pivots (optional plugin, disabled by default; demo output is watermarked)
- `templates/` – frontend pages
- `static/js/` – frontend logic
- `docs/WIKI.md` – full internal wiki (EN)
- Source-level calculated fields are stored in source config (`calculated_fields`) and are automatically applied during source loading; this makes them available to all plugins (including cross-source lookup and multi-source merge) without redefining formulas per plugin request.
- Optional plugin `google_account_sheets` (disabled by default) enables OAuth device-flow authentication for private Google Drive Sheets and can be licensed as a Pro/Full add-on.
- For direct Google connect from Source Manager, set OAuth credentials once via env (`PIVOTDESK_GOOGLE_CLIENT_ID`, `PIVOTDESK_GOOGLE_CLIENT_SECRET`) or `config.json` under `google_oauth.client_id` / `google_oauth.client_secret`.
- Multi-source merge plugin can now persist merge output as a generated CSV source in `DATA_DIR/generated_sources`, so merged datasets can be reused like normal sources.
- Multi-source merge plugin also exposes template helpers: `POST /plugin/multi-source-merge/template/headers` (derive template columns from source or CSV/XLSX/ODS headers) and `POST /plugin/multi-source-merge/template/suggest-map` (auto-suggest target/source field mapping for guided drag/drop linking UX).
- Multi-source merge plugin now supports template persistence + execution: create/list/get/delete templates (`/template/save`, `/template/list`, `/template/{id}`) and run append/union merges from a selected template (`POST /plugin/multi-source-merge/build-from-template`) so mapped rows from selected sources are appended under the same target headers.
- Source Manager plugin panel includes a guided template-first merge flow with drag&drop mapping (save/load template headers, drag source fields onto template slots, auto-suggest mappings per source, run merge from template) for schema-aligned append across heterogeneous sources.

Plugin visibility/enablement:
- `GET /plugins/status` shows runtime status + license allow/deny flags.
- `POST /plugins/config/save` persists plugin enable/disable map (`plugins.json`, restart required).
- Plugin discovery scans these folders (first match by plugin id wins): `APP_HOME/plugins`, runtime `plugins/`, bundled `resource/plugins`.
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
