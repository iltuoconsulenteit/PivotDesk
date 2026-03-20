# PivotDesk Internal Wiki (EN)

This guide provides a single operational reference for PivotDesk features (user + admin).

> Italian translation: see [`WIKI.it.md`](./WIKI.it.md).

![PivotDesk app logo](../static/img/pivotdesk-logo.png)

---

## 1) Product overview

PivotDesk is a FastAPI + Pandas web app (with desktop launcher/tray) used to:

- load data from multiple source types (CSV, Excel, ODS, MySQL, HTTP JSON);
- build and save pivot presets;
- define row-level calculated fields;
- filter/sort and manage totals/subtotals;
- render pivot-based charts;
- open drilldown details from pivot values;
- print pivot/chart/detail views;
- manage licensing, LAN behavior, branding, and backup/restore.

![PivotDesk workflow](images/pivot-workflow.svg)
![Home screen structure example](images/screen-home.svg)

---

## 2) Quick start

### Requirements
- Python 3.10+
- dependencies from `requirements-core.txt`

### Start
- dev launcher: `python run_pivotdesk.py`
- main launcher: `python main.py`

Default local URL: `http://127.0.0.1:8091`

Default first-run credentials: `admin / admin` (change immediately).

---

## 3) Data sources

Supported source types:
- CSV
- Excel (`.xlsx`, `.xls`, `.xlsm`) with sheet selection
- ODS
- MySQL
- HTTP JSON (`http_json`, `api`, `rest`)

Notes:
- CSV ingestion uses tolerant parsing for real-world files.
- Excel sheets can be listed/selected directly from source forms.
- Free licenses are restricted to CSV-only pivot usage.

---

## 4) Pivot presets and builder

A preset stores:
- filters, rows, columns, values (aggregations);
- view options (subtotals/totals/sorting);
- calculated field definitions.

Core actions:
- create/edit preset;
- source preview;
- preset save/load (JSON);
- backup/export and restore workflows.

![Builder screen structure example](images/screen-builder.svg)

---

## 5) Calculated fields

Calculated fields are server-side virtual columns computed row-by-row.

Function families include:
- text: `trim`, `upper`, `lower`, `replace`, `concat`, `after`, `before`, `token_after`
- date: `year`, `month`, `day`
- numeric: `to_number`, `round`
- time: `minutes_diff`, `hours_diff`
- logic: `if_else`, comparisons (`>=`, `<=`, `==`, `!=`, `>`, `<`)

UI support:
- formula assistant/wizard;
- drag & drop field references;
- output-type handling and validation.

---

## 6) Filters, sorting, totals

- Column and header filters are supported.
- Numeric values are sorted numerically (not lexicographically).
- Filter comparison is numeric-safe (`1` equals `1.0`).
- Subtotals/totals can be toggled by view options and licensing.

---

## 7) Charts from pivot

From the pivot UI you can generate:
- column, bar, line, pie charts;
- selectable label/value fields;
- Top-N extraction.

Dedicated chart printing is available (license-dependent).

Recommended usage by chart type:
- **Column:** compare absolute values across categories.
- **Bar:** same as column, better when labels are long.
- **Line:** show progression/trend over ordered categories.
- **Pie:** show part-to-whole share for limited category counts.

---

## 8) Drilldown (detail view)

List-icon drilldown can be opened from pivot values to inspect contributing records.

Detail modal features:
- tabular drilldown result;
- show/hide columns;
- local column presets (save/apply/delete);
- detail printing.

Drilldown is a premium feature and is license-gated.

![Drilldown and print flow](images/drilldown-print.svg)
![Drilldown modal structure example](images/screen-drilldown.svg)

---

## 9) Printing

Dedicated print flows exist for:
- pivot table;
- chart;
- drilldown detail.

When `print_show_logos` is enabled, branded footer logos are included; customer logo is also included when available/licensed.

---

## 10) Licensing tiers

## Free tier
- on-screen pivots from CSV sources only;
- premium features disabled (print, charts, drilldown, premium backup/restore);
- LAN exposure disabled by policy.

## Paid / Developer tiers
- premium features available based on feature flags;
- LAN can be enabled (license dependent);
- branding, backup/restore, charts, drilldown, printing.

![License tiers](images/license-tiers.svg)

---

## 11) LAN diagnostics and firewall helpers

Key endpoints:
- `GET /lan/status`
- `POST /lan/probe/new`
- `GET /lan/probe/{id}`
- `GET /lan/probe/result`
- `POST /lan/firewall/open`

Recommended workflow:
1. check `/lan/status`;
2. run a probe;
3. open firewall if needed;
4. restart launcher with correct bind/license mode.

---

## 12) Branding

For eligible admin/license contexts:
- upload customer logo;
- show logo on login/header;
- include logo in supported print layouts.

---

## 13) User management (admin)

Admin user management is available in the dedicated page (`templates/admin_users.html`) and includes:

- user creation (username, email, role, password);
- role and activation controls;
- password reset and delete actions;
- admin navigation shortcuts back to main app.

![User management structure example](images/screen-users.svg)

---

## 14) Backup and restore

Endpoints:
- `GET /admin/backup/export`
- `POST /admin/backup/restore`

Covers main settings and pivot presets for migration/rollback scenarios.

---

## 15) Internationalization

Language catalogs:
- `static/languages/en.json`
- `static/languages/it.json`

Language can be switched from settings UI.

---

## 16) Home layout usability

The main dashboard (`templates/index.html`) now groups controls in a compact grid:

- Source
- Preset
- Page filters
- Layout & options quickbar

Each panel has a **Show/Hide** toggle so users can collapse less-used sections and keep the pivot output area visible without excessive scrolling.
On wide screens, the user context bar and top action menu are aligned on one row to avoid wasting vertical space before the pivot result.
On tablet/smartphone breakpoints, menu groups reflow and dropdown entries open inline so submenu items remain visible and usable.
The layout quickbar also shows the active view summary on the same row and includes a **Wiki** button that opens a slide-out side panel.
The duplicate lower layout-status line has been removed; when a pivot run succeeds, summary remains in quickbar only. The wiki panel embeds scrollable WIKI content and can be resized (width slider) without blocking the main frontend.
Wiki panel content is loaded from `GET /wiki/content?lang=it|en`; panel width can also be changed by dragging its left border.

---

## 17) Project map

- `app.py` → API and web routes
- `services/pivot_engine.py` → pivot engine
- `services/source_manager.py` → source management
- `plugins/calculated_fields/backend.py` → formula engine
- `templates/` → frontend templates
- `static/js/` → frontend logic
- `run_pivotdesk.py`, `main.py`, `tray.py` → launcher/tray

---

## 18) Troubleshooting

- Port already in use → change `config.json` port or stop existing process.
- Source load issues → validate file path/sheet/encoding.
- Feature locked → verify license tier and feature flags.
- LAN unreachable → inspect `/lan/status`, probe, firewall.
- Missing templates → check `templates/` folder presence.

---

## 19) Recommended operating checklist

1. Configure source.
2. Build pivot preset.
3. (Optional) add calculated fields.
4. Validate filters/totals/subtotals.
5. Validate chart/drilldown/print based on license.
6. Export backup snapshot.
