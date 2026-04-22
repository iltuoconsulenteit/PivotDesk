# Moduli PivotDesk

Questa cartella separa i **moduli applicativi** dai **plugin**:

- `modules/` = funzionalità/pagine principali (core o ibride core+plugin).
- `plugins/` = estensioni tecniche che aggiungono endpoint, provider o tool.

Ogni modulo contiene un file `module.json` con metadati stabili (`id`, `name`, `kind`, `plugin_id`, `ui`, ...),
così la manutenzione resta ordinata anche quando aumentano plugin e varianti.

Per la navigazione, il modulo `main_menu` include anche `menu.json` con layout (`topbar` o `sidebar`) e sezioni/voci renderizzate in homepage.
