# Integrazione licenza demo

## 1. Verifica licenza all'avvio

Nel tuo `main.py`, subito dopo gli import, aggiungi:

```python
from licensing.license_runtime import get_current_license
```

Poi, all'inizio di `main()`:

```python
license_result = get_current_license()
write_log(f"Licenza: {license_result.status} - {license_result.message}")
if not license_result.valid:
    raise SystemExit(f"Licenza non valida: {license_result.message}")
```

## 2. Esponi lo stato licenza al frontend

Nel backend FastAPI, in una route che renderizza il template principale, passa al template questo payload:

```python
from licensing.license_runtime import get_current_license, is_demo_license

license_result = get_current_license()
license_payload = {
    "isDemo": is_demo_license(),
    "restricted": ["subtotals", "preview", "print"] if is_demo_license() else [],
    "edition": (license_result.license_data or {}).get("edition", "Unknown"),
}
```

Nel template HTML principale, prima dei tuoi script applicativi:

```html
<script>
  window.PivotDeskLicense = {{ license_payload | tojson }};
</script>
<script src="/static/js/demo-guard.js"></script>
```

## 3. Blocca i pulsanti demo

Associa questi selettori ai tuoi pulsanti reali:

```html
<script>
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.PivotDeskDemoGuard) return;
    PivotDeskDemoGuard.intercept("[data-feature='subtotals']", "subtotals");
    PivotDeskDemoGuard.intercept("[data-feature='preview']", "preview");
    PivotDeskDemoGuard.intercept("[data-feature='print']", "print");
  });
</script>
```

E aggiungi gli attributi ai pulsanti:

```html
<button data-feature="subtotals">Subtotali</button>
<button data-feature="preview">Anteprima</button>
<button data-feature="print">Stampa</button>
```

## 4. Se vuoi bloccare anche lato backend

Per evitare bypass dal browser, nei punti Python che eseguono davvero subtotali, anteprima o stampa, usa:

```python
from licensing.license_runtime import feature_enabled, demo_message

if not feature_enabled("print"):
    raise PermissionError(demo_message("print"))
```

Stesso schema per `subtotals` e `preview`.

## 5. Licenza demo di fallback

Se in `%APPDATA%\\PivotDesk\\license.json` non esiste una licenza installata, il runtime userà automaticamente `licenses/demo-license.json`.
