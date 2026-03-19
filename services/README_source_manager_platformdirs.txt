Aggiornamento source_manager per supporto multipiattaforma

Cosa cambia:
- connections.json non viene più letto solo da data/connections.json nella root progetto
- usa la stessa cartella dati utente definita da services.config_loader.DATA_DIR
- migra automaticamente il file legacy se esiste

Come applicarlo:
- sostituisci il file esistente con source_manager_platformdirs.py rinominandolo in source_manager.py

Prerequisito:
- config_loader.py deve già essere aggiornato con la versione platformdirs
