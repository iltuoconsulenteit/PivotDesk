from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import BaseSourceAdapter


class CsvSourceAdapter(BaseSourceAdapter):
    def load_dataframe(self) -> pd.DataFrame:
        cfg = self._get_config()

        # retrocompatibilità col vecchio formato
        path_value = cfg.get("path") or self.source.get("path")
        if not path_value:
            raise FileNotFoundError("Percorso CSV non configurato")

        path = Path(path_value)
        if not path.exists():
            raise FileNotFoundError(f"CSV non trovato: {path}")

        encoding = str(cfg.get("encoding", "")).strip() or None
        delimiter = cfg.get("delimiter", None)

        encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
        separators = [delimiter] if delimiter else [None, ";", ",", "\t"]

        last_error: Exception | None = None

        for enc in encodings:
            for sep in separators:
                try:
                    if sep is None:
                        df = pd.read_csv(
                            path,
                            encoding=enc,
                            sep=None,
                            engine="python",
                            dtype=str,
                            keep_default_na=False,
                        )
                    else:
                        df = pd.read_csv(
                            path,
                            encoding=enc,
                            sep=sep,
                            dtype=str,
                            keep_default_na=False,
                        )
                    return self._normalize_df(df)
                except Exception as exc:
                    last_error = exc

        raise RuntimeError(f"Impossibile leggere il CSV: {path}. Ultimo errore: {last_error}")