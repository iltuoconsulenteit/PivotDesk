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

- `http://127.0.0.1:8091`

Packaging note: **PyInstaller one-dir** is the recommended first packaging target.

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
- Chart modal (column/bar/line/pie) with print support.
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
- `templates/` – frontend pages
- `static/js/` – frontend logic
- `docs/WIKI.md` – full internal wiki (EN)

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
