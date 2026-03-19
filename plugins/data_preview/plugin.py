from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/data-preview", tags=["plugins", "data_preview"])

    @router.get("/preview")
    def preview(
        source_id: str = Query(...),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")

        source = plugin_api.get_source(source_id)
        df = plugin_api.load_dataframe_from_source(source)

        total_rows = int(len(df))
        slice_df = df.iloc[offset:offset + limit].copy()

        return {
            "source_id": source_id,
            "offset": offset,
            "limit": limit,
            "total_rows": total_rows,
            "columns": [str(c) for c in slice_df.columns],
            "rows": slice_df.fillna("").to_dict(orient="records"),
        }

    @router.get("/profile")
    def profile(source_id: str = Query(...)):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")

        source = plugin_api.get_source(source_id)
        df = plugin_api.load_dataframe_from_source(source)

        columns = []
        for col in df.columns:
            s = df[col]
            columns.append({
                "name": str(col),
                "dtype": str(s.dtype),
                "non_null": int(s.notna().sum()),
                "nulls": int(s.isna().sum()),
                "distinct": int(s.nunique(dropna=True)),
            })

        return {
            "source_id": source_id,
            "rows": int(len(df)),
            "columns": columns,
        }

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
