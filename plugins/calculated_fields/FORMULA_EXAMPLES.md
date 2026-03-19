# Esempi formule campi calcolati

Questa versione aggiunge la UI nel costruttore pivot e salva i campi calcolati nel preset.
Il motore backend delle formule va collegato nel passaggio successivo.

## Esempi pensati per hashtag o testo dopo un marcatore
- `after([Descrizione], "#")`
- `after_last([Descrizione], "#")`
- `before([Descrizione], "#")`
- `between([Descrizione], "#", " ")`

## Altri esempi
- `concat([Descrizione], " ", [Importo (EUR)])`
- `upper([Descrizione])`
- `lower([Descrizione])`
