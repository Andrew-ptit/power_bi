"""Plan-declared controls, independent raw-source totals and A/B identities.

No IO or clock. Shared Typed scalar conversion/expression semantics are used to
replay a source's filters; source summation never executes the result plan and
never uses joined/aggregated result rows as its comparison basis. Ambiguous
lineage remains explicitly unverified. All arithmetic has a fixed context.
"""

from copy import deepcopy
from decimal import (Context, Decimal, DecimalException, DivisionByZero,
                     InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext)
import re

from pbip_assistant.errors import InputError
from pbip_assistant.powerquery.typed_local.executor import _convert
from pbip_assistant.powerquery.typed_local.expressions import evaluate, logical
from .assistant_ingest import canonical_hash


_CONTEXT = Context(prec=100, rounding=ROUND_HALF_EVEN, Emin=-999999,
                   Emax=999999, capitals=1, clamp=0, flags=[],
                   traps=[InvalidOperation, DivisionByZero, Overflow])
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
ENGINE = {"executor": "typed_local", "version": "1.0", "parityChecked": "none",
          "knownDifferences": ["text-compare-case-sensitive", "decimal-money",
              "stable-distinct-first-row", "stable-sort", "join-left-input-order",
              "invalid-date-to-null"]}
_BASIS = ("planHash", "snapshotHash", "previewHash", "resultDigest", "sourceFingerprint",
          "rowsIn", "rowsOut", "colsIn", "colsOut", "controlTotal", "maxFanOut",
          "controlTotalApplicable", "controlTotalReason", "controlTotalSource",
          "controlTotalResult", "controlTotalTolerance", "controlTotalPassed",
          "fanOutPassed", "checks", "blockers", "warnings", "hardChecksPassed",
          "acknowledgementRequired", "selectable", "passed", "abIdentityPassed", "abDeltaHash", "engine")


class _Unavailable(Exception):
    pass


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError("Expected a finite decimal")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Expected a finite decimal")
    return result


def _number(value):
    return str(value) if value else "0"


def result_digest(result):
    """Hash the entire JSON-ready result matrix, never a truncated preview."""
    return canonical_hash({"columns": result["columns"], "rows": result["rows"]})


def build_preview(snapshot_hash, branch, result):
    preview = {"schemaVersion": "1.0", "snapshotHash": snapshot_hash,
               "planHash": branch["planHash"], "resultDigest": result_digest(result),
               "rowsOut": result.get("rowCount"), "colsOut": len(result.get("columns", [])),
               "engine": deepcopy(ENGINE)}
    preview["previewHash"] = canonical_hash(preview)
    return preview


def _source(source, tables):
    matches = [table for table in tables if table.get("sourceId") == source["sourceId"]]
    if not matches:
        alias = source.get("objectName", source.get("runtimeAlias"))
        matches = [table for table in tables if alias and table.get("name") == alias]
    if len(matches) != 1:
        raise _Unavailable("Không xác định được đúng một bảng nguồn cho tổng kiểm soát.")
    raw = matches[0]
    if raw.get("mode") != "compute" or raw.get("totalRows", len(raw["rows"])) != len(raw["rows"]):
        raise _Unavailable("Tổng kiểm soát cần dữ liệu nguồn đầy đủ.")
    return raw


def _graph(plan):
    by_id = {step["stepId"]: step for step in plan["steps"]}
    memo = {}
    def sources(step_id):
        if step_id not in memo:
            step = by_id[step_id]
            if step["operation"]["type"].startswith("source."):
                memo[step_id] = {step_id}
            else:
                memo[step_id] = set().union(*(sources(item["ref"]) for item in step["inputs"]))
        return memo[step_id]
    sources(plan["finalOutputStepId"])
    return by_id, sources


def source_dimensions(plan, tables):
    by_id, ancestors = _graph(plan)
    source_map = {source["sourceId"]: source for source in plan["sources"]}
    used = {}
    for reference in ancestors(plan["finalOutputStepId"]):
        identifier = by_id[reference]["operation"]["parameters"]["sourceId"]
        used[identifier] = _source(source_map[identifier], tables)
    return sum(len(table["rows"]) for table in used.values()), sum(len(table["header"]) for table in used.values())


def _independent_source_total(plan, tables, control):
    by_id, ancestors = _graph(plan)
    source_map = {source["sourceId"]: source for source in plan["sources"]}
    final = plan["finalOutputStepId"]
    candidates = []
    for reference in sorted(ancestors(final)):
        source = source_map[by_id[reference]["operation"]["parameters"]["sourceId"]]
        for column in source["columns"]:
            if column["name"] == control["sourceColumn"]:
                candidates.append((reference, source, column))
    if len(candidates) != 1:
        raise _Unavailable("Cột tổng kiểm soát không xác định được một nguồn và một phạm vi dòng duy nhất.")
    source_ref, source, basis = candidates[0]
    path, current = [], final
    while current != source_ref:
        step = by_id[current]
        path.append(step)
        parents = [item["ref"] for item in step["inputs"] if source_ref in ancestors(item["ref"])]
        if len(parents) != 1:
            raise _Unavailable("Nguồn kiểm soát đi qua nhiều nhánh; không suy đoán phạm vi dòng.")
        current = parents[0]
    raw = _source(source, tables)
    positions = [raw["header"].index(column["name"]) for column in source["columns"]]
    rows = [{column["columnId"]: _convert(row[position], column["inferredType"], None, [], "control.source")
             for column, position in zip(source["columns"], positions)} for row in raw["rows"]]
    complex_scope = False
    for step in reversed(path):
        kind, parameters = step["operation"]["type"], step["operation"]["parameters"]
        if kind in ("table.mergeTables", "table.appendTables", "table.expandTableColumn", "table.groupRows", "table.aggregateRows"):
            complex_scope = True
        elif kind == "table.filterRows" and control["afterFilters"]:
            if complex_scope:
                raise _Unavailable("Bộ lọc sau nối/ghép/nhóm cần basis riêng; chưa có tổng nguồn độc lập đáng tin cậy.")
            filtered = []
            for row in rows:
                try:
                    keep = logical(evaluate(parameters["predicate"], row)) is True
                except (ValueError, TypeError, DecimalException):
                    policy = parameters["onEvaluationError"]
                    if policy == "block":
                        raise _Unavailable("Không đánh giá được bộ lọc nguồn để đối soát độc lập.") from None
                    keep = policy == "keepRow"
                if keep:
                    filtered.append(row)
            rows = filtered
        elif kind == "table.distinctRows" and control["afterFilters"]:
            raise _Unavailable("Kế hoạch khử trùng cần basis tổng nguồn riêng; không suy đoán tổng sau khử trùng.")
        elif kind == "table.changeTypes":
            for conversion in parameters["conversions"]:
                for row in rows:
                    column = conversion["columnId"]
                    if column in row:
                        row[column] = _convert(row[column], conversion["targetType"], conversion.get("culture"), [], "control.conversion")
        elif kind == "table.addColumn" and not complex_scope:
            for row in rows:
                try:
                    row[parameters["newColumnId"]] = evaluate(parameters["expression"], row)
                except (ValueError, TypeError, DecimalException):
                    if parameters["onEvaluationError"] == "block":
                        raise _Unavailable("Không đánh giá được cột dùng cho bộ lọc nguồn.") from None
                    row[parameters["newColumnId"]] = None
        # Select/remove/rename preserve IDs; retain the private basis column
        # even after a projection so source totals never use result values.
    return sum((_amount(row[basis["columnId"]]) for row in rows if row[basis["columnId"]] is not None), Decimal(0))


def _shape(preview, branch, result):
    try:
        columns, rows = result["columns"], result["rows"]
        if not isinstance(columns, list) or not columns or not isinstance(rows, list):
            return False
        names = [column["name"] for column in columns]
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
            return False
        final = next(step for step in branch["plan"]["steps"] if step["stepId"] == branch["plan"]["finalOutputStepId"])
        if columns != [{"name": column["name"], "type": column["inferredType"]} for column in final["outputContract"]["columns"]]:
            return False
        if type(result.get("rowCount")) is not int or result["rowCount"] != len(rows):
            return False
        if preview["rowsOut"] != len(rows) or preview["colsOut"] != len(columns):
            return False
        if preview["planHash"] != branch["planHash"] or preview["resultDigest"] != result_digest(result):
            return False
        if preview.get("previewHash") != canonical_hash({key: value for key, value in preview.items() if key != "previewHash"}):
            return False
        if not isinstance(preview.get("snapshotHash"), str) or not _HASH.fullmatch(preview["snapshotHash"]):
            return False
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns) or not row:
                return False
            for column, value in zip(columns, row):
                if value is not None and not isinstance(value, (str, int, bool)):
                    return False
                if column["type"] in ("number", "integer") and value is not None:
                    _amount(value)
        return True
    except (KeyError, TypeError, ValueError, StopIteration, DecimalException):
        return False


def _fanout(plan, result, allowed):
    expected = {step["stepId"] for step in plan["steps"] if step["operation"]["type"] == "table.mergeTables"}
    fanout = result.get("fanOut")
    joins = fanout.get("joins") if isinstance(fanout, dict) else []
    if not expected:
        return not joins, "Kế hoạch không có nối bảng."
    if not isinstance(joins, list) or len(joins) != len(expected):
        return False, "Thiếu số đo fan-out của một hoặc nhiều phép nối."
    seen = set()
    for join in joins:
        if not isinstance(join, dict) or not isinstance(join.get("stepId"), str):
            return False, "Số đo fan-out không hợp lệ."
        if join["stepId"] not in expected or join["stepId"] in seen:
            return False, "Số đo fan-out không khớp từng phép nối."
        seen.add(join["stepId"])
        before, after = join.get("rowsBefore"), join.get("rowsAfter")
        if type(before) is not int or type(after) is not int or before < 0 or after < 0:
            return False, "Số dòng fan-out không hợp lệ."
        if Decimal(after) > Decimal(before) * allowed:
            return False, "Phép nối " + join["stepId"] + " vượt hệ số fan-out đã khai."
    return True, "Mọi phép nối đều nằm trong hệ số fan-out đã khai."


def _rehash(result):
    result["hashBasis"] = list(_BASIS)
    result["reconcileHash"] = canonical_hash({key: result[key] for key in _BASIS})
    return result


def reconcile_v2(preview_of_branch, plan, source_tables, result):
    """Reconcile a branch wrapper (normalized ``plan`` + declared policies)."""
    with localcontext(_CONTEXT):
        branch, preview = plan, preview_of_branch
        normalized = branch["plan"]
        control = branch.get("controlTotal")
        shape_passed = _shape(preview, branch, result)
        rows_in, cols_in = source_dimensions(normalized, source_tables)
        applicable, reason, source_total, result_total = False, None, None, None
        tolerance = _amount(control.get("tolerance", "0.01")) if isinstance(control, dict) else Decimal("0.01")
        if tolerance < 0:
            raise InputError("AF_RECONCILE_INVALID", "controlTotal.tolerance", "Tolerance must be nonnegative")
        if control is None:
            reason = "Nhánh chưa khai tổng kiểm soát nguồn tương ứng."
        else:
            try:
                index = next(index for index, column in enumerate(result["columns"]) if column["name"] == control["resultColumn"])
                result_total = sum((_amount(row[index]) for row in result["rows"] if row[index] is not None), Decimal(0))
                source_total = _independent_source_total(normalized, source_tables, control)
                applicable = True
            except (_Unavailable, InputError, ValueError, TypeError, KeyError, StopIteration, IndexError, DecimalException) as exc:
                reason = str(exc) if isinstance(exc, _Unavailable) else "Chưa xác định được basis tổng nguồn độc lập theo kiểu và phạm vi dòng đã khai."
        total_passed = applicable and abs(source_total - result_total) <= tolerance
        allowed = _amount(branch.get("maxFanOut", "1"))
        if not Decimal(1) <= allowed <= Decimal(100000):
            raise InputError("AF_RECONCILE_INVALID", "maxFanOut", "Fan-out limit must be within 1..100000")
        fanout_passed, fanout_detail = _fanout(normalized, result, allowed)
        blockers = []
        if not shape_passed:
            blockers.append({"code": "AF_RECONCILE_FAILED", "path": "result", "detail": "Hình dạng, số dòng/cột hoặc binding Preview không khớp."})
        if applicable and not total_passed:
            blockers.append({"code": "AF_RECONCILE_FAILED", "path": "controlTotal", "detail": "Tổng kết quả lệch tổng nguồn độc lập quá tolerance."})
        if not fanout_passed:
            blockers.append({"code": "AF_FANOUT_RISK", "path": "fanOut.joins", "detail": fanout_detail})
        hard_passed = not blockers
        output = {"schemaVersion": "1.0", "planHash": branch["planHash"], "snapshotHash": preview["snapshotHash"],
                  "previewHash": preview["previewHash"], "resultDigest": preview["resultDigest"],
                  "sourceFingerprint": canonical_hash([{"name": table["name"], "header": table["header"], "rows": table["rows"]} for table in source_tables]),
                  "rowsIn": rows_in, "rowsOut": len(result.get("rows", [])), "colsIn": cols_in, "colsOut": len(result.get("columns", [])),
                  "controlTotal": deepcopy(control), "maxFanOut": str(allowed), "controlTotalApplicable": applicable,
                  "controlTotalReason": reason, "controlTotalSource": _number(source_total) if source_total is not None else None,
                  "controlTotalResult": _number(result_total) if result_total is not None else None,
                  "controlTotalTolerance": _number(tolerance), "controlTotalPassed": total_passed,
                  "fanOutPassed": fanout_passed, "hardChecksPassed": hard_passed,
                  "acknowledgementRequired": not applicable, "selectable": hard_passed,
                  "checks": [{"id": "R1", "passed": shape_passed, "detail": "Hình dạng và digest kết quả đầy đủ phải khớp Preview."},
                             {"id": "R2", "passed": total_passed, "detail": reason or "Tổng nguồn được tính riêng từ raw và bộ lọc nguồn."},
                             {"id": "R3", "passed": fanout_passed, "detail": fanout_detail},
                             {"id": "R4", "passed": None, "detail": "Chờ kết quả A/B do engine tính."}],
                  "blockers": blockers, "warnings": [] if applicable else [{"code": "AF_CONTROL_UNVERIFIED", "detail": reason}],
                  "passed": hard_passed and total_passed, "abIdentityPassed": None, "abDeltaHash": None,
                  "engine": deepcopy(ENGINE)}
        return _rehash(output)


def _branch_total(branch):
    result = branch.get("result")
    if not isinstance(result, dict) or branch.get("executionError"):
        raise _Unavailable("Một nhánh chưa có kết quả thi hành hợp lệ.")
    control = branch.get("controlTotal")
    name = control["resultColumn"] if control else None
    numeric = [column for column in result["columns"] if column["type"] in ("number", "integer")]
    if name is None:
        if len(numeric) != 1:
            raise _Unavailable("Chưa có một measure A/B duy nhất để so sánh.")
        name = numeric[0]["name"]
    index = next(index for index, column in enumerate(result["columns"]) if column["name"] == name)
    return name, sum((_amount(row[index]) for row in result["rows"] if row[index] is not None), Decimal(0))


def _control_basis(branch):
    """Prove the declared measure resolves to one actual ancestor source column."""
    plan, control = branch["plan"], branch["controlTotal"]
    by_id, ancestors = _graph(plan)
    source_map = {source["sourceId"]: source for source in plan["sources"]}
    candidates = []
    for reference in ancestors(plan["finalOutputStepId"]):
        source = source_map[by_id[reference]["operation"]["parameters"]["sourceId"]]
        candidates.extend((source["sourceId"], column["columnId"]) for column in source["columns"]
                          if column["name"] == control["sourceColumn"])
    if len(candidates) != 1:
        raise _Unavailable("Chưa xác định được duy nhất nguồn measure để so sánh A/B.")
    return candidates[0]


def build_ab_delta(branch_a, branch_b):
    """Only engine result matrices supply A/B totals; AI has no delta input."""
    with localcontext(_CONTEXT):
        try:
            name_a, total_a = _branch_total(branch_a)
            name_b, total_b = _branch_total(branch_b)
            control_a, control_b = branch_a.get("controlTotal"), branch_b.get("controlTotal")
            if not control_a or not control_b:
                raise _Unavailable("Chưa khai basis nguồn chung cho cả hai nhánh; tên cột kết quả giống nhau chưa đủ để so sánh cùng measure.")
            if control_a and control_b and control_a["sourceColumn"] != control_b["sourceColumn"]:
                raise _Unavailable("Hai nhánh khai cột nguồn kiểm soát khác nhau; không coi là cùng một measure A/B.")
            if _control_basis(branch_a) != _control_basis(branch_b):
                raise _Unavailable("Hai nhánh dùng bảng hoặc cột nguồn khác nhau; tên measure giống nhau chưa chứng minh cùng đơn vị A/B.")
            if name_a != name_b and (not control_a or not control_b or control_a["sourceColumn"] != control_b["sourceColumn"]):
                raise _Unavailable("Hai nhánh chưa khai measure có thể so sánh trực tiếp.")
            result = {"applicable": True, "a": _number(total_a), "b": _number(total_b),
                      "value": _number(total_a - total_b), "reason": None, "computedBy": "typed_local"}
        except (_Unavailable, KeyError, TypeError, ValueError, StopIteration, DecimalException) as exc:
            result = {"applicable": False, "a": None, "b": None, "value": None,
                      "reason": str(exc) if isinstance(exc, _Unavailable) else "Chưa tính được delta A/B hữu hạn.", "computedBy": "typed_local"}
        result["deltaHash"] = canonical_hash(result)
        return result


def ab_identity_passed(delta):
    with localcontext(_CONTEXT):
        if delta.get("applicable") is not True:
            return None
        try:
            return (_amount(delta["a"]) - _amount(delta["b"]) == _amount(delta["value"])
                    and delta["deltaHash"] == canonical_hash({key: value for key, value in delta.items() if key != "deltaHash"}))
        except (KeyError, TypeError, ValueError, DecimalException):
            return False


def bind_ab_identity(reconciliation, delta):
    result = deepcopy(reconciliation)
    passed = ab_identity_passed(delta)
    result["abIdentityPassed"] = passed
    result["abDeltaHash"] = delta["deltaHash"]
    result["checks"][-1] = {"id": "R4", "passed": passed,
                            "detail": "A.total − B.total = delta do engine tính." if passed is True else delta.get("reason") or "A/B identity không khớp."}
    if passed is False:
        result["blockers"].append({"code": "AF_RECONCILE_FAILED", "path": "delta", "detail": "A/B identity không khớp."})
        result["hardChecksPassed"] = result["selectable"] = result["passed"] = False
    return _rehash(result)
