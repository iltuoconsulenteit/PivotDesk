# PivotDesk Internal Wiki (EN)

This guide provides a single operational reference for PivotDesk features (user + admin).

> Italian translation: see [`WIKI.it.md`](./WIKI.it.md).

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

## 13) Backup and restore

Endpoints:
- `GET /admin/backup/export`
- `POST /admin/backup/restore`

Covers main settings and pivot presets for migration/rollback scenarios.

---

## 14) Internationalization

Language catalogs:
- `static/languages/en.json`
- `static/languages/it.json`

Language can be switched from settings UI.

---

## 15) Project map

- `app.py` → API and web routes
- `services/pivot_engine.py` → pivot engine
- `services/source_manager.py` → source management
- `plugins/calculated_fields/backend.py` → formula engine
- `templates/` → frontend templates
- `static/js/` → frontend logic
- `run_pivotdesk.py`, `main.py`, `tray.py` → launcher/tray

---

## 16) Troubleshooting

- Port already in use → change `config.json` port or stop existing process.
- Source load issues → validate file path/sheet/encoding.
- Feature locked → verify license tier and feature flags.
- LAN unreachable → inspect `/lan/status`, probe, firewall.
- Missing templates → check `templates/` folder presence.

---

## 17) Recommended operating checklist

1. Configure source.
2. Build pivot preset.
3. (Optional) add calculated fields.
4. Validate filters/totals/subtotals.
5. Validate chart/drilldown/print based on license.
6. Export backup snapshot.
