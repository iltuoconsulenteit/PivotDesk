from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text

from .base import BaseSourceAdapter


class MySqlSourceAdapter(BaseSourceAdapter):
    def _get_connection(self) -> dict[str, Any]:
        cfg = self._get_config()
        connection_id = str(cfg.get("connection_id", "")).strip()
        if not connection_id:
            raise RuntimeError("connection_id non configurato per la sorgente MySQL")

        items = self.connections.get("items", []) or []
        conn = next((x for x in items if str(x.get("id", "")).strip() == connection_id), None)
        if not conn:
            raise RuntimeError(f"Connessione MySQL non trovata: {connection_id}")

        return conn

    def _build_engine(self):
        conn = self._get_connection()

        host = str(conn.get("host", "")).strip()
        port = int(conn.get("port", 3306))
        database = str(conn.get("database", "")).strip()
        user = str(conn.get("user", "")).strip()
        password = str(conn.get("password", "")).strip()

        if not host or not database or not user:
            raise RuntimeError("Parametri connessione MySQL incompleti")

        url = (
            f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{database}"
        )
        return create_engine(url)

    def load_dataframe(self) -> pd.DataFrame:
        cfg = self._get_config()
        table = str(cfg.get("table", "")).strip()
        query = str(cfg.get("query", "")).strip()

        if not table and not query:
            raise RuntimeError("Per una sorgente MySQL devi indicare table oppure query")

        if query and not query.lower().lstrip().startswith("select"):
            raise RuntimeError("Sono consentite solo query SELECT")

        engine = self._build_engine()

        with engine.connect() as conn:
            if query:
                df = pd.read_sql(text(query), conn)
            else:
                df = pd.read_sql(f"SELECT * FROM `{table}`", conn)

        return self._normalize_df(df)