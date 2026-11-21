"""Đối soát WL5 thuần bộ nhớ; không cấp quyền ghi hoặc tự mở nguồn."""

from __future__ import annotations

from decimal import Decimal, localcontext
import re

from pbip_assistant.errors import InputError
from .assistant_findings import (
    _account, _ARITHMETIC_CONTEXT, _decimal, _finance, _period, _records,
    _sales, _select, _unique, number,
)
from .assistant_ingest import canonical_hash
from .assistant_preview import _supported_recipe, result_digest
from .assistant_profile import profile_table
from .assistant_roles import warning_classification
from .assistant_spec import spec_fingerprint


_BASIS = ("specFingerprint", "previewHash", "rowsIn", "rowsInDeduped", "rowsOut", "colsIn", "colsOut",
          "controlTotalRawSource", "droppedByDedupe", "controlTotalSource", "controlTotalResult",
          "controlTotalTolerance", "controlTotalPassed", "bridge", "checks", "blockers", "warnings",
          "labels", "passed", "variantOf", "variantReason")
_PREVIEW_BASIS = ("specFingerprint", "target", "counts", "source", "sheets", "variantOf", "variantReason")
_COLUMNS = {
    "tp-fin": ["pnlLine", "accountCode", "costCenter", "entityCode", "actualVnd", "budgetVnd",
               "varianceVnd", "period", "currency"],
    "tp-sales": ["region", "revenueVnd", "orderCount", "customerCount"],
}
_CONTROL = ("controlTotalRawSource", "droppedByDedupe", "controlTotalSource", "controlTotalResult")
_CHECKS = ("row_count", "control_total", "bridge_identity")
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_ZERO = Decimal("0")


def _invalid(message: str, code: str = "AF_RECONCILE_INVALID") -> InputError:
    return InputError(code, "reconciliation", message)


def _amount(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise _invalid("Số đối soát phải là Decimal, số nguyên hoặc chuỗi số hữu hạn.")
    try:
        return _decimal(str(value))
    except InputError as exc:
        raise _invalid("Số đối soát bị thiếu, không hữu hạn hoặc vượt giới hạn.") from exc


def _text(value: Decimal) -> str:
    return number(value, "decimal")


def _raw(raw_tables) -> tuple[list[dict], str]:
    if not isinstance(raw_tables, list) or not raw_tables or len(raw_tables) > 128:
        raise _invalid("Cần danh sách bảng nguồn đã ingest trong giới hạn.")
    names, row_count = set(), 0
    try:
        for table in raw_tables:
            profile = profile_table(table)
            row_count += profile["rowCount"]
            identifier = table.get("id")
            if identifier is not None and (not isinstance(identifier, str) or re.fullmatch(r"tbl_[a-f0-9]{12}", identifier) is None):
                raise _invalid("Định danh bảng raw không hợp lệ.")
            if profile["name"] in names or row_count > 100000 or profile["columnCount"] > 256:
                raise _invalid("Tên bảng trùng hoặc kích thước nguồn vượt giới hạn.")
            names.add(profile["name"])
    except (TypeError, ValueError, KeyError) as exc:
        raise _invalid("Bảng nguồn không đúng shape raw đã ingest.") from exc
    finance = any({"DocNo", "DebitCredit", "PostingDate", "Amount"} <= set(t["header"]) for t in raw_tables)
    return raw_tables, "tp-fin" if finance else "tp-sales"


def _result(result, scenario: str) -> list[list]:
    if (not isinstance(result, dict) or set(result) != {"columns", "rows"}
            or result["columns"] != _COLUMNS[scenario] or not isinstance(result["rows"], list)
            or len(result["rows"]) > 100000):
        raise _invalid("Kết quả phải có đúng cột và danh sách hàng của scenario.")
    for row in result["rows"]:
        if not isinstance(row, list) or len(row) != len(_COLUMNS[scenario]):
            raise _invalid("Hàng kết quả không khớp độ rộng cột.")
        text_indexes = (0, 1, 2, 3, 7, 8) if scenario == "tp-fin" else (0,)
        if any(not isinstance(row[index], str) for index in text_indexes):
            raise _invalid("Chiều nhóm và nhãn kỳ phải là chuỗi.")
        for index in ((4, 5, 6) if scenario == "tp-fin" else (1, 2, 3)):
            if isinstance(row[index], bool) or not isinstance(row[index], (Decimal, int)):
                raise _invalid("Cột số kết quả phải giữ kiểu Decimal hoặc số nguyên, không phải text.")
            _amount(row[index])
        if scenario == "tp-sales" and any(_amount(row[index]) < 0 or
                _amount(row[index]) != _amount(row[index]).to_integral_value() for index in (2, 3)):
            raise _invalid("Số đơn và khách phải là số nguyên không âm.")
    return result["rows"]


def _layout(tables: list[dict], scenario: str) -> tuple[int, int, int, list]:
    """Suy số hàng kỳ vọng từ khóa nguồn; độc lập với số hàng caller giao."""
    if scenario == "tp-sales":
        source = _select(tables, {"OrderID", "ProductID", "Quantity", "UnitPrice", "DiscountPct"})
        orders = _records(_select(tables, {"OrderID", "OrderDate", "CustomerID", "TerritoryID", "Status"}))
        customers = _unique(_records(_select(tables, {"CustomerID", "TerritoryID"}, excluded={"OrderID"})), "CustomerID")
        territories = _unique(_records(_select(tables, {"TerritoryID", "Region"})), "TerritoryID")
        regions = set()
        for order in orders:
            if order["Status"] != "Cancelled":
                territory = order["TerritoryID"].strip() or customers.get(order["CustomerID"], {}).get("TerritoryID", "")
                regions.add(territories.get(territory, {}).get("Region", "UNKNOWN"))
        return len(source["rows"]), len(source["rows"]), len(source["header"]), sorted(regions)
    source = _select(tables, {"DocNo", "LineNo", "DebitCredit", "Amount", "PartnerEntity", "PostingDate"})
    rows = _records(source)
    accounts = _unique(_records(_select(tables, {"AccountCode", "AccountType", "PnlGroup"})), "AccountCode")
    centers = _unique(_records(_select(tables, {"CostCenter", "EntityCode"}, excluded={"DocNo", "Amount"})), "CostCenter")
    budget = _records(_select(tables, {"Month", "AccountCode", "CostCenter", "Currency", "Amount"}, excluded={"DebitCredit"}))
    distinct = {tuple(row) for row in source["rows"]}
    periods = {_period(row["PostingDate"]) for row in rows}
    if len(periods) != 1:
        raise _invalid("Kế hoạch FIN hiện chỉ đối soát một kỳ GL duy nhất.")
    keys = set()
    for row in rows:
        account = _account(row["AccountCode"], accounts)
        line = "IntercompanyReconciliation" if row["PartnerEntity"].strip() else account["PnlGroup"]
        keys.add((line, account["AccountCode"], row["CostCenter"], row["EntityCode"]))
    for row in budget:
        if row["Month"] not in periods:
            continue
        account = _account(row["AccountCode"], accounts)
        entity = centers.get(row["CostCenter"], {}).get("EntityCode", "UNKNOWN")
        keys.add((account["PnlGroup"], row["AccountCode"], row["CostCenter"], entity))
    return len(rows), len(distinct), len(source["header"]), sorted(keys)


def _measures(tables, scenario):
    return _finance(tables) if scenario == "tp-fin" else _sales(tables)


def _controls(measures, rows, scenario):
    raw = measures["control_total_raw"] if scenario == "tp-fin" else measures["revenue_excluding_cancelled"]
    source = measures["control_total_deduped"] if scenario == "tp-fin" else raw
    index = 4 if scenario == "tp-fin" else 1
    return dict(zip(_CONTROL, map(_text, (raw, raw - source, source, sum((_amount(row[index]) for row in rows), _ZERO))), strict=True))


def control_totals(raw_tables, result, *, scenario) -> dict:
    """Tổng nguồn độc lập tổng kết quả; SALES dùng phạm vi loại Cancelled đã chốt."""
    with localcontext(_ARITHMETIC_CONTEXT):
        tables, detected = _raw(raw_tables)
        if not isinstance(scenario, str) or scenario not in _COLUMNS or scenario != detected:
            raise _invalid("Scenario không khớp schema nguồn.")
        rows = _result(result, scenario)
        return _controls(_measures(tables, scenario), rows, scenario)


def _bridge(measures, scenario):
    result = {"applicable": scenario == "tp-fin", "scope": None, "op": None, "fx": None,
              "total": None, "variance": None, "passed": None}
    if scenario == "tp-sales":
        return result
    result.update({"scope": "NetRevenue", "passed": False,
                   **{field: None for field in ("actualUsd", "actualVnd", "budgetUsd", "budgetVnd", "rateActual", "rateBudget")}})
    if measures is None:
        return result
    source_fields = {"actualUsd": "actual_usd", "actualVnd": "actual_vnd", "budgetUsd": "budget_usd",
                     "budgetVnd": "budget_vnd", "rateActual": "rate_actual_usd_average", "rateBudget": "rate_budget_usd",
                     "op": "op", "fx": "fx", "total": "bridge_total", "variance": "variance"}
    result.update({target: _text(measures[source]) if measures[source] is not None else None for target, source in source_fields.items()})
    result["passed"] = measures["op"] + measures["fx"] == measures["bridge_total"] == measures["variance"]
    return result


def _rate_messages(tables, scenario):
    if scenario != "tp-fin":
        return [{"code": "AF_MISSING_DATA", "severity": "warning",
                 "message": "Chưa có nguồn cùng kỳ hoặc cờ khách rời bỏ; không kết luận nguyên nhân thiếu khách."}]
    # Context profile dùng riêng cho classifier WL2; không dựng hoặc giả hash snapshot.
    profiles = []
    for table in tables:
        profile = profile_table(table)
        profile["id"] = table.get("id", profile["id"])
        profiles.append(profile)
    return warning_classification({"tables": profiles}, tables)


def _bindings(preview, spec, scenario):
    if (not isinstance(spec, dict) or spec.get("fingerprint") != spec_fingerprint(spec)
            or spec.get("stale") is not False or "stale" in spec.get("labels", [])):
        raise _invalid("Spec sai hash hoặc đã stale.", "AF_SPEC_STALE")
    if any(step["status"] != "ok" or step["guard"] is not None for step in spec["steps"]):
        raise _invalid("Spec còn step chưa đủ điều kiện thực thi.")
    _supported_recipe(spec, scenario)
    choices = [choice for step in spec["steps"] for choice in step["params"].get("chosenOptions", {}).values()]
    if not choices or any(choice != "A" for choice in choices):
        raise _invalid("WL5 hiện chỉ thực thi tập policy A; không đổi lựa chọn hộ.")
    if (not isinstance(preview, dict)
            or set(preview) != {*_PREVIEW_BASIS, "schemaVersion", "hashBasis", "previewHash"}
            or preview.get("schemaVersion") != "1.0"
            or preview.get("variantOf") is not None or preview.get("variantReason") is not None
            or preview.get("hashBasis") != list(_PREVIEW_BASIS)
            or preview.get("previewHash") != canonical_hash({key: preview.get(key) for key in _PREVIEW_BASIS})
            or preview.get("specFingerprint") != spec["fingerprint"]):
        raise _invalid("Preview sai hash hoặc không thuộc đúng Spec.", "AF_SPEC_STALE")
    target = preview.get("target")
    expected_sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
    if (not isinstance(target, dict) or target.get("sheet") != expected_sheet
            or target.get("mode") != "values_only" or target.get("workbook") != "temp_copy"
            or preview.get("counts") != {"formulaCount": 0, "queryCount": 0, "connectionCount": 0}):
        raise _invalid("Preview không đúng đích values-only hoặc còn formula/query/connection.")
    marker = target.get("marker")
    parts = marker.split("|") if isinstance(marker, str) else []
    if (len(parts) != 5 or parts[:3] != ["LOCAL_DATA_COPILOT", expected_sheet, "spec=" + spec["fingerprint"]]
            or not parts[3].startswith("preview=") or _HASH.fullmatch(parts[3][8:]) is None
            or parts[4] != "labels=" + ",".join(spec["labels"])):
        raise _invalid("Marker Preview phải bind đúng Spec, digest payload và nhãn.")
    source = preview.get("source")
    if (not isinstance(source, dict) or source.get("unchanged") is not True
            or not isinstance(source.get("before"), str) or _HASH.fullmatch(source["before"]) is None
            or source.get("before") != source.get("after")):
        raise _invalid("Nguồn Preview không còn nguyên trạng.", "AF_SOURCE_LOST")
    return parts[3][8:]


def build_reconciliation(preview, spec, raw_tables, result, *, tolerance="0.01", injected_drift=None) -> dict:
    """Tính lại control/bridge từ raw; lỗi nguồn đo được trả artifact chặn duyệt."""
    with localcontext(_ARITHMETIC_CONTEXT):
        tables, scenario = _raw(raw_tables)
        rows = _result(result, scenario)
        declared_payload = _bindings(preview, spec, scenario)
        payload_passed = declared_payload == result_digest(result)
        allowed = _amount(tolerance)
        if allowed < 0 or allowed > Decimal("0.01"):
            raise _invalid("Tolerance phải không âm và không nới quá 0.01.")
        rows_in, deduped, cols_in, expected_keys = _layout(tables, scenario)
        messages = _rate_messages(tables, scenario)
        warnings = [message for message in messages if message["severity"] == "warning"]
        missing = [message for message in messages if message["severity"] == "blocker"]
        measures = None
        try:
            measures = _measures(tables, scenario)
        except InputError as exc:
            if exc.code != "AF_MISSING_DATA":
                raise
            missing.append({"code": "AF_MISSING_DATA", "severity": "blocker",
                            "message": "Thiếu basis nguồn hoặc tỷ giá được dùng; không xuất số quy đổi chưa tính được."})
        if measures is not None:
            controls = _controls(measures, rows, scenario)
        else:
            index = 4 if scenario == "tp-fin" else 1
            controls = {**{field: None for field in _CONTROL},
                        "controlTotalResult": _text(sum((_amount(row[index]) for row in rows), _ZERO))}
        if injected_drift is not None:
            controls["controlTotalResult"] = _text(_amount(controls["controlTotalResult"]) + _amount(injected_drift))
        total_passed = (measures is not None and not missing and
                        abs(_amount(controls["controlTotalSource"]) - _amount(controls["controlTotalResult"])) <= allowed)
        keys = [tuple(row[:4]) if scenario == "tp-fin" else row[0] for row in rows]
        sheets = preview.get("sheets", {})
        row_passed = (payload_passed and keys == expected_keys and sheets.get("before") == {"rows": rows_in, "cols": cols_in}
                      and sheets.get("after") == {"rows": len(rows), "cols": len(result["columns"])})
        bridge = _bridge(measures, scenario)
        if scenario == "tp-fin" and measures is not None:
            row_identities = all(_amount(row[4]) - _amount(row[5]) == _amount(row[6]) for row in rows)
            result_variance = sum((_amount(row[6]) for row in rows if row[0] == "NetRevenue"), _ZERO)
            bridge["passed"] = bridge["passed"] and row_identities and result_variance == measures["variance"]
        bridge_passed = not bridge["applicable"] or bridge["passed"] is True
        checks = [
            {"id": "row_count", "passed": row_passed,
             "detail": f"{rows_in} → {deduped} → {len(rows)}; cột {cols_in} → {len(result['columns'])}; kỳ vọng {len(expected_keys)} hàng; digest payload khớp={payload_passed}."},
            {"id": "control_total", "passed": total_passed,
             "detail": "Tổng nguồn=" + str(controls["controlTotalSource"]) + "; tổng kết quả=" + controls["controlTotalResult"] + "; tolerance=" + _text(allowed) + "."},
            {"id": "bridge_identity", "passed": bridge_passed,
             "detail": "op + fx = total = variance nguồn và NetRevenue kết quả; từng hàng actual - budget = variance."
             if bridge["applicable"] else "Không áp dụng cầu nối FX cho SALES."},
        ]
        passed = all(check["passed"] for check in checks) and not missing
        blockers = [] if passed else [{"code": "AF_RECONCILE_FAILED", "severity": "blocker",
                                      "message": "Đối soát nguồn và kết quả chưa đạt; không được duyệt."}]
        blockers.extend(missing)
        output = {"schemaVersion": "1.0", "specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"],
                  "rowsIn": rows_in, "rowsInDeduped": deduped, "rowsOut": len(rows), "colsIn": cols_in,
                  "colsOut": len(result["columns"]), **controls, "controlTotalTolerance": _text(allowed),
                  "controlTotalPassed": total_passed, "bridge": bridge, "checks": checks, "blockers": blockers,
                  "warnings": warnings, "labels": list(spec["labels"]), "passed": passed, "variantOf": None,
                  "variantReason": None, "hashBasis": list(_BASIS), "reconcileHash": ""}
        output["reconcileHash"] = canonical_hash({field: output[field] for field in _BASIS})
        return output


def assert_approvable(reconciliation) -> None:
    """Cổng kiểm integrity và ba check; không phải approval hoặc quyền Apply WL6."""
    try:
        if (not isinstance(reconciliation, dict)
                or set(reconciliation) != {*_BASIS, "schemaVersion", "hashBasis", "reconcileHash"}
                or reconciliation.get("schemaVersion") != "1.0" or reconciliation.get("passed") is not True
                or reconciliation.get("hashBasis") != list(_BASIS)
                or reconciliation.get("reconcileHash") != canonical_hash({k: reconciliation[k] for k in _BASIS})
                or reconciliation.get("blockers") != [] or reconciliation.get("controlTotalPassed") is not True
                or [check["id"] for check in reconciliation["checks"]] != list(_CHECKS)
                or any(check["passed"] is not True for check in reconciliation["checks"])):
            raise ValueError
        if any(not isinstance(reconciliation[field], str) or _HASH.fullmatch(reconciliation[field]) is None
               for field in ("specFingerprint", "previewHash", "reconcileHash")):
            raise ValueError
        if any(type(reconciliation[field]) is not int or reconciliation[field] < 0
               for field in ("rowsIn", "rowsInDeduped", "rowsOut", "colsIn", "colsOut")):
            raise ValueError
        if (reconciliation["rowsInDeduped"] > reconciliation["rowsIn"] or reconciliation["variantOf"] is not None
                or reconciliation["variantReason"] is not None or not isinstance(reconciliation["labels"], list)
                or any(label not in {"assumed", "unverified", "out_of_scope"} for label in reconciliation["labels"])):
            raise ValueError
        with localcontext(_ARITHMETIC_CONTEXT):
            raw, dropped, source, result = (_amount(reconciliation[field]) for field in _CONTROL)
            tolerance = _amount(reconciliation["controlTotalTolerance"])
            if tolerance < 0 or tolerance > Decimal("0.01") or raw - dropped != source or abs(source - result) > tolerance:
                raise ValueError
            bridge = reconciliation["bridge"]
            if bridge["applicable"] is True:
                if bridge["passed"] is not True or _amount(bridge["op"]) + _amount(bridge["fx"]) != _amount(bridge["total"]) or _amount(bridge["total"]) != _amount(bridge["variance"]):
                    raise ValueError
            elif bridge["applicable"] is not False or any(value is not None for key, value in bridge.items() if key != "applicable"):
                raise ValueError
    except (InputError, KeyError, TypeError, ValueError) as exc:
        raise _invalid("Đối soát chưa đạt hoặc artifact không còn toàn vẹn; không được duyệt.", "AF_RECONCILE_FAILED") from exc
