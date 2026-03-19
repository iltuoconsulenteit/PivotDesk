# Fix backend principale PivotDesk per i campi calcolati

Il problema mostrato in UI (`Colonne mancanti: Anno`) non dipende più dal modal frontend.

## Sintomo
- Il preset usa `Anno` in filtri/righe/colonne.
- Il backend principale valida le colonne del preset contro le sole colonne fisiche della sorgente.
- `Anno` è un campo virtuale, quindi viene segnalato come mancante.

## Fix obbligatorio nel backend principale

### 1. Durante il salvataggio preset
Quando salvi `/preset-editor/save`, conserva anche:

```python
preset["calculated_fields"] = payload.get("calculated_fields", [])
```

### 2. Quando ricarichi i preset
Ogni endpoint che restituisce i preset (`/pivots`, eventuale loader preset singolo) deve restituire anche:
```python
"calculated_fields": preset.get("calculated_fields", [])
```

### 3. Prima del controllo colonne mancanti
Nel run pivot:

```python
from plugins.calculated_fields.backend import (
    build_calculated_definitions,
    prepare_rows_and_fields,
)

calc_defs = build_calculated_definitions(preset.get("calculated_fields") or [])
rows, available_fields = prepare_rows_and_fields(rows, available_fields, calc_defs)
```

### 4. Solo dopo fai la validazione
```python
required_fields = set(preset.get("filters", [])) | set(preset.get("rows", [])) | set(preset.get("cols", []))
required_fields |= {v["field"] for v in preset.get("values", [])}

missing = sorted(f for f in required_fields if f not in available_fields)
if missing:
    raise ValueError("Colonne mancanti: " + ", ".join(missing))
```

### 5. Anche `/filter-values` deve conoscere i campi calcolati
Se chiedi i valori per `Anno`, devi prima applicare i campi calcolati alle righe sorgente, altrimenti il filtro pagina non potrà popolarsi correttamente.

## Conclusione
Finché il backend principale non:
- salva `calculated_fields`
- li restituisce nei preset
- li applica prima della validazione

il frontend potrà anche mostrare il campo, ma la pivot continuerà a fallire.
