from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class VotingAnalyticsRequest(BaseModel):
    source_id: str
    name_column: str
    votes_column: str
    extra_dimensions: list[str] = Field(default_factory=list)
    threshold_main: float = 0
    threshold_min: float = 0
    thresholds_as_percent: bool = False
    top_n: int = Field(default=200, ge=1, le=5000)


def _normalize_status(votes: float, threshold_main: float, threshold_min: float) -> str:
    if votes >= threshold_main:
        return "Eletto"
    if votes >= threshold_min:
        return "Riserva"
    return "Escluso"


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/voting-analytics", tags=["plugins", "voting_analytics"])

    @router.post("/process")
    def process_voting(payload: VotingAnalyticsRequest):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")

        source = plugin_api.get_source(payload.source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Sorgente non trovata")

        df = plugin_api.load_dataframe_from_source(source).copy()
        if payload.name_column not in df.columns:
            raise HTTPException(status_code=400, detail=f"Colonna nome mancante: {payload.name_column}")
        if payload.votes_column not in df.columns:
            raise HTTPException(status_code=400, detail=f"Colonna voti mancante: {payload.votes_column}")

        extra_dims = [c for c in payload.extra_dimensions if c in df.columns and c not in {payload.name_column, payload.votes_column}]

        work = pd.DataFrame()
        work["name"] = df[payload.name_column].fillna("").astype(str).str.strip()
        work["votes"] = pd.to_numeric(df[payload.votes_column], errors="coerce").fillna(0.0)
        for c in extra_dims:
            work[c] = df[c].fillna("").astype(str).str.strip()

        work = work[work["name"] != ""].copy()
        if work.empty:
            return {
                "ok": True,
                "ranking": [],
                "multi_column": {"Eletti": [], "Riserva": [], "Esclusi": [], "rows": []},
                "pivot_status": [],
                "summary": {"total_rows": 0, "total_votes": 0, "threshold_main": payload.threshold_main, "threshold_min": payload.threshold_min, "thresholds_as_percent": payload.thresholds_as_percent},
                "chart": {"ranking": {"labels": [], "values": []}, "status_distribution": {"labels": ["Eletto", "Riserva", "Escluso"], "values": [0, 0, 0]}},
            }

        total_votes = float(work["votes"].sum())
        threshold_main = float(payload.threshold_main)
        threshold_min = float(payload.threshold_min)
        if payload.thresholds_as_percent:
            threshold_main = total_votes * (threshold_main / 100.0)
            threshold_min = total_votes * (threshold_min / 100.0)

        work["status"] = work["votes"].map(lambda x: _normalize_status(float(x), threshold_main, threshold_min))

        work = work.sort_values(["votes", "name"], ascending=[False, True], kind="stable").reset_index(drop=True)
        work["rank"] = work.index + 1

        ranking_cols = ["rank", "name", "votes", "status"] + extra_dims
        ranking = work[ranking_cols].head(payload.top_n).fillna("").to_dict(orient="records")

        elected = work[work["status"] == "Eletto"]["name"].tolist()
        reserve = work[work["status"] == "Riserva"]["name"].tolist()
        excluded = work[work["status"] == "Escluso"]["name"].tolist()
        max_len = max(len(elected), len(reserve), len(excluded), 0)
        multi_rows: list[dict[str, Any]] = []
        for i in range(max_len):
            multi_rows.append({
                "Eletti": elected[i] if i < len(elected) else "",
                "Riserva": reserve[i] if i < len(reserve) else "",
                "Esclusi": excluded[i] if i < len(excluded) else "",
            })

        group_dims = extra_dims if extra_dims else ["status"]
        pivot_status = (
            work.groupby(group_dims + ["status"], dropna=False)
            .size()
            .reset_index(name="count")
            .fillna("")
            .to_dict(orient="records")
        )

        status_counts = work["status"].value_counts()
        chart = {
            "ranking": {
                "labels": [str(x) for x in work["name"].head(payload.top_n).tolist()],
                "values": [float(x) for x in work["votes"].head(payload.top_n).tolist()],
            },
            "status_distribution": {
                "labels": ["Eletto", "Riserva", "Escluso"],
                "values": [
                    int(status_counts.get("Eletto", 0)),
                    int(status_counts.get("Riserva", 0)),
                    int(status_counts.get("Escluso", 0)),
                ],
            },
        }

        return {
            "ok": True,
            "ranking": ranking,
            "multi_column": {
                "Eletti": elected,
                "Riserva": reserve,
                "Esclusi": excluded,
                "rows": multi_rows,
            },
            "pivot_status": pivot_status,
            "summary": {
                "total_rows": int(len(work.index)),
                "total_votes": total_votes,
                "threshold_main": threshold_main,
                "threshold_min": threshold_min,
                "thresholds_as_percent": bool(payload.thresholds_as_percent),
                "source_id": payload.source_id,
                "name_column": payload.name_column,
                "votes_column": payload.votes_column,
                "extra_dimensions": extra_dims,
            },
            "chart": chart,
        }

    app.include_router(router)

    return {
        "tool_tab": "plugins",
        "card_id": "voting_analytics",
    }
