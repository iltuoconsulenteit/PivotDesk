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
        import_all_sheets = bool(cfg.get("import_all_sheets", False))

        if import_all_sheets:
            all_sheets = pd.read_excel(
                path,
                sheet_name=None,
                header=header_row,
                dtype=str,
                engine="openpyxl",
            )
            frames = []
            for sheet_label, sheet_df in (all_sheets or {}).items():
                if sheet_df is None:
                    continue
                tmp = sheet_df.copy()
                tmp["_sheet"] = str(sheet_label or "")
                frames.append(tmp)
            if not frames:
                return self._normalize_df(pd.DataFrame())
            merged = pd.concat(frames, ignore_index=True)
            return self._normalize_df(merged)

        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=header_row,
            dtype=str,
            engine="openpyxl",
        )

        return self._normalize_df(df)
