"""Pure, bounded execution of normalized Typed plans.

Distinct keeps the first row. Sort is stable and multi-key; groups sort by
ascending keys with null first. Text uses case-sensitive UTF-8 ordinal order.
All six catalog join kinds preserve NestedJoin's nested-table representation;
left rows and right matches keep input order, unmatched right rows follow.
Fan-out records the projected expanded row count, rather than incorrectly
counting one nested-table cell as one match. Empty average/min/max/sum are null.
Decimal arithmetic uses a fixed 100-digit context, independent of the caller.
This module performs no file/network IO and never reads a clock.

Tables bind by sourceId, or uniquely by a source's objectName/runtimeAlias.
Each has rows and either a header or columns; sampleRows is never substituted
for complete data. The normalized plan owns column lineage IDs and types.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import (
    Context, Decimal, DecimalException, DivisionByZero, InvalidOperation,
    Overflow, ROUND_HALF_EVEN, localcontext,
)
import re

from ...errors import InputError
from ..typed.model import MAX_STEPS, OPERATION_ARITY
from ..typed.validation import _normalize_operation
from .expressions import evaluate, identity, logical, number, numeric, ordered

MAX_ROWS = 100_000
MAX_COLUMNS = 256


@dataclass
class _Table:
    columns: list
    rows: list


def _invalid(path="plan", detail="Invalid normalized Typed plan"):
    return InputError("AF_EXECUTOR_INVALID", path, detail)


def _limit(rows, columns):
    if rows > MAX_ROWS or columns > MAX_COLUMNS:
        raise InputError("AF_EXECUTOR_LIMIT", "tables", "Executor row or column limit exceeded")


def _schema(columns):
    if not isinstance(columns, list) or not columns:
        raise _invalid("columns")
    _limit(0, len(columns))
    if any(not isinstance(c, dict) or not isinstance(c.get("columnId"), str)
           or not isinstance(c.get("name"), str) or not isinstance(c.get("inferredType"), str) for c in columns):
        raise _invalid("columns")
    if len({c["columnId"] for c in columns}) != len(columns) or len({c["name"] for c in columns}) != len(columns):
        raise _invalid("columns", "Duplicate columns")


def _convert(value, target, culture, warnings, path):
    if value is None or target == "any":
        return value
    if culture not in {None, "", "en-US", "en-GB", "vi-VN", "de-DE", "fr-FR"}:
        raise _invalid(path, "Unsupported explicit conversion culture")
    if target == "text":
        if isinstance(value, bool):
            return "true" if value else "false"
        return value.isoformat() if isinstance(value, (date, datetime, time)) else str(value)
    if target in {"number", "integer"}:
        if isinstance(value, bool):
            result = Decimal(int(value))
        else:
            if isinstance(value, str) and culture:
                if culture in {"vi-VN", "de-DE"}:
                    value = value.replace(".", "").replace(",", ".")
                elif culture == "fr-FR":
                    value = value.replace(" ", "").replace("\u202f", "").replace("\u00a0", "").replace(",", ".")
                else:
                    value = value.replace(",", "")
            result = number(value)
        if target == "integer":
            result = result.to_integral_value(rounding=ROUND_HALF_EVEN)
            if not -(2**63) <= result < 2**63:
                raise ValueError("Integer outside Int64 range")
        return result
    if target == "logical":
        if isinstance(value, bool):
            return value
        if isinstance(value, (Decimal, int, float)):
            return number(value) != 0
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError("Invalid logical conversion")
    if target == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            if isinstance(value, str):
                try:
                    return date.fromisoformat(value)
                except ValueError:
                    if culture:
                        return datetime.strptime(value, "%m/%d/%Y" if culture == "en-US" else "%d/%m/%Y").date()
            raise ValueError("Invalid date")
        except ValueError:
            warnings.append({"code": "AF_EXECUTOR_DATE_NULL", "path": path})
            return None
    if target in {"datetime", "datetimezone"}:
        result = value if isinstance(value, datetime) else datetime.combine(value, time()) if isinstance(value, date) else datetime.fromisoformat(value)
        if target == "datetimezone" and result.utcoffset() is None:
            raise ValueError("Datetimezone requires an explicit offset")
        return result.replace(tzinfo=None) if target == "datetime" else result
    if target == "time":
        return value.time() if isinstance(value, datetime) else value if isinstance(value, time) else time.fromisoformat(value)
    if target == "duration":
        if isinstance(value, timedelta):
            return value
        if isinstance(value, (Decimal, int, float)):
            return timedelta(microseconds=int(number(value) * Decimal(86_400_000_000)))
        match = re.fullmatch(r"(-?)(\d+)\.(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", value)
        if not match or int(match[3]) > 23 or int(match[4]) > 59 or number(match[5]) >= 60:
            raise ValueError("Invalid duration")
        seconds = Decimal(match[2]) * 86400 + Decimal(match[3]) * 3600 + Decimal(match[4]) * 60 + number(match[5])
        return timedelta(microseconds=int(seconds * 1_000_000)) * (-1 if match[1] else 1)
    raise ValueError("Unsupported type")


def _scalar(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (Decimal, int, float)):
        return str(number(value))
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        micros = (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
        sign = "-" if micros < 0 else ""
        seconds = Decimal(abs(micros)) / 1_000_000
        days, seconds = divmod(seconds, Decimal(86400))
        hours, seconds = divmod(seconds, Decimal(3600))
        minutes, seconds = divmod(seconds, Decimal(60))
        return f"{sign}{int(days)}.{int(hours):02}:{int(minutes):02}:{seconds:02}"
    raise _invalid("rows", "Final output must contain scalar cells")


def _load_source(source, tables, warnings):
    candidates = [t for t in tables if t.get("sourceId") == source["sourceId"]]
    if not candidates:
        alias = source.get("objectName", source.get("runtimeAlias"))
        candidates = [t for t in tables if alias and alias in (t.get("name"), t.get("tableName"), t.get("objectName"), t.get("table"))]
    if len(candidates) != 1:
        raise _invalid("tables", "Source must bind exactly one table")
    table = candidates[0]
    rows = table.get("rows")
    if not isinstance(rows, list) or table.get("sampleOnly") is True or table.get("totalRows", len(rows)) != len(rows):
        raise _invalid("tables", "Executor requires complete table rows")
    columns = deepcopy(source["columns"])
    _limit(len(rows), len(columns))
    header = table.get("header", table.get("headers"))
    if header is None and isinstance(table.get("columns"), list):
        header = [c["name"] if isinstance(c, dict) else c for c in table["columns"]]
    if header is None:
        header = [c["name"] for c in columns]
    if isinstance(header, list):
        _limit(len(rows), len(header))
    if not isinstance(header, list) or len(set(header)) != len(header) or set(header) != {c["name"] for c in columns}:
        raise _invalid("tables", "Source header does not match its catalog")
    positions = [header.index(c["name"]) for c in columns]
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(header):
            raise _invalid("tables", "Source row width does not match its header")
        cells = {}
        for column, position in zip(columns, positions):
            value = row[position]
            if isinstance(value, (dict, list, tuple)):
                raise _invalid("tables", "Source cells must be scalar")
            if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                value = number(value)
            cells[column["columnId"]] = _convert(value, column["inferredType"], None, warnings, "source." + column["columnId"])
        result.append(cells)
    return _Table(columns, result)


def _aggregate(items, spec):
    function = spec["function"]
    if function == "rowCount":
        return Decimal(len(items))
    values = [r[spec["columnId"]] for r in items if r[spec["columnId"]] is not None]
    if function == "countNonNull":
        return Decimal(len(values))
    if function == "countDistinct":
        return Decimal(len({identity(v) for v in values}))
    if not values:
        return None
    if function in {"min", "max"}:
        return (min if function == "min" else max)(values, key=ordered)
    total = sum((numeric(v) for v in values), Decimal(0))
    return total / Decimal(len(values)) if function == "average" else total


def _merge(left, right, params, columns, step_id, joins):
    left_ids = [p["leftColumnId"] for p in params["keyPairs"]]
    right_ids = [p["rightColumnId"] for p in params["keyPairs"]]
    key = lambda row, ids: tuple(identity(row[c]) for c in ids)
    index = {}
    for i, row in enumerate(right.rows):
        index.setdefault(key(row, right_ids), []).append(i)
    kind, nested = params["joinKind"], params["nestedColumnId"]
    result, matched, projected = [], set(), 0
    for row in left.rows:
        matches = index.get(key(row, left_ids), [])
        matched.update(matches)
        if kind == "rightAnti" or (kind == "leftAnti" and matches):
            continue
        if not matches and kind in {"inner", "rightOuter"}:
            continue
        nested_rows = [] if kind == "leftAnti" else [right.rows[i] for i in matches]
        projected += max(1, len(nested_rows))
        _limit(projected, len(columns))
        result.append({**row, nested: _Table(right.columns, nested_rows)})
    if kind in {"rightOuter", "fullOuter", "rightAnti"}:
        for i, row in enumerate(right.rows):
            if i not in matched:
                result.append({**{c["columnId"]: None for c in left.columns}, nested: _Table(right.columns, [row])})
                projected += 1
                _limit(projected, len(columns))
    joins.append({"stepId": step_id, "joinKind": kind, "rowsBefore": len(left.rows),
                  "nestedRowsAfter": len(result), "rowsAfter": projected,
                  "ratio": str(Decimal(projected) / len(left.rows)) if left.rows else None})
    return result


def _run(operation, params, inputs, columns, step_id, warnings, joins):
    source = inputs[0]
    rows = source.rows
    if operation == "table.filterRows":
        result = []
        for row in rows:
            try:
                keep = logical(evaluate(params["predicate"], row)) is True
            except (ValueError, TypeError, DecimalException):
                if params["onEvaluationError"] == "block":
                    raise
                keep = params["onEvaluationError"] == "keepRow"
            if keep:
                result.append(row)
        return result
    if operation in {"table.selectColumns", "table.removeColumns", "table.renameColumns"}:
        return [{c["columnId"]: r[c["columnId"]] for c in columns} for r in rows]
    if operation == "table.changeTypes":
        result = [dict(row) for row in rows]
        for conversion in params["conversions"]:
            for row in result:
                cid = conversion["columnId"]
                row[cid] = _convert(row[cid], conversion["targetType"], conversion.get("culture"), warnings, step_id + "." + cid)
        return result
    if operation == "table.addColumn":
        result = []
        for row in rows:
            try:
                value = evaluate(params["expression"], row)
            except (ValueError, TypeError, DecimalException):
                if params["onEvaluationError"] == "block":
                    raise
                value = None
            result.append({**row, params["newColumnId"]: value})
        return result
    if operation == "table.sortRows":
        result = list(rows)
        for item in reversed(params["keys"]):
            result.sort(key=lambda row: ordered(row[item["columnId"]]), reverse=item["direction"] == "descending")
        return result
    if operation == "table.distinctRows":
        seen, result = set(), []
        for row in rows:
            key = tuple(identity(row[c]) for c in params["columnIds"])
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result
    if operation in {"table.groupRows", "table.aggregateRows"}:
        groups = {}
        keys = params["keyColumnIds"]
        for row in rows:
            key = tuple(identity(row[c]) for c in keys)
            groups.setdefault(key, []).append(row)
        if not rows and not keys:
            groups[()] = []
        ordered_groups = sorted(groups.values(), key=lambda group: tuple(ordered(group[0][c]) for c in keys))
        result = []
        for group in ordered_groups:
            values = [group[0][c] for c in keys] + [_aggregate(group, a) for a in params["aggregations"]]
            result.append({c["columnId"]: value for c, value in zip(columns, values)})
        return result
    if operation == "table.appendTables":
        _limit(sum(len(t.rows) for t in inputs), len(columns))
        result = []
        for table in inputs:
            by_name = {c["name"]: c["columnId"] for c in table.columns}
            for row in table.rows:
                result.append({c["columnId"]: row.get(by_name.get(c["name"])) for c in columns})
        return result
    if operation == "table.mergeTables":
        return _merge(source, inputs[1], params, columns, step_id, joins)
    if operation == "table.expandTableColumn":
        result = []
        nested_id = params["nestedColumnId"]
        for row in rows:
            nested = row[nested_id]
            if not isinstance(nested, _Table):
                raise ValueError("Expand requires a nested table")
            _limit(len(result) + max(1, len(nested.rows)), len(columns))
            for child in nested.rows or [None]:
                output = {k: v for k, v in row.items() if k != nested_id}
                for col in params["columns"]:
                    output[col["newColumnId"]] = None if child is None else child[col["sourceColumnId"]]
                result.append(output)
        return result
    raise ValueError("Unsupported operation")


def execute_plan(plan: dict, tables: list[dict]) -> dict:
    """Execute a normalized Typed plan without mutating either input.

    Return scalar JSON-ready columns/rows/rowCount and fanOut (or None).
    Warnings contain codes/lineage paths only, never source cell values.
    The caller measures elapsed time; this function is deterministic.
    """
    try:
        with localcontext(Context(prec=100, rounding=ROUND_HALF_EVEN,
                                  Emin=-999999, Emax=999999, capitals=1, clamp=0,
                                  flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])):
            return _execute(plan, tables)
    except InputError as exc:
        if exc.code in {"AF_EXECUTOR_INVALID", "AF_EXECUTOR_LIMIT"}:
            raise
        raise _invalid(exc.path, "Plan failed Typed validation") from None
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, DecimalException, OverflowError, RecursionError):
        raise _invalid() from None


def _execute(plan, tables):
    if not isinstance(plan, dict) or not isinstance(tables, list) or any(not isinstance(t, dict) for t in tables):
        raise _invalid()
    steps, sources = plan.get("steps"), plan.get("sources")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS or not isinstance(sources, list):
        raise _invalid()
    source_map = {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("sourceId"), str) or source["sourceId"] in source_map:
            raise _invalid("sources")
        _schema(source["columns"])
        source_map[source["sourceId"]] = source
    results, warnings, joins = {}, [], []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("stepId"), str) or step["stepId"] in results:
            raise _invalid("steps")
        sid = step["stepId"]
        operation = step["operation"]["type"]
        if operation not in OPERATION_ARITY or not isinstance(step.get("inputs"), list):
            raise _invalid("steps")
        inputs = []
        for reference in step["inputs"]:
            if reference.get("kind") != "step" or reference.get("ref") not in results:
                raise _invalid("steps.inputs")
            inputs.append(results[reference["ref"]])
        minimum, maximum = OPERATION_ARITY[operation]
        if not minimum <= len(inputs) <= maximum:
            raise _invalid("steps.inputs")
        params, columns, _ = _normalize_operation(sid, operation, step["operation"]["parameters"], [t.columns for t in inputs], source_map, sid)
        _schema(columns)
        supplied = step["outputContract"]["columns"]
        if supplied != columns:
            raise _invalid("steps.outputContract", "Output contract differs from normalized operation")
        if operation.startswith("source."):
            result = _load_source(source_map[params["sourceId"]], tables, warnings)
        else:
            result = _Table(columns, _run(operation, params, inputs, columns, sid, warnings, joins))
        _limit(len(result.rows), len(result.columns))
        results[sid] = result
    final = results[plan["finalOutputStepId"]]
    if any(c["inferredType"] == "table" for c in final.columns):
        raise _invalid("finalOutputStepId", "Final nested tables must be expanded")
    fan_out = None
    if joins:
        fan_out = {"rowsBefore": joins[-1]["rowsBefore"], "rowsAfter": joins[-1]["rowsAfter"],
                   "ratio": joins[-1]["ratio"], "joins": joins}
    result = {"columns": [{"name": c["name"], "type": c["inferredType"]} for c in final.columns],
              "rows": [[_scalar(row[c["columnId"]]) for c in final.columns] for row in final.rows],
              "rowCount": len(final.rows), "fanOut": fan_out}
    if warnings:
        result["warnings"] = list({(w["code"], w["path"]): w for w in warnings}.values())
    return result
