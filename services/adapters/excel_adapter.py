from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import BaseSourceAdapter


class ExcelSourceAdapter(BaseSourceAdapter):
    def load_dataframe(self) -> pd.DataFrame:
        cfg = self._get_config()

        path_value = cfg.get("path") or self.source.get("path")
        if not path_value:
            raise FileNotFoundError("Percorso XLSX non configurato")

        path = Path(path_value)
        if not path.exists():
            raise FileNotFoundError(f"File Excel non trovato: {path}")

        sheet_name = cfg.get("sheet_name", 0)
        header_row = cfg.get("header_row", 0)

        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=header_row,
            dtype=str,
            engine="openpyxl",
        )

        return self._normalize_df(df)