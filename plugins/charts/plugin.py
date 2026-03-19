from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/charts", tags=["plugins", "charts"])

    @router.get("/source-series")
    def source_series(
        source_id: str = Query(...),
        category_field: str = Query(...),
        value_field: str = Query(...),
        limit: int = Query(20, ge=1, le=200),
    ):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")

        source = plugin_api.get_source(source_id)
        df = plugin_api.load_dataframe_from_source(source)

        missing = [f for f in [category_field, value_field] if f not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Campi mancanti: {', '.join(missing)}")

        grouped = (
            df[[category_field, value_field]]
            .dropna(subset=[category_field])
            .groupby(category_field, dropna=True)[value_field]
            .sum(numeric_only=True)
            .sort_values(ascending=False)
            .head(limit)
        )

        return {
            "source_id": source_id,
            "category_field": category_field,
            "value_field": value_field,
            "labels": [str(x) for x in grouped.index.tolist()],
            "values": [float(x) if x is not None else 0.0 for x in grouped.tolist()],
        }

    @router.get("/ping")
    def ping():
        return {"ok": True, "plugin": "charts"}

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
