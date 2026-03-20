from __future__ import annotations

from typing import Any

import pandas as pd


AGG_MAP = {
    "sum": "sum",
    "count": "count",
    "avg": "mean",
    "min": "min",
    "max": "max",
}


def _looks_like_date_field(field_name: str | None) -> bool:
    f = str(field_name or "").strip().upper()
    if not f:
        return False

    return (
        f == "DATA"
        or f == "DATE"
        or f.startswith("DATA")
        or f.endswith("_DATA")
        or "_DATA_" in f
        or f.endswith("_DT")
        or f.startswith("DT_")
        or f in {"DATA_FC", "DATA_REGISTRAZIONE", "DATA_PAGAMENTO", "DATA_INCASSO"}
    )


def _parse_date_series(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    s = s.replace("", pd.NA)

    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)

    missing = dt.isna() & s.notna()
    if missing.any():
        dt2 = pd.to_datetime(s[missing], errors="coerce", dayfirst=False)
        dt.loc[missing] = dt2

    return dt


def normalize_df(
    df: pd.DataFrame,
    numeric_fields: list[str] | None = None,
    date_fields: list[str] | None = None,
) -> pd.DataFrame:
    out = df.copy()

    for col in numeric_fields or []:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in date_fields or []:
        if col in out.columns:
            out[col] = _parse_date_series(out[col])

    return out


def apply_filters(df: pd.DataFrame, filters: dict[str, Any] | None = None) -> pd.DataFrame:
    if not filters:
        return df

    out = df.copy()

    for field, value in filters.items():
        if field not in out.columns:
            continue
        if value is None or str(value).strip() == "":
            continue

        value_str = str(value).strip()

        if _looks_like_date_field(field):
            series_dt = _parse_date_series(out[field])
            target_dt = pd.to_datetime(value_str, errors="coerce", dayfirst=False)

            if pd.notna(target_dt):
                out = out[series_dt.dt.strftime("%Y-%m-%d") == target_dt.strftime("%Y-%m-%d")]
                continue

        # Numeric-safe filtering: if filter value is numeric and column can be parsed
        # as numeric, compare numerically to avoid mismatches like "1" vs "1.0".
        target_num = pd.to_numeric(pd.Series([value_str]), errors="coerce").iloc[0]
        if pd.notna(target_num):
            series_num = pd.to_numeric(out[field], errors="coerce")
            if series_num.notna().any():
                out = out[series_num == float(target_num)]
                continue

        out = out[out[field].astype(str).str.strip() == value_str]

    return out


def _options_from_preset(preset: dict[str, Any]) -> dict[str, Any]:
    raw = preset.get("options", {}) or {}
    return {
        "measures_layout": str(raw.get("measures_layout", "vertical")).strip().lower() or "vertical",
        "show_row_totals": bool(raw.get("show_row_totals", True)),
        "show_col_totals": bool(raw.get("show_col_totals", True)),
        "show_subtotals": bool(raw.get("show_subtotals", False)),
        "sort_enabled": bool(raw.get("sort_enabled", False)),
        "sort_field": str(raw.get("sort_field", "")).strip(),
        "sort_direction": str(raw.get("sort_direction", "asc")).strip().lower() or "asc",
    }


def _build_requested_values(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    for item in values or []:
        field = str(item.get("field", "")).strip()
        agg = str(item.get("agg", "sum")).strip().lower() or "sum"
        label = str(item.get("label", "")).strip() or field

        if not field:
            continue
        if agg not in AGG_MAP:
            agg = "sum"

        out.append(
            {
                "field": field,
                "agg": agg,
                "agg_pandas": AGG_MAP[agg],
                "label": label,
            }
        )

    return out


def _remove_row_totals(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return table

    if isinstance(table.index, pd.MultiIndex):
        mask = pd.Series([True] * len(table.index), index=table.index)
        for lvl in range(table.index.nlevels):
            mask &= pd.Index(table.index.get_level_values(lvl)).astype(str) != "Totale"
        return table[mask.values]

    return table[pd.Index(table.index).astype(str) != "Totale"]


def _remove_col_totals(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return table

    if isinstance(table.columns, pd.MultiIndex):
        keep_cols = []
        for col in table.columns:
            col_tuple = col if isinstance(col, tuple) else (col,)
            if not any(str(part).strip() == "Totale" for part in col_tuple):
                keep_cols.append(col)
        return table.loc[:, keep_cols]

    return table.loc[:, pd.Index(table.columns).astype(str) != "Totale"]


def _safe_index_names(index: pd.Index | pd.MultiIndex, rows: list[str]) -> list[str]:
    if rows:
        return rows[:]

    if isinstance(index, pd.MultiIndex):
        out: list[str] = []
        for i, name in enumerate(index.names):
            text = str(name).strip() if name is not None else ""
            out.append(text or f"Riga_{i + 1}")
        return out

    text = str(index.name).strip() if getattr(index, "name", None) is not None else ""
    return [text or "Riga"]


def _col_header_from_key(col: Any) -> str:
    if isinstance(col, tuple):
        parts = []
        for x in col:
            sx = str(x).strip()
            if not sx or sx == "nan":
                continue
            parts.append(sx)

        if not parts:
            return "Totale"

        if len(parts) == 1 and parts[0] == "Totale":
            return "Totale"

        return " | ".join(parts)

    text = str(col).strip()
    if not text:
        return "Totale"
    if text == "Totale":
        return "Totale"
    return text


def _sort_result(table: pd.DataFrame, options: dict[str, Any]) -> pd.DataFrame:
    if table.empty or not options.get("sort_enabled"):
        return table

    sort_field = options.get("sort_field", "")
    if not sort_field or sort_field not in table.columns:
        return table

    ascending = options.get("sort_direction", "asc") == "asc"

    try:
        return table.sort_values(by=sort_field, ascending=ascending, kind="stable")
    except Exception:
        return table


def _pivot_single_value(
    df: pd.DataFrame,
    rows: list[str],
    cols: list[str],
    req: dict[str, str],
    show_row_totals: bool,
    show_col_totals: bool,
) -> pd.DataFrame:
    margins = bool(show_row_totals or show_col_totals)

    table = pd.pivot_table(
        df,
        index=rows or None,
        columns=cols or None,
        values=req["field"],
        aggfunc=req["agg_pandas"],
        fill_value=0,
        margins=margins,
        margins_name="Totale",
        dropna=False,
        observed=False,
    )

    if not show_row_totals:
        table = _remove_row_totals(table)

    if not show_col_totals:
        table = _remove_col_totals(table)

    return table


def _get_group_key(idx: Any, rows: list[str]) -> tuple[Any, ...]:
    idx_tuple = idx if isinstance(idx, tuple) else (idx,)
    if not rows:
        return idx_tuple
    if len(rows) <= 1:
        return idx_tuple[:1]
    return idx_tuple[:-1]


def _build_group_subtotal_record(
    group_key: tuple[Any, ...],
    idx_names: list[str],
    group_rows: list[dict[str, Any]],
    include_measure: bool = True,
) -> dict[str, Any]:
    subtotal: dict[str, Any] = {}
    subtotal["__row_type__"] = "subtotal"

    for i, name in enumerate(idx_names):
        subtotal[name] = group_key[i] if i < len(group_key) else ""

    if include_measure:
        subtotal["Misura"] = "Subtotale"

    numeric_cols = set()
    for row in group_rows:
        for k, v in row.items():
            if k in idx_names or (include_measure and k == "Misura"):
                continue
            if isinstance(v, (int, float)) and not pd.isna(v):
                numeric_cols.add(k)

    for col in numeric_cols:
        total = 0.0
        for row in group_rows:
            v = row.get(col)
            if isinstance(v, (int, float)) and not pd.isna(v):
                total += float(v)
        subtotal[col] = total

    return subtotal


def _build_vertical_table(
    pivot_tables: list[tuple[dict[str, str], pd.DataFrame]],
    rows: list[str],
    show_subtotals: bool,
) -> pd.DataFrame:
    if not pivot_tables:
        return pd.DataFrame()

    first_table = pivot_tables[0][1]
    idx_names = _safe_index_names(first_table.index, rows)
    include_measure = len(pivot_tables) > 1

    all_indexes: list[Any] = []
    seen = set()
    for _, table in pivot_tables:
        for idx in table.index:
            key = idx if isinstance(idx, tuple) else (idx,)
            if key not in seen:
                seen.add(key)
                all_indexes.append(idx)

    data_rows: list[dict[str, Any]] = []

    current_group_key = None
    current_group_rows: list[dict[str, Any]] = []

    for idx in all_indexes:
        idx_tuple = idx if isinstance(idx, tuple) else (idx,)
        group_key = _get_group_key(idx, rows)

        if show_subtotals and current_group_key is not None and group_key != current_group_key:
            if current_group_rows:
                data_rows.append(
                    _build_group_subtotal_record(
                        current_group_key,
                        idx_names,
                        current_group_rows,
                        include_measure=include_measure,
                    )
                )
            current_group_rows = []

        base = {
            idx_names[i]: idx_tuple[i] if i < len(idx_tuple) else ""
            for i in range(len(idx_names))
        }
        base["__row_type__"] = ""

        for req, table in pivot_tables:
            if idx not in table.index:
                continue

            row_values = table.loc[idx]
            record = dict(base)
            if include_measure:
                record["Misura"] = req["label"]

            for col in table.columns:
                header = _col_header_from_key(col)
                record[header] = row_values[col]

            data_rows.append(record)
            if show_subtotals:
                current_group_rows.append(record)

        current_group_key = group_key

    if show_subtotals and current_group_key is not None and current_group_rows:
        data_rows.append(
            _build_group_subtotal_record(
                current_group_key,
                idx_names,
                current_group_rows,
                include_measure=include_measure,
            )
        )

    out = pd.DataFrame(data_rows)
    desired = idx_names + (["Misura"] if include_measure else [])
    extra = [c for c in out.columns if c not in desired]
    return out[desired + extra] if not out.empty else pd.DataFrame(columns=desired)


def _build_horizontal_group_subtotal_record(
    group_key: tuple[Any, ...],
    idx_names: list[str],
    group_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    subtotal: dict[str, Any] = {}
    subtotal["__row_type__"] = "subtotal"

    for i, name in enumerate(idx_names):
        subtotal[name] = group_key[i] if i < len(group_key) else ""

    numeric_cols = set()
    for row in group_rows:
        for k, v in row.items():
            if k in idx_names:
                continue
            if isinstance(v, (int, float)) and not pd.isna(v):
                numeric_cols.add(k)

    for col in numeric_cols:
        total = 0.0
        for row in group_rows:
            v = row.get(col)
            if isinstance(v, (int, float)) and not pd.isna(v):
                total += float(v)
        subtotal[col] = total

    return subtotal


def _build_horizontal_table(
    pivot_tables: list[tuple[dict[str, str], pd.DataFrame]],
    rows: list[str],
    show_subtotals: bool,
) -> pd.DataFrame:
    if not pivot_tables:
        return pd.DataFrame()

    first_table = pivot_tables[0][1]
    idx_names = _safe_index_names(first_table.index, rows)

    all_indexes: list[Any] = []
    seen_idx = set()
    for _, table in pivot_tables:
        for idx in table.index:
            key = idx if isinstance(idx, tuple) else (idx,)
            if key not in seen_idx:
                seen_idx.add(key)
                all_indexes.append(idx)

    all_col_keys: list[Any] = []
    seen_cols = set()
    for _, table in pivot_tables:
        for col in table.columns:
            key = col if isinstance(col, tuple) else (col,)
            if key not in seen_cols:
                seen_cols.add(key)
                all_col_keys.append(col)

    data_rows: list[dict[str, Any]] = []

    current_group_key = None
    current_group_rows: list[dict[str, Any]] = []

    for idx in all_indexes:
        idx_tuple = idx if isinstance(idx, tuple) else (idx,)
        group_key = _get_group_key(idx, rows)

        if show_subtotals and current_group_key is not None and group_key != current_group_key:
            if current_group_rows:
                data_rows.append(
                    _build_horizontal_group_subtotal_record(current_group_key, idx_names, current_group_rows)
                )
            current_group_rows = []

        record = {
            idx_names[i]: idx_tuple[i] if i < len(idx_tuple) else ""
            for i in range(len(idx_names))
        }
        record["__row_type__"] = ""

        for col in all_col_keys:
            header = _col_header_from_key(col)

            for req, table in pivot_tables:
                col_label = f"{header} | {req['label']}" if header else req["label"]

                value = ""
                if idx in table.index and col in table.columns:
                    value = table.loc[idx, col]

                record[col_label] = value

        data_rows.append(record)
        if show_subtotals:
            current_group_rows.append(record)

        current_group_key = group_key

    if show_subtotals and current_group_key is not None and current_group_rows:
        data_rows.append(
            _build_horizontal_group_subtotal_record(current_group_key, idx_names, current_group_rows)
        )

    out = pd.DataFrame(data_rows)
    fixed = idx_names[:]
    extra = [c for c in out.columns if c not in fixed]
    return out[fixed + extra] if not out.empty else pd.DataFrame(columns=fixed)


def run_pivot(df: pd.DataFrame, preset: dict[str, Any]) -> pd.DataFrame:
    rows = preset.get("rows", []) or []
    cols = preset.get("cols", []) or []
    values = preset.get("values", []) or []

    if not values:
        return pd.DataFrame()

    options = _options_from_preset(preset)
    requested_values = _build_requested_values(values)

    if not requested_values:
        return pd.DataFrame()

    pivot_tables: list[tuple[dict[str, str], pd.DataFrame]] = []

    for req in requested_values:
        table = _pivot_single_value(
            df=df,
            rows=rows,
            cols=cols,
            req=req,
            show_row_totals=options.get("show_row_totals", True),
            show_col_totals=options.get("show_col_totals", True),
        )
        pivot_tables.append((req, table))

    if options.get("measures_layout", "horizontal") == "horizontal":
        result = _build_horizontal_table(
            pivot_tables,
            rows,
            bool(options.get("show_subtotals", False)),
        )
    else:
        result = _build_vertical_table(
            pivot_tables,
            rows,
            bool(options.get("show_subtotals", False)),
        )

    return _sort_result(result, options)


def _format_cell(value: Any) -> str:
    if pd.isna(value):
        return ""

    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    if isinstance(value, int):
        return str(value)

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")

    return str(value)


def table_to_html(table: pd.DataFrame) -> str:
    if table is None or table.empty:
        return '<table class="pd-table"><tbody><tr><td>Nessun dato</td></tr></tbody></table>'

    row_type_col = "__row_type__" if "__row_type__" in table.columns else None
    cols = [c for c in table.columns if c != row_type_col]

    html = ['<table class="pd-table">']

    # header
    html.append("<thead><tr>")
    for col in cols:
        html.append(f"<th>{_format_cell(col)}</th>")
    html.append("</tr></thead>")

    html.append("<tbody>")

    for _, row in table.iterrows():

        values = [str(_format_cell(row[c])).strip() for c in cols]
        row_type = str(row.get(row_type_col, "")).strip().lower() if row_type_col else ""

        is_total = any(v.upper() == "TOTALE" for v in values)
        is_subtotal = row_type == "subtotal" or any("SUBTOTALE" in v.upper() for v in values)

        css = ""
        if is_total:
            css = ' class="total-row"'
        elif is_subtotal:
            css = ' class="subtotal-row"'

        html.append(f"<tr{css}>")

        for col in cols:
            html.append(f"<td>{_format_cell(row[col])}</td>")

        html.append("</tr>")

    html.append("</tbody></table>")

    return "".join(html)
