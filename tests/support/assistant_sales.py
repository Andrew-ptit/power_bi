"""Oracle Decimal và builder fixture TP-SALES; chỉ đọc CSV synthetic đã lưu."""

from __future__ import annotations

from collections import Counter
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "assistant" / "tp-sales" / "source"
ZERO = Decimal("0")
CENT = Decimal("0.01")
STAMP = "2026-10-26T09:00:00Z"
LABELS = ["assumed", "unverified"]
PROMPT = "Doanh thu theo khu vực quý 3 giảm vì đơn huỷ hay thiếu khách?"
SOURCE_FILES = (
    "Customers.csv", "OrderItems.csv", "Products.csv", "Territory.csv",
    "orders/Orders_2026-07.csv", "orders/Orders_2026-08.csv", "orders/Orders_2026-09.csv",
)


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def identifier(prefix: str, value: object, length: int = 12) -> str:
    return prefix + canonical_hash(value).split(":")[1][:length]


def decimal_text(value: Decimal | int) -> str:
    text = format(Decimal(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _read(relative: str) -> list[dict[str, str]]:
    with (SOURCE_ROOT / relative).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _step_plan(table_ids: dict[str, str], formula_ids: dict[str, str]) -> list[dict]:
    """Ten-step pipeline; ids, refs and order are part of the fixture contract."""
    steps = []

    def step(kind: str, operation: str, label: str, refs: list[str], table: str | None = None, columns: list[str] | None = None, formula: str | None = None) -> None:
        index = len(steps) + 1
        steps.append({"id": f"st_{index:02d}", "kind": kind, "label": label, "decisionRefs": refs,
                      "inputs": ([steps[-1]["output"]] if steps else []) + ([table_ids[table]] if table else []),
                      "params": {"operation": operation, "tableId": table_ids[table] if table else None, "columns": columns, "formulaId": formula},
                      "output": f"q_sales_{index:02d}", "dependsOn": [steps[-1]["id"]] if steps else [], "status": "ok", "guard": None})

    step("recipe", "folder_append", "Nạp đơn hàng theo thứ tự tên file tháng", [], "Orders")
    step("join", "join_order_items", "Nối đơn hàng với dòng chi tiết", [], "OrderItems", ["OrderID"])
    step("join", "join_customers", "Nối khách hàng, giữ khách ngoài danh mục trong nhóm riêng", ["SP-3"], "Customers", ["CustomerID"])
    step("join", "join_products", "Nối danh mục sản phẩm", [], "Products", ["ProductID"])
    step("lookup", "resolve_territory", "Lấy khu vực trên đơn hoặc từ danh mục khách hàng", ["SP-4"], "Territory", ["TerritoryID"])
    step("filter", "exclude_cancelled", "Loại đơn huỷ theo quyết định đã chốt", ["SP-1"])
    step("calc", "line_revenue_net_returns", "Tính doanh thu sau chiết khấu, giữ dòng trả hàng âm", ["SP-2"], formula=formula_ids["revenueExcludingCancelled"])
    step("group", "group_region", "Gộp doanh thu theo khu vực", [], columns=["region"])
    step("sort", "sort_region", "Sắp xếp khu vực để kết quả tái lập", [], columns=["region"])
    step("output", "values_only", "Xuất kết quả chỉ giá trị có nhãn", [])
    return steps


def _tables() -> dict[str, list[dict[str, str]]]:
    tables = {Path(name).stem: _read(name) for name in SOURCE_FILES if "/" not in name}
    tables["Orders"] = [row for name in sorted(SOURCE_FILES) if name.startswith("orders/") for row in _read(name)]
    return tables


def line_revenue(item: dict[str, str]) -> Decimal:
    return (Decimal(item["Quantity"]) * Decimal(item["UnitPrice"]) *
            (Decimal("1") - Decimal(item["DiscountPct"]) / Decimal("100"))).quantize(CENT, ROUND_HALF_UP)


def _metrics(tables: dict[str, list[dict[str, str]]]) -> tuple[dict[str, object], list[dict[str, object]]]:
    orders = tables["Orders"]
    items = tables["OrderItems"]
    customers = {row["CustomerID"]: row for row in tables["Customers"]}
    territories = {row["TerritoryID"]: row for row in tables["Territory"]}
    amounts: dict[str, Decimal] = {}
    for item in items:
        amounts[item["OrderID"]] = amounts.get(item["OrderID"], ZERO) + line_revenue(item)
    cancelled = {row["OrderID"] for row in orders if row["Status"] == "Cancelled"}
    returned = {row["OrderID"] for row in orders if row["Status"] == "Returned"}
    groups: dict[str, dict[str, object]] = {}
    for order in orders:
        if order["OrderID"] in cancelled:
            continue
        territory = order["TerritoryID"].strip() or customers.get(order["CustomerID"], {}).get("TerritoryID", "")
        region = territories.get(territory, {}).get("Region", "UNKNOWN")
        group = groups.setdefault(region, {"region": region, "revenue": ZERO, "orderIds": set(), "customerIds": set()})
        group["revenue"] += amounts.get(order["OrderID"], ZERO)
        group["orderIds"].add(order["OrderID"])
        group["customerIds"].add(order["CustomerID"] if order["CustomerID"] in customers else "UNKNOWN_CUSTOMER")
    result = [{"region": region, "revenue": decimal_text(group["revenue"]),
               "orders": len(group["orderIds"]), "customers": len(group["customerIds"])}
              for region, group in sorted(groups.items())]
    anchors = {
        "orders": len(orders), "orderLines": len(items), "cancelledOrders": len(cancelled),
        "returnedOrders": len(returned),
        "orphanCustomerOrders": sum(row["CustomerID"] not in customers for row in orders),
        "ordersMissingTerritory": sum(not row["TerritoryID"].strip() for row in orders),
        "revenueAllOrders": decimal_text(sum(amounts.values(), ZERO)),
        "revenueExcludingCancelled": decimal_text(sum((amount for key, amount in amounts.items() if key not in cancelled), ZERO)),
        "revenueCancelledExcluded": decimal_text(sum((amounts.get(key, ZERO) for key in cancelled), ZERO)),
        "returnLinesEffect": decimal_text(sum((line_revenue(item) for item in items if item["OrderID"] in returned), ZERO)),
        "regionTotals": {row["region"]: row["revenue"] for row in result},
    }
    return anchors, result


ANCHORS = _metrics(_tables())[0]


def _artifact(fields: dict[str, object], hash_name: str, basis: list[str] | None = None) -> dict[str, object]:
    document = {"schemaVersion": "1.0", **fields, "variantOf": None, "variantReason": None}
    document["hashBasis"] = [*(basis if basis is not None else list(fields)), "variantOf", "variantReason"]
    document[hash_name] = canonical_hash({key: document[key] for key in document["hashBasis"]})
    return document


def _evidence(kind: str, value: str | None = None, ref: str | None = None, formula_id: str | None = None) -> dict[str, object]:
    return {"kind": kind, "value": value, "ref": ref, "formulaId": formula_id}


def _ratio(numerator: int, denominator: int) -> float:
    return float((Decimal(numerator) / Decimal(denominator) if denominator else ZERO).quantize(Decimal("0.001"), ROUND_HALF_UP))


def _column(name: str, rows: list[dict[str, str]]) -> dict[str, object]:
    values = [row[name] for row in rows]
    nonempty = [value for value in values if value != ""]
    if name.endswith("ID") or name == "LineNo":
        kind, role = ("integer" if name == "LineNo" else "text"), "key"
    elif name == "OrderDate":
        kind, role = "date", "date"
    elif name in {"Quantity", "UnitPrice", "ListPrice", "DiscountPct"}:
        kind = "integer" if all(re.fullmatch(r"-?\d+", value) for value in nonempty) else "decimal"
        role = "percent" if name == "DiscountPct" else "amount"
    else:
        kind, role = "text", "text"
    return {"name": name, "type": kind, "nullRate": _ratio(len(values) - len(nonempty), len(values)),
            "distinctCount": len(set(nonempty)), "distinctRatio": _ratio(len(set(nonempty)), len(values)),
            "sample": values[:20], "role": role, "roleStatus": "inferred",
            "evidence": [_evidence("distinct_ratio", decimal_text(Decimal(str(_ratio(len(set(nonempty)), len(values))))),
                                    formula_id="fm_profile_distinct_ratio")]}


def _snapshot(tables: dict[str, list[dict[str, str]]]) -> dict[str, object]:
    sources, profiled = [], []
    for name, rows in sorted(tables.items()):
        folder = name == "Orders"
        origin = "source/orders" if folder else f"source/{name}.csv"
        content = [{"name": Path(path).name, "content": (SOURCE_ROOT / path).read_text(encoding="utf-8")}
                   for path in SOURCE_FILES if path.startswith("orders/")] if folder else (SOURCE_ROOT / f"{name}.csv").read_text(encoding="utf-8")
        source_id = identifier("src_", origin)
        sources.append({"id": source_id, "name": name if folder else f"{name}.csv", "type": "folder" if folder else "csv",
                        "origin": origin, "hash": canonical_hash(content), "addedAt": STAMP})
        header = list(rows[0])
        sample = [list(row.values()) for row in rows[:20]]
        profiled.append({"id": identifier("tbl_", name), "sourceId": source_id, "name": name,
                         "locator": {"kind": "folder" if folder else "file", "sheet": None, "range": None,
                                     "path": origin, "fileCount": sum(path.startswith("orders/") for path in SOURCE_FILES) if folder else len([origin])},
                         "rowCount": len(rows), "columnCount": len(header), "headerHash": canonical_hash(header),
                         "sampleHash": canonical_hash(sample), "fingerprint": canonical_hash({"name": name, "header": header, "sample": sample}),
                         "columns": [_column(field, rows) for field in header]})
    return _artifact({"snapshot": {"snapshotId": identifier("snap_", sources, 24), "createdAt": STAMP,
                                   "sessionId": identifier("sess_", "tp-sales"), "sourceCount": len(sources), "tableCount": len(profiled)},
                      "sources": sources, "tables": profiled}, "snapshotHash")


def build_fixtures() -> dict[str, str]:
    """Dựng mười JSON từ CSV đã lưu, không đọc thư mục giao việc hoặc workbook."""
    tables = _tables()
    anchors, result_rows = _metrics(tables)
    snapshot = _snapshot(tables)
    table_ids = {name: identifier("tbl_", name) for name in tables}
    formula_values = {key: value for key, value in anchors.items() if key != "regionTotals"}
    formula_values.update({f"region_{key.lower()}": value for key, value in anchors["regionTotals"].items()})
    customers = {row["CustomerID"]: row for row in tables["Customers"]}
    orders_by_id = {row["OrderID"]: row for row in tables["Orders"]}
    orphan_ids = {row["OrderID"] for row in tables["Orders"] if row["CustomerID"] not in customers}
    orphan_effect = sum((line_revenue(item) for item in tables["OrderItems"]
                         if item["OrderID"] in orphan_ids and orders_by_id[item["OrderID"]]["Status"] != "Cancelled"), ZERO)
    territory_effect = sum((line_revenue(item) for item in tables["OrderItems"]
                           if not orders_by_id[item["OrderID"]]["TerritoryID"] and
                           customers.get(orders_by_id[item["OrderID"]]["CustomerID"], {}).get("TerritoryID") and
                           orders_by_id[item["OrderID"]]["Status"] != "Cancelled"), ZERO)
    formula_values.update({"orphanCustomerRevenue": decimal_text(orphan_effect), "territoryFallbackRevenue": decimal_text(territory_effect)})
    formula_ids = {key: "fm_" + re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower() for key in formula_values}
    expressions = {
        "orders": "count(append_csv_files_sorted_by_name(Orders))",
        "orderLines": "count(OrderItems)", "cancelledOrders": "count(Orders where Status == 'Cancelled')",
        "returnedOrders": "count(Orders where Status == 'Returned')",
        "orphanCustomerOrders": "count(Orders anti_join Customers on CustomerID)",
        "ordersMissingTerritory": "count(Orders where TerritoryID is blank)",
        "revenueAllOrders": "sum(Quantity * UnitPrice * (1 - DiscountPct / 100))",
        "revenueExcludingCancelled": "sum(lineRevenue where Orders.Status != 'Cancelled')",
        "revenueCancelledExcluded": "sum(lineRevenue where Orders.Status == 'Cancelled')",
        "returnLinesEffect": "sum(lineRevenue where Orders.Status == 'Returned')",
        "orphanCustomerRevenue": "sum(lineRevenue where customer missing and Status != 'Cancelled')",
        "territoryFallbackRevenue": "sum(lineRevenue where order territory blank and customer territory available and Status != 'Cancelled')",
    }
    formulas = _artifact({"formulas": [{"formulaId": formula_ids[key], "expression": expressions.get(key, f"sum(lineRevenue where resolvedRegion == '{key.removeprefix('region_').upper()}' and Status != 'Cancelled')"),
                                        "basis": "engine-decimal", "unit": "count" if isinstance(value, int) else "VND",
                                        "inputs": [table_ids[name] for name in sorted(tables)]}
                                       for key, value in formula_values.items()] + [
                                           {"formulaId": "fm_profile_distinct_ratio",
                                            "expression": "round_half_up(count(distinct(nonempty(column))) / count(table), 3)",
                                            "basis": "engine-decimal", "unit": "ratio",
                                            "inputs": [table_ids[name] for name in sorted(tables)]},
                                           {"formulaId": "fm_row_count", "expression": "count(table)",
                                            "basis": "engine-decimal", "unit": "count",
                                            "inputs": [table_ids[name] for name in sorted(tables)]}]}, "hash")

    def value(key: str) -> dict[str, str]:
        return {"formulaId": formula_ids[key], "value": str(formula_values[key]),
                "unit": "count" if isinstance(formula_values[key], int) else "VND"}

    assumptions = [{"id": identifier("asm_", policy), "statement": statement, "source": "data", "confidence": confidence,
                    "risk": "medium", "evidence": [_evidence("engine", str(anchors[metric]), formula_id=formula_ids[metric])]}
                   for policy, statement, metric, confidence in (
                       ("cancelled", "Đề xuất loại đơn huỷ khỏi doanh thu; người dùng chốt trước khi ghi.", "cancelledOrders", _ratio(1, 2)),
                       ("returns", "Đề xuất giữ số lượng âm để tính doanh thu thuần; người dùng chốt trước khi ghi.", "returnedOrders", _ratio(1, 2)),
                       ("territory", "Đề xuất dùng khu vực khách hàng khi khu vực trên đơn trống.", "ordersMissingTerritory", _ratio(3, 4)))]
    relations = []
    for from_name, to_name, key in (("OrderItems", "Orders", "OrderID"), ("Orders", "Customers", "CustomerID"),
                                    ("OrderItems", "Products", "ProductID"), ("Orders", "Territory", "TerritoryID"),
                                    ("Customers", "Territory", "TerritoryID")):
        keys = {row[key] for row in tables[to_name]}
        rows = tables[from_name]
        matches = sum(row[key] in keys for row in rows)
        overlap = _ratio(matches, len(rows))
        relations.append({"id": identifier("rel_", [from_name, to_name, key]), "fromTable": table_ids[from_name], "toTable": table_ids[to_name],
                          "fromColumns": [key], "toColumns": [key], "cardinality": "N:1", "score": overlap,
                          "evidence": {"name": _ratio(1, 1), "type": _ratio(1, 1), "overlap": overlap, "orphan": len(rows) - matches},
                          "status": "auto" if matches == len(rows) else "needs_confirm", "fanOutRisk": "none", "fanOutEvidence": None})
    understand = _artifact({"snapshotHash": snapshot["snapshotHash"],
                           "pack": {"id": "generic", "version": "1.0", "genericMode": True,
                                    "notice": "Không có domain pack: kết quả kém chính xác hơn finance pack."},
                           "roles": [{"tableId": table_ids[name], "structural": "fact" if name == "OrderItems" else "dim",
                                      "domainLabel": {"OrderItems": "Dòng đơn hàng", "Orders": "Đơn hàng", "Customers": "Khách hàng", "Products": "Sản phẩm", "Territory": "Khu vực"}[name],
                                      "confidence": _ratio(len({tuple(row.values()) for row in rows}), len(rows)),
                                      "evidence": [_evidence("row_count", str(len(rows)), ref=table_ids[name],
                                                              formula_id="fm_row_count")]} for name, rows in sorted(tables.items())],
                           "relationships": relations, "assumptions": assumptions,
                           "warnings": [{"code": "AF_MISSING_DATA", "severity": "warning", "message": "Không có cờ khách rời bỏ hoặc nguồn cùng kỳ; không kết luận nguyên nhân thiếu khách."}]}, "understandHash")
    specifications = (
        ("SP-1", "Đơn huỷ có được tính doanh thu không?", "assumed", "revenueCancelledExcluded",
         "Loại đơn huỷ khỏi doanh thu", "Giữ đơn huỷ và gắn cờ", "Policy này thay đổi tổng doanh thu."),
        ("SP-2", "Trả hàng với số lượng âm tính thuần hay gộp?", "assumed", "returnLinesEffect",
         "Tính thuần, giữ số lượng âm", "Không trừ dòng trả hàng, trình bày riêng", "Policy này thay đổi ảnh hưởng trả hàng."),
        ("SP-3", "Khách không có trong danh mục được xử lý thế nào?", "conflict", "orphanCustomerRevenue",
         "Giữ khách trong nhóm UNKNOWN_CUSTOMER", "Bỏ dòng có khách ngoài danh mục", "Bỏ khách ngoài danh mục làm mất doanh thu có trong nguồn."),
        ("SP-4", "Đơn thiếu khu vực được gán khu vực thế nào?", "inferred", "territoryFallbackRevenue",
         "Lấy khu vực từ danh mục khách, còn thiếu dùng UNKNOWN", "Giữ nhóm UNKNOWN cho khu vực trống", "Policy này thay đổi phân bổ khu vực, không thay đổi tổng."),
        ("SP-5", "Có cờ khách rời bỏ hoặc nguồn cùng kỳ để giải thích thiếu khách không?", "missing_data", None,
         "Báo cáo doanh thu, phần thiếu khách ngoài phạm vi", "Chờ nguồn khách rời bỏ hoặc cùng kỳ", "Chưa có nguồn; không kết luận khách rời bỏ hoặc so cùng kỳ."),
    )
    subproblems = []
    for sp_id, question, status, metric, label_a, label_b, why in specifications:
        subproblems.append({"id": sp_id, "question": question, "whyItMatters": why, "status": status, "provenance": "data",
                            "evidence": [_evidence("engine", str(formula_values[metric]), formula_id=formula_ids[metric])] if metric else [_evidence("source_scope", "Không có cờ khách rời bỏ hoặc nguồn cùng kỳ.")],
                            "options": [{"id": option_id, "label": label, "recommended": option_id == "A",
                                         "consequence": {"statement": why, "value": value(metric) if metric else None}}
                                        for option_id, label in (("A", label_a), ("B", label_b))],
                            "proposedOptionId": "A", "chosenOptionId": None, "blocker": status == "conflict",
                            "consequenceOfChoice": None, "labels": ["out_of_scope"] if metric is None else []})
    finding_statements = {
        "orders": "Số đơn trong các file tháng đã nối.", "orderLines": "Số dòng chi tiết đơn hàng.",
        "cancelledOrders": "Số đơn mang trạng thái huỷ.", "returnedOrders": "Số đơn mang trạng thái trả hàng.",
        "orphanCustomerOrders": "Số đơn có khách ngoài danh mục.", "ordersMissingTerritory": "Số đơn thiếu khu vực trên đơn.",
        "revenueAllOrders": "Doanh thu nguồn khi tính cả đơn huỷ.", "revenueExcludingCancelled": "Doanh thu thuần theo chính sách đề xuất loại đơn huỷ.",
        "revenueCancelledExcluded": "Doanh thu đơn huỷ bị loại theo chính sách đề xuất.", "returnLinesEffect": "Ảnh hưởng của dòng trả hàng trong doanh thu thuần.",
        "orphanCustomerRevenue": "Doanh thu được giữ trong nhóm khách ngoài danh mục.", "territoryFallbackRevenue": "Doanh thu được phân bổ bằng khu vực từ danh mục khách.",
    }
    brief = _artifact({"snapshotHash": snapshot["snapshotHash"], "understandHash": understand["understandHash"], "prompt": PROMPT,
                       "outputContract": {"grain": ["region"], "measures": [{"name": "NetRevenue", "formulaId": formula_ids["revenueExcludingCancelled"]}],
                                          "filters": [{"field": "OrderDate", "operator": "between", "value": ["2026-07-01", "2026-09-30"]}],
                                          "period": {"from": "2026-07-01", "to": "2026-09-30", "label": "Quý 3/2026"}, "currency": "VND"},
                       "findings": [{"id": identifier("fd_", key), "statement": finding_statements.get(key, "Doanh thu theo khu vực " + key.removeprefix("region_").upper() + "."),
                                     "value": value(key), "evidence": [_evidence("engine", str(metric), formula_id=formula_ids[key]), _evidence("source", ref=table_ids["OrderItems"])],
                                     "status": "inferred", "provenance": "data"} for key, metric in formula_values.items()],
                       "insightCases": [{"id": identifier("ic_", "cancelled"), "kind": "hypothesis", "statement": "Giả thuyết: loại đơn huỷ giải thích một phần chênh lệch tổng doanh thu; chưa đủ nguồn để kết luận khách rời bỏ.",
                                         "evidence": [_evidence("engine", str(anchors["revenueCancelledExcluded"]), formula_id=formula_ids["revenueCancelledExcluded"])], "status": "inferred", "provenance": "data"},
                                        {"id": identifier("ic_", "regions"), "kind": "slice", "statement": "Cắt doanh thu theo khu vực, giữ riêng khu vực chưa xác định.",
                                         "evidence": [_evidence("engine", str(anchors["regionTotals"]["UNKNOWN"]), formula_id=formula_ids["region_unknown"])], "status": "inferred", "provenance": "data"}],
                       "subProblems": subproblems, "scenarios": [], "delta": None, "assumptions": assumptions, "labels": LABELS.copy()}, "briefHash")
    decisions = _artifact({"snapshotHash": snapshot["snapshotHash"], "understandHash": understand["understandHash"], "briefHash": brief["briefHash"],
                           "decisions": [{"subProblemId": sp["id"], "optionId": "A", "decidedBy": "user", "decidedAt": "2026-10-26T09:30:00Z", "rationale": "Chấp nhận phương án đã đọc và hệ quả trong brief synthetic."} for sp in subproblems if sp["status"] != "missing_data"],
                           "acknowledgements": [{"subProblemId": "SP-5", "acknowledged": "out_of_scope", "note": "Chưa có nguồn để giải thích khách rời bỏ hoặc so cùng kỳ; không bịa số."}], "freezeBlocked": False}, "decisionsHash")
    steps = _step_plan(table_ids, formula_ids)
    spec = _artifact({"id": identifier("spec_", decisions["decisionsHash"], 24), "snapshotHash": snapshot["snapshotHash"], "decisionsHash": decisions["decisionsHash"],
                      "briefHash": brief["briefHash"], "steps": steps, "labels": LABELS.copy(), "unverifiedAssumptions": [item["id"] for item in assumptions],
                      "createdAt": "2026-10-26T09:40:00Z", "stale": False}, "fingerprint",
                     ["snapshotHash", "decisionsHash", "briefHash", "steps", "labels", "unverifiedAssumptions", "stale"])
    source_fingerprint = canonical_hash([{name: (SOURCE_ROOT / name).read_text(encoding="utf-8")} for name in SOURCE_FILES])
    source = {"before": source_fingerprint, "after": source_fingerprint, "unchanged": True}
    rows_in = len(tables["OrderItems"])
    cols_in = len(tables["OrderItems"][0])
    rows_out, cols_out = len(result_rows), len(result_rows[0])
    preview = _artifact({"specFingerprint": spec["fingerprint"],
                         "target": {"workbook": "temp_copy", "sheet": "Sales_Preview", "mode": "values_only",
                                    "marker": f"LOCAL_DATA_COPILOT|Sales_Preview|spec={spec['fingerprint']}|labels={','.join(LABELS)}"},
                         "counts": {"formulaCount": len([]), "queryCount": len([]), "connectionCount": len([])}, "source": source,
                         "sheets": {"before": {"rows": rows_in, "cols": cols_in}, "after": {"rows": rows_out, "cols": cols_out}}}, "previewHash")
    control_source = anchors["revenueExcludingCancelled"]
    control_result = decimal_text(sum((Decimal(row["revenue"]) for row in result_rows), ZERO))
    control_passed = Decimal(control_source) == Decimal(control_result)
    reconciliation = _artifact({"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"],
                                "rowsIn": rows_in, "rowsInDeduped": rows_in, "rowsOut": rows_out, "colsIn": cols_in, "colsOut": cols_out,
                                "controlTotalRawSource": control_source, "droppedByDedupe": decimal_text(ZERO),
                                "controlTotalSource": control_source, "controlTotalResult": control_result,
                                "controlTotalTolerance": decimal_text(CENT), "controlTotalPassed": control_passed,
                                "bridge": {"applicable": False, "scope": None, "op": None, "fx": None, "total": None, "variance": None, "passed": None},
                                "checks": [{"id": "row_count", "passed": rows_in == len(tables["OrderItems"]) and rows_out == len(result_rows), "detail": f"{rows_in} → {rows_out}"},
                                           {"id": "control_total", "passed": control_passed, "detail": f"{control_source} = {control_result}"},
                                           {"id": "bridge_identity", "passed": True, "detail": "Không áp dụng: báo cáo doanh thu không tính FX."}],
                                "blockers": [], "warnings": understand["warnings"], "labels": LABELS.copy(), "passed": control_passed}, "reconcileHash")
    apply = _artifact({"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"],
                       "approval": {"approvalId": identifier("apr_", [spec["fingerprint"], preview["previewHash"]]), "approvedBy": "user", "approvedAt": "2026-10-26T10:00:00Z",
                                    "boundTo": {"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"]}, "consumed": True, "singleUse": True},
                       "target": {"workbook": "current", "sheet": "Sales_Result", "mode": "values_only",
                                  "marker": f"LOCAL_DATA_COPILOT|Sales_Result|spec={spec['fingerprint']}|preview={preview['previewHash']}|labels={','.join(LABELS)}", "writeMode": "new_sheet_only"},
                       "written": {"rowCount": rows_out, "columnCount": cols_out}, "source": {**source, "sheetsWritten": []},
                       "workbookSaved": False, "labels": LABELS.copy(), "appliedAt": "2026-10-26T10:01:00Z"}, "hash",
                      ["specFingerprint", "previewHash", "approval", "target", "written", "source", "workbookSaved", "labels"])
    nulls_before = {key: sum(not row[key].strip() for row in tables["Orders"]) for key in ("TerritoryID", "CustomerID")}
    resolved_orders = [{**row, "TerritoryID": row["TerritoryID"].strip() or customers.get(row["CustomerID"], {}).get("TerritoryID", "") or "UNKNOWN",
                        "CustomerID": row["CustomerID"] if row["CustomerID"] in customers else "UNKNOWN_CUSTOMER"} for row in tables["Orders"]]
    nulls_after = {key: sum(not row[key].strip() for row in resolved_orders) for key in nulls_before}
    duplicates = sum(count - 1 for count in Counter(tuple(row.values()) for row in tables["OrderItems"]).values())
    record = _artifact({"id": identifier("rec_", spec["fingerprint"], 24), "createdAt": "2026-10-26T10:05:00Z",
                        "snapshot": {"snapshotHash": snapshot["snapshotHash"], "sourceFingerprint": source_fingerprint},
                        "brief": {"briefHash": brief["briefHash"], "prompt": PROMPT}, "decisions": decisions["decisions"], "assumptions": assumptions,
                        "steps": steps, "reconciliations": [reconciliation],
                        "delta": {"rowsIn": rows_in, "rowsOut": rows_out, "nullsBefore": nulls_before, "nullsAfter": nulls_after,
                                  "duplicatesBefore": duplicates, "duplicatesAfter": duplicates,
                                  "changedColumns": ["Quantity×UnitPrice×DiscountPct→revenue", "TerritoryID→region", "CustomerID→customerBucket"]},
                        "labels": LABELS.copy(), "stale": False}, "hash",
                       ["snapshot", "brief", "decisions", "assumptions", "steps", "reconciliations", "delta", "labels", "stale"])
    artifacts = {"formulas.json": formulas, "wl1_snapshot.json": snapshot, "wl2_understand.json": understand,
                 "wl3_brief.json": brief, "wl3_decisions.json": decisions, "wl4_execution_spec.json": spec,
                 "wl5_preview.json": preview, "wl5_reconciliation.json": reconciliation, "wl6_apply.json": apply, "wl7_decision_record.json": record}
    return {name: json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n" for name, document in artifacts.items()}


def generate(root: Path) -> None:
    """Ghi bộ dữ liệu riêng; không sửa bất kỳ nguồn CSV nào."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, document in build_fixtures().items():
        (root / name).write_text(document, encoding="utf-8", newline="\n")
    for relative in SOURCE_FILES:
        destination = root / "source" / relative
        if destination.resolve() != (SOURCE_ROOT / relative).resolve():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((SOURCE_ROOT / relative).read_bytes())


if __name__ == "__main__":
    generate(SOURCE_ROOT.parent)
    print(json.dumps(ANCHORS, ensure_ascii=False, sort_keys=True))
