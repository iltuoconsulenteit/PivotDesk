from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseSourceAdapter(ABC):
    def __init__(self, source: dict[str, Any], connections: dict[str, Any] | None = None):
        self.source = source
        self.connections = connections or {"items": []}

    @abstractmethod
    def load_dataframe(self) -> pd.DataFrame:
        raise NotImplementedError

    def get_fields(self) -> list[str]:
        df = self.load_dataframe()
        return [str(c).strip() for c in df.columns]

    def get_preview(self, limit: int = 100) -> pd.DataFrame:
        df = self.load_dataframe()
        return df.head(limit)

    def _get_config(self) -> dict[str, Any]:
        return self.source.get("config", {}) or {}

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df.columns = [str(c).strip() for c in df.columns]
        return df.fillna("")