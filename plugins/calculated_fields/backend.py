"""
Calculated fields plugin backend for PivotDesk.

Phase A:
- row-level calculated fields only
- safe whitelisted function language
- formulas persisted in presets

Supported syntax:
- field references: [Nome Campo]
- string literals: "abc", 'abc'
- numeric literals: 12, 12.5, -3
- booleans: true, false
- function calls:
    after(text, marker)
    after_last(text, marker)
    before(text, marker)
    before_last(text, marker)
    between(text, start, end)
    concat(a, b, ...)
    upper(x)
    lower(x)
    trim(x)
    replace(text, old, new)
    year(x)
    month(x)
    day(x)
    to_number(x)
    to_text(x)
    round(x, digits?)
    minutes_diff(end_time, start_time)
    hours_diff(end_time, start_time)
    if_else(condition, true_value, false_value)
    gte(a, b), gt(a, b), lte(a, b), lt(a, b), eq(a, b), neq(a, b)
    token_after(text, marker, case_sensitive?)

Supported operators:
- >=, <=, ==, !=, >, <
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import math
import re
from typing import Any, Callable


@dataclass
class CalculatedFieldDefinition:
    name: str
    formula: str
    field_type: str = "string"
    enabled: bool = True


class FormulaError(ValueError):
    """User-facing formula error."""


FIELD_REF_RE = re.compile(r"\[([^\[\]]+)\]")
FUNC_CALL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
    return str(value)


def _normalize_spaces(text: str) -> str:
    return str(text).replace("\xa0", " ").strip()


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = _normalize_spaces(_to_text(value))
    if not text:
        return None

    known_formats = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%d/%m/%y",
        "%d-%m-%y",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    )
    for fmt in known_formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value

    text = _normalize_spaces(_to_text(value))
    if not text:
        return None
    text = text.strip("'\"")

    # Excel-like fractional day (e.g. 0.5 -> 12:00:00)
    numeric = _to_number(value)
    if numeric is not None and 0 <= numeric < 1:
        total_seconds = int(round(numeric * 24 * 60 * 60))
        total_seconds = total_seconds % (24 * 60 * 60)
        hh = total_seconds // 3600
        mm = (total_seconds % 3600) // 60
        ss = total_seconds % 60
        return time(hour=hh, minute=mm, second=ss)

    known_formats = (
        "%H:%M",
        "%H:%M:%S",
        "%H:%M:%S.%f",
        "%H:%M:%S,%f",
        "%H.%M",
        "%H.%M.%S",
        "%I:%M %p",
        "%I:%M:%S %p",
    )
    for fmt in known_formats:
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass

    # Try ISO-like datetime values and use the time component.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).time()
    except ValueError:
        pass

    # Fallback: extract first time-like token from longer text.
    token_match = re.search(r"(\d{1,2}[:.]\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?(?:\s*[APap][Mm])?)", text)
    if token_match:
        token = token_match.group(1).strip().replace(".", ":")
        token_formats = ("%H:%M", "%H:%M:%S", "%H:%M:%S.%f", "%I:%M %p", "%I:%M:%S %p")
        for fmt in token_formats:
            try:
                return datetime.strptime(token, fmt).time()
            except ValueError:
                pass

    return None


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)

    text = _normalize_spaces(_to_text(value))
    if not text:
        return None

    text = text.replace("€", "").replace("EUR", "").replace("eur", "")
    text = text.replace(" ", "")

    if "," in text and "." in text:
        # Assume European thousands separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        # Remove thousands separators if they appear like 1.234.567
        if text.count(".") > 1:
            text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def fn_after(text: Any, marker: Any) -> str:
    text_s = _to_text(text)
    marker_s = _to_text(marker)
    if not marker_s:
        return ""
    idx = text_s.find(marker_s)
    return text_s[idx + len(marker_s):] if idx >= 0 else ""


def fn_after_last(text: Any, marker: Any) -> str:
    text_s = _to_text(text)
    marker_s = _to_text(marker)
    if not marker_s:
        return ""
    idx = text_s.rfind(marker_s)
    return text_s[idx + len(marker_s):] if idx >= 0 else ""


def fn_before(text: Any, marker: Any) -> str:
    text_s = _to_text(text)
    marker_s = _to_text(marker)
    if not marker_s:
        return ""
    idx = text_s.find(marker_s)
    return text_s[:idx] if idx >= 0 else text_s


def fn_before_last(text: Any, marker: Any) -> str:
    text_s = _to_text(text)
    marker_s = _to_text(marker)
    if not marker_s:
        return ""
    idx = text_s.rfind(marker_s)
    return text_s[:idx] if idx >= 0 else text_s


def fn_between(text: Any, start: Any, end: Any) -> str:
    text_s = _to_text(text)
    start_s = _to_text(start)
    end_s = _to_text(end)
    if not start_s or not end_s:
        return ""
    i = text_s.find(start_s)
    if i < 0:
        return ""
    j = text_s.find(end_s, i + len(start_s))
    if j < 0:
        return ""
    return text_s[i + len(start_s):j]


def fn_concat(*args: Any) -> str:
    return "".join(_to_text(x) for x in args)


def fn_upper(value: Any) -> str:
    return _to_text(value).upper()


def fn_lower(value: Any) -> str:
    return _to_text(value).lower()


def fn_trim(value: Any) -> str:
    return _to_text(value).strip()


def fn_replace(text: Any, old: Any, new: Any) -> str:
    return _to_text(text).replace(_to_text(old), _to_text(new))


def fn_year(value: Any) -> int | None:
    d = _parse_date(value)
    return d.year if d else None


def fn_month(value: Any) -> int | None:
    d = _parse_date(value)
    return d.month if d else None


def fn_day(value: Any) -> int | None:
    d = _parse_date(value)
    return d.day if d else None


def fn_to_number(value: Any) -> float | None:
    return _to_number(value)


def fn_to_text(value: Any) -> str:
    return _to_text(value)


def fn_round(value: Any, digits: Any = 0) -> float | None:
    number = _to_number(value)
    if number is None:
        return None
    digits_n = _to_number(digits)
    return round(number, int(digits_n or 0))


def fn_minutes_diff(end_value: Any, start_value: Any) -> float | None:
    end_t = _parse_time(end_value)
    start_t = _parse_time(start_value)
    if end_t is None or start_t is None:
        return None
    end_minutes = (end_t.hour * 60) + end_t.minute + (end_t.second / 60)
    start_minutes = (start_t.hour * 60) + start_t.minute + (start_t.second / 60)
    diff = end_minutes - start_minutes
    if diff < 0:
        diff += 24 * 60
    return diff


def fn_hours_diff(end_value: Any, start_value: Any) -> float | None:
    diff = fn_minutes_diff(end_value, start_value)
    if diff is None:
        return None
    return diff / 60


def _compare_values(left: Any, right: Any) -> tuple[Any, Any] | None:
    left_num = _to_number(left)
    right_num = _to_number(right)
    if left_num is not None and right_num is not None:
        return left_num, right_num
    if isinstance(left, bool) and isinstance(right, bool):
        return left, right
    if left is None or right is None:
        return None
    return _to_text(left), _to_text(right)


def fn_gte(left: Any, right: Any) -> bool:
    values = _compare_values(left, right)
    return False if values is None else values[0] >= values[1]


def fn_gt(left: Any, right: Any) -> bool:
    values = _compare_values(left, right)
    return False if values is None else values[0] > values[1]


def fn_lte(left: Any, right: Any) -> bool:
    values = _compare_values(left, right)
    return False if values is None else values[0] <= values[1]


def fn_lt(left: Any, right: Any) -> bool:
    values = _compare_values(left, right)
    return False if values is None else values[0] < values[1]


def fn_eq(left: Any, right: Any) -> bool:
    values = _compare_values(left, right)
    if values is None:
        return left is None and right is None
    return values[0] == values[1]


def fn_neq(left: Any, right: Any) -> bool:
    return not fn_eq(left, right)


def fn_if_else(condition: Any, true_value: Any, false_value: Any) -> Any:
    return true_value if bool(condition) else false_value


def fn_token_after(text: Any, marker: Any, case_sensitive: Any = False) -> str:
    """
    Return the first token that appears after `marker`.

    Examples:
    - token_after("... CRO: 12345 ABI: 03069", "CRO:") -> "12345"
    - token_after("Pagamento #IBAN IT60X0542811101000000123456", "#IBAN") -> "IT60X0542811101000000123456"
    """
    text_s = _to_text(text)
    marker_s = _to_text(marker)
    if not marker_s:
        return ""

    is_case_sensitive = False
    if isinstance(case_sensitive, bool):
        is_case_sensitive = case_sensitive
    else:
        case_sensitive_s = _to_text(case_sensitive).strip().lower()
        is_case_sensitive = case_sensitive_s in {"1", "true", "yes", "y", "si", "sì"}

    if is_case_sensitive:
        idx = text_s.find(marker_s)
    else:
        idx = text_s.lower().find(marker_s.lower())
    if idx < 0:
        return ""

    tail = text_s[idx + len(marker_s):]
    tail = tail.lstrip()
    if not tail:
        return ""

    # stop at first whitespace or common separator
    separators = set(" \t\r\n,;|()[]{}")
    out: list[str] = []
    for ch in tail:
        if ch in separators:
            break
        out.append(ch)
    return "".join(out).strip()


SAFE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "after": fn_after,
    "after_last": fn_after_last,
    "before": fn_before,
    "before_last": fn_before_last,
    "between": fn_between,
    "concat": fn_concat,
    "upper": fn_upper,
    "lower": fn_lower,
    "trim": fn_trim,
    "replace": fn_replace,
    "year": fn_year,
    "month": fn_month,
    "day": fn_day,
    "to_number": fn_to_number,
    "to_text": fn_to_text,
    "round": fn_round,
    "minutes_diff": fn_minutes_diff,
    "hours_diff": fn_hours_diff,
    "gte": fn_gte,
    "gt": fn_gt,
    "lte": fn_lte,
    "lt": fn_lt,
    "eq": fn_eq,
    "neq": fn_neq,
    "if_else": fn_if_else,
    "token_after": fn_token_after,
}


def _split_binary(expr: str, operators: tuple[str, ...]) -> tuple[str, str, str] | None:
    depth_round = 0
    depth_square = 0
    quote: str | None = None
    escape = False

    idx = 0
    while idx < len(expr):
        ch = expr[idx]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            idx += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            idx += 1
            continue
        if ch == "(":
            depth_round += 1
            idx += 1
            continue
        if ch == ")":
            depth_round -= 1
            idx += 1
            continue
        if ch == "[":
            depth_square += 1
            idx += 1
            continue
        if ch == "]":
            depth_square -= 1
            idx += 1
            continue

        if depth_round == 0 and depth_square == 0:
            for op in operators:
                if expr.startswith(op, idx):
                    left = expr[:idx].strip()
                    right = expr[idx + len(op):].strip()
                    if left and right:
                        return left, op, right
        idx += 1
    return None


def _split_args(arg_text: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth_round = 0
    depth_square = 0
    quote: str | None = None
    escape = False

    for ch in arg_text:
        if quote:
            current.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue

        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            continue
        if ch == "(":
            depth_round += 1
            current.append(ch)
            continue
        if ch == ")":
            depth_round -= 1
            current.append(ch)
            continue
        if ch == "[":
            depth_square += 1
            current.append(ch)
            continue
        if ch == "]":
            depth_square -= 1
            current.append(ch)
            continue
        if ch == "," and depth_round == 0 and depth_square == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    elif arg_text.strip():
        args.append("")
    return args


def _strip_outer_parens(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        ok = True
        quote: str | None = None
        escape = False
        for idx, ch in enumerate(expr):
            if quote:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ("'", '"'):
                quote = ch
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and idx != len(expr) - 1:
                    ok = False
                    break
        if ok and depth == 0:
            expr = expr[1:-1].strip()
        else:
            break
    return expr


def _parse_literal(expr: str) -> Any:
    expr = expr.strip()
    if len(expr) >= 2 and expr[0] == expr[-1] and expr[0] in ("'", '"'):
        inner = expr[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")
    low = expr.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    if NUMBER_RE.match(expr):
        if "," in expr and "." not in expr:
            expr = expr.replace(",", ".")
        number = float(expr)
        return int(number) if number.is_integer() else number
    return None


def _parse_func(expr: str) -> tuple[str, list[str]] | None:
    expr = expr.strip()
    if not FUNC_CALL_RE.match(expr) or not expr.endswith(")"):
        return None

    name, rest = expr.split("(", 1)
    name = name.strip()
    if not IDENT_RE.match(name):
        return None

    inner = rest[:-1]  # drop last ')'
    depth = 0
    quote: str | None = None
    escape = False
    for ch in inner:
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None

    if depth != 0:
        return None

    args = _split_args(inner) if inner.strip() else []
    return name, args


def evaluate_formula(formula: str, row: dict[str, Any]) -> Any:
    expr = _strip_outer_parens((formula or "").strip())
    if not expr:
        raise FormulaError("Formula vuota.")

    field_match = FIELD_REF_RE.fullmatch(expr)
    if field_match:
        field_name = field_match.group(1).strip()
        return row.get(field_name)

    literal = _parse_literal(expr)
    if literal is not None or expr.lower() == "null":
        return literal

    binary = _split_binary(expr, (">=", "<=", "==", "!=", ">", "<"))
    if binary:
        left_expr, op, right_expr = binary
        left = evaluate_formula(left_expr, row)
        right = evaluate_formula(right_expr, row)
        if op == ">=":
            return fn_gte(left, right)
        if op == "<=":
            return fn_lte(left, right)
        if op == "==":
            return fn_eq(left, right)
        if op == "!=":
            return fn_neq(left, right)
        if op == ">":
            return fn_gt(left, right)
        return fn_lt(left, right)

    func = _parse_func(expr)
    if func:
        name, arg_exprs = func
        fn = SAFE_FUNCTIONS.get(name.lower())
        if fn is None:
            raise FormulaError(f"Funzione non consentita: {name}")
        args = [evaluate_formula(arg_expr, row) for arg_expr in arg_exprs]
        try:
            return fn(*args)
        except TypeError as exc:
            raise FormulaError(f"Argomenti non validi per {name}: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise FormulaError(f"Errore in {name}: {exc}") from exc

    raise FormulaError(f"Sintassi formula non riconosciuta: {expr}")


def cast_output(value: Any, field_type: str) -> Any:
    kind = (field_type or "string").strip().lower()
    if kind == "number":
        return _to_number(value)
    if kind == "date":
        d = _parse_date(value)
        return d.isoformat() if d else None
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = _to_text(value).strip().lower()
        if text in {"1", "true", "sì", "si", "yes", "y"}:
            return True
        if text in {"0", "false", "no", "n", ""}:
            return False
        return bool(value)
    return _to_text(value)


def validate_formula(formula: str) -> tuple[bool, str]:
    formula = (formula or "").strip()
    if not formula:
        return False, "Formula vuota."
    try:
        evaluate_formula(formula, {})
        return True, ""
    except FormulaError as exc:
        # Allow field references not present in empty validation row.
        message = str(exc)
        if "Sintassi formula non riconosciuta" in message or "Funzione non consentita" in message:
            return False, message
        return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


def apply_calculated_fields(
    rows: list[dict[str, Any]],
    definitions: list[CalculatedFieldDefinition],
) -> list[dict[str, Any]]:
    """
    Apply row-level calculated fields.

    Definitions are evaluated sequentially, so later calculated fields may
    reference earlier calculated fields in the same row.
    """
    prepared = [
        d for d in definitions
        if d and d.enabled and str(d.name or "").strip() and str(d.formula or "").strip()
    ]
    if not prepared:
        return [dict(row) for row in rows]

    output: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        for definition in prepared:
            try:
                value = evaluate_formula(definition.formula, new_row)
                new_row[definition.name] = cast_output(value, definition.field_type)
            except FormulaError:
                new_row[definition.name] = None
        output.append(new_row)
    return output



def get_calculated_field_names(definitions: list[CalculatedFieldDefinition]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for definition in definitions:
        name = str(getattr(definition, "name", "") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def augment_field_list(base_fields: list[str], definitions: list[CalculatedFieldDefinition]) -> list[str]:
    out = list(base_fields or [])
    seen = set(out)
    for name in get_calculated_field_names(definitions):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def build_calculated_definitions(items: list[dict[str, Any]] | None) -> list[CalculatedFieldDefinition]:
    definitions: list[CalculatedFieldDefinition] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        definitions.append(CalculatedFieldDefinition(
            name=str(item.get("name", "") or "").strip(),
            formula=str(item.get("formula", "") or "").strip(),
            field_type=str(item.get("type", "string") or "string").strip(),
            enabled=bool(item.get("enabled", True)),
        ))
    return definitions


def prepare_rows_and_fields(
    rows: list[dict[str, Any]],
    base_fields: list[str],
    definitions: list[CalculatedFieldDefinition],
) -> tuple[list[dict[str, Any]], list[str]]:
    new_rows = apply_calculated_fields(rows, definitions)
    new_fields = augment_field_list(base_fields, definitions)
    return new_rows, new_fields

def register_plugin() -> dict[str, Any]:
    return {
        "id": "calculated_fields",
        "name": "Calculated Fields",
        "phase": "phase_a",
        "row_level_only": True,
        "supported_functions": sorted(SAFE_FUNCTIONS.keys()),
    }
