from __future__ import annotations

import pandas as pd

from services.google_account_sheets import read_sheet_as_rows

from .base import BaseSourceAdapter


class GoogleAccountSheetAdapter(BaseSourceAdapter):
    def load_dataframe(self) -> pd.DataFrame:
        cfg = self._get_config()
        connection_id = str(cfg.get("connection_id") or "").strip()
        spreadsheet_id = str(cfg.get("spreadsheet_id") or cfg.get("sheet_id") or "").strip()
        worksheet = str(cfg.get("worksheet") or cfg.get("sheet_name") or "").strip()
        cell_range = str(cfg.get("range") or cfg.get("cell_range") or "").strip()

        if not connection_id:
            raise RuntimeError("connection_id Google obbligatorio per sorgente gsheet_account")
        if not spreadsheet_id:
            raise RuntimeError("spreadsheet_id Google obbligatorio per sorgente gsheet_account")

        rows = read_sheet_as_rows(
            connection_id=connection_id,
            spreadsheet_id=spreadsheet_id,
            worksheet=worksheet,
            cell_range=cell_range,
        )
        if not rows:
            return self._normalize_df(pd.DataFrame())

        max_cols = max(len(r) for r in rows)
        padded = [r + [""] * (max_cols - len(r)) for r in rows]

        headers = [str(x).strip() for x in padded[0]]
        if not any(headers):
            headers = [f"col_{i+1}" for i in range(max_cols)]
        else:
            seen: dict[str, int] = {}
            normalized_headers: list[str] = []
            for i, h in enumerate(headers):
                base = h or f"col_{i+1}"
                count = seen.get(base, 0) + 1
                seen[base] = count
                normalized_headers.append(base if count == 1 else f"{base}_{count}")
            headers = normalized_headers

        data_rows = padded[1:] if len(padded) > 1 else []
        df = pd.DataFrame(data_rows, columns=headers)
        return self._normalize_df(df)
