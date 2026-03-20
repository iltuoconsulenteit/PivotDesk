# Esempi formule campi calcolati

Questa pagina raccoglie esempi utili per il plugin `calculated_fields` (frontend + backend formule).

## Esempi pensati per hashtag o testo dopo un marcatore
- `after([Descrizione], "#")`
- `after_last([Descrizione], "#")`
- `before([Descrizione], "#")`
- `between([Descrizione], "#", " ")`
- `token_after([Descrizione], "CRO:")`

## Altri esempi testo/numero
- `concat([Descrizione], " ", [Importo (EUR)])`
- `upper([Descrizione])`
- `lower([Descrizione])`
- `round(to_number([Importo (EUR)]), 2)`

## Esempi su orari e condizioni
- `minutes_diff([Uscita], [Ingresso])`
- `hours_diff([Uscita], [Ingresso])`
- `if_else(hours_diff([Uscita], [Ingresso]) >= 8, 1, 0)`
- `if_else(gte(hours_diff([Uscita], [Ingresso]), 8), "OK", "KO")`
