"""Deterministic W-21 planner for the synthetic Excel connector fixture.

This is deliberately not a general AI planner.  It validates the W-20 fixture
schema and creates one typed, reproducible plan so the Office.js -> copy ->
Excel calculation path can be tested safely.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from pbip_assistant.errors import InputError


MAX_PROMPT_CHARS = 4_000
MAX_PREVIEW_ROWS = 20
MAX_TABLES = 50
MAX_COLUMNS = 200


@dataclass(frozen=True)
class FormulaOperation:
    id: str
    target_table: str
    target_column: str
    formula: str
    reason: str
    number_format: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "excel.formula_column.add",
            "target": f"{self.target_table}[{self.target_column}]",
            "targetTable": self.target_table,
            "targetColumn": self.target_column,
            "formula": self.formula,
            "reason": self.reason,
            "risk": "low",
            "dependsOn": _dependencies(self.id),
            **({"numberFormat": self.number_format} if self.number_format else {}),
        }


OPERATIONS = (
    FormulaOperation(
        "op-net-revenue",
        "SalesTable",
        "Net Revenue",
        "=[@[Gross Revenue]]-[@[Discount Value]]-[@[Return Value]]",
        "Doanh thu ròng sau giảm giá và hàng trả.",
        "#,##0.00",
    ),
    FormulaOperation(
        "op-return-rate",
        "SalesTable",
        "Return Rate",
        "=IFERROR([@[Total Return Qty]]/[@[Total Sold Qty]],0)",
        "Tỷ lệ số lượng trả; mẫu số 0 trả về 0.",
        "0.00%",
    ),
    FormulaOperation(
        "op-commission",
        "SalesTable",
        "Commission Value",
        "=[@[Net Revenue]]*XLOOKUP([@[Net Revenue]],CommissionTable[Min Net Revenue],CommissionTable[Commission Rate],0,-1)",
        "Áp tỷ lệ hoa hồng theo ngưỡng doanh thu ròng gần nhất nhỏ hơn hoặc bằng.",
        "#,##0.00",
    ),
    FormulaOperation(
        "op-sales-rank",
        "SalesTable",
        "Sales Rank",
        '=LET(p,PERCENTRANK.INC(SalesTable[Net Revenue],[@[Net Revenue]]),IFS(p>=0.9,"Top 10%",p>=0.8,"Top 20%",TRUE,"Bottom"))',
        "Phân nhóm percentile dựa trên Net Revenue.",
    ),
)

OPERATION_BY_ID = {operation.id: operation for operation in OPERATIONS}

REQUIRED_TABLES = {
    "SalesTable": (
        "SaleID",
        "EmployeeID",
        "Region",
        "SaleDate",
        "Gross Revenue",
        "Discount Value",
        "Return Value",
        "Total Sold Qty",
        "Total Return Qty",
    ),
    "CommissionTable": ("Min Net Revenue", "Commission Rate"),
}


def _dependencies(operation_id: str) -> list[str]:
    if operation_id in {"op-commission", "op-sales-rank"}:
        return ["op-net-revenue"]
    return []


def _canonical_hash(value: Any, prefix: str) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:24]}"


def _validated_workbook(workbook: Any) -> dict[str, Any]:
    if not isinstance(workbook, dict):
        raise InputError("INVALID_REQUEST", "workbook", "workbook must be an object")
    name = workbook.get("name")
    url = workbook.get("url")
    active_sheet = workbook.get("activeSheet")
    tables = workbook.get("tables")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise InputError("INVALID_WORKBOOK", "workbook.name", "Workbook needs a plain file name")
    if not isinstance(url, str):
        raise InputError("INVALID_WORKBOOK", "workbook.url", "Workbook URL must be text")
    if not isinstance(active_sheet, str) or not active_sheet:
        raise InputError("INVALID_WORKBOOK", "workbook.activeSheet", "Active sheet is missing")
    if not isinstance(tables, list) or len(tables) > MAX_TABLES:
        raise InputError("INVALID_WORKBOOK", "workbook.tables", f"At most {MAX_TABLES} tables are accepted")

    clean_tables: list[dict[str, Any]] = []
    for index, table in enumerate(tables):
        path = f"workbook.tables[{index}]"
        if not isinstance(table, dict):
            raise InputError("INVALID_WORKBOOK", path, "Table metadata must be an object")
        sheet = table.get("sheet")
        table_name = table.get("name")
        headers = table.get("headers")
        rows = table.get("rows", [])
        if not isinstance(sheet, str) or not sheet or not isinstance(table_name, str) or not table_name:
            raise InputError("INVALID_WORKBOOK", path, "Table needs sheet and name")
        if (
            not isinstance(headers, list)
            or len(headers) > MAX_COLUMNS
            or not all(isinstance(item, str) and item for item in headers)
        ):
            raise InputError("INVALID_WORKBOOK", f"{path}.headers", "Headers are invalid or exceed limit")
        if not isinstance(rows, list) or len(rows) > MAX_PREVIEW_ROWS:
            raise InputError("INVALID_WORKBOOK", f"{path}.rows", f"Preview is limited to {MAX_PREVIEW_ROWS} rows")
        clean_rows: list[list[Any]] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(headers):
                raise InputError(
                    "INVALID_WORKBOOK",
                    f"{path}.rows[{row_index}]",
                    "Preview row width must match headers",
                )
            clean_rows.append(row)
        clean_tables.append({"sheet": sheet, "name": table_name, "headers": headers, "rows": clean_rows})
    return {"name": name, "url": url, "activeSheet": active_sheet, "tables": clean_tables}


def local_source_path(workbook: dict[str, Any]) -> Path:
    """Return a saved local .xlsx path from an Office document URL."""

    url = workbook.get("url", "")
    if not url:
        raise InputError("WORKBOOK_UNSAVED", "workbook.url", "Save the workbook as a local .xlsx file, then refresh")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "file" or parsed.netloc not in {"", "localhost"}:
        raise InputError(
            "REMOTE_WORKBOOK_UNSUPPORTED",
            "workbook.url",
            "W-21 supports only a saved local workbook; download OneDrive/SharePoint files first",
        )
    raw_path = unquote(parsed.path)
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    source = Path(raw_path)
    if source.suffix.lower() != ".xlsx" or source.name.casefold() != str(workbook.get("name", "")).casefold():
        raise InputError("INVALID_WORKBOOK", "workbook.url", "URL and workbook name must identify the same .xlsx file")
    return source


def _table_map(workbook: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for table in workbook["tables"]:
        name = table["name"]
        if name in result:
            raise InputError("SCHEMA_MISMATCH", name, "Duplicate table name is not supported")
        result[name] = table
    return result


def _schema_blockers(workbook: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    tables = _table_map(workbook)
    for table_name, required_headers in REQUIRED_TABLES.items():
        table = tables.get(table_name)
        if table is None:
            blockers.append({
                "code": "SCHEMA_MISMATCH",
                "target": table_name,
                "reason": f"Không tìm thấy table {table_name}.",
                "remedy": "Mở fixture W-20 hoặc tạo đúng Excel table rồi phân tích lại.",
            })
            continue
        missing = [header for header in required_headers if header not in table["headers"]]
        if missing:
            blockers.append({
                "code": "SCHEMA_MISMATCH",
                "target": table_name,
                "reason": f"Thiếu cột: {', '.join(missing)}.",
                "remedy": "Bổ sung/đổi tên cột theo fixture rồi phân tích lại.",
            })
    return blockers


def _number(value: Any, target: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError("PREVIEW_TYPE", target, "Fixture preview expects numeric input")
    return float(value)


def _percent_rank_inc(values: list[float], value: float) -> float:
    ordered = sorted(values)
    if len(ordered) <= 1:
        return 1.0
    if value <= ordered[0]:
        return 0.0
    if value >= ordered[-1]:
        return 1.0
    for index in range(1, len(ordered)):
        lower, upper = ordered[index - 1], ordered[index]
        if value <= upper:
            fraction = 0.0 if upper == lower else (value - lower) / (upper - lower)
            return ((index - 1) + fraction) / (len(ordered) - 1)
    return 1.0


def _simulated_preview(workbook: dict[str, Any]) -> dict[str, Any]:
    tables = _table_map(workbook)
    sales = tables["SalesTable"]
    commission = tables["CommissionTable"]
    sales_rows = [dict(zip(sales["headers"], row, strict=True)) for row in sales["rows"]]
    commission_rows = [dict(zip(commission["headers"], row, strict=True)) for row in commission["rows"]]
    net_values = [
        _number(row["Gross Revenue"], "Gross Revenue")
        - _number(row["Discount Value"], "Discount Value")
        - _number(row["Return Value"], "Return Value")
        for row in sales_rows
    ]
    thresholds = sorted(
        (
            _number(row["Min Net Revenue"], "Min Net Revenue"),
            _number(row["Commission Rate"], "Commission Rate"),
        )
        for row in commission_rows
    )
    after: list[dict[str, Any]] = []
    for row, net_revenue in zip(sales_rows, net_values, strict=True):
        sold = _number(row["Total Sold Qty"], "Total Sold Qty")
        returned = _number(row["Total Return Qty"], "Total Return Qty")
        applicable = [rate for minimum, rate in thresholds if minimum <= net_revenue]
        commission_rate = applicable[-1] if applicable else 0.0
        percentile = _percent_rank_inc(net_values, net_revenue)
        rank = "Top 10%" if percentile >= 0.9 else "Top 20%" if percentile >= 0.8 else "Bottom"
        after.append({
            "SaleID": row.get("SaleID"),
            "Net Revenue": round(net_revenue, 10),
            "Return Rate": round(returned / sold, 10) if sold else 0,
            "Commission Value": round(net_revenue * commission_rate, 10),
            "Sales Rank": rank,
        })
    return {
        "label": "Simulated preview — chưa ghi Excel",
        "beforeColumns": list(sales["headers"]),
        "beforeRows": sales["rows"],
        "afterColumns": ["SaleID", "Net Revenue", "Return Rate", "Commission Value", "Sales Rank"],
        "afterRows": [[row[column] for column in ("SaleID", "Net Revenue", "Return Rate", "Commission Value", "Sales Rank")] for row in after],
    }


def create_fixture_plan(prompt: Any, workbook: Any) -> dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip():
        raise InputError("PROMPT_REQUIRED", "prompt", "Nhập yêu cầu xử lý trước khi phân tích")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise InputError("PROMPT_LIMIT", "prompt", f"Prompt vượt quá {MAX_PROMPT_CHARS} ký tự")
    clean_workbook = _validated_workbook(workbook)
    blockers = _schema_blockers(clean_workbook)
    try:
        local_source_path(clean_workbook)
    except InputError as exc:
        blockers.append({
            "code": exc.code,
            "target": exc.path,
            "reason": exc.detail,
            "remedy": "Lưu workbook thành file .xlsx local rồi bấm refresh.",
        })

    snapshot_basis = {"workbook": clean_workbook}
    snapshot_id = _canonical_hash(snapshot_basis, "snap")
    operation_payload = [operation.public() for operation in OPERATIONS]
    revision_basis = {"snapshotId": snapshot_id, "prompt": prompt, "operations": operation_payload}
    revision_id = _canonical_hash(revision_basis, "plan")
    preview = None
    if not blockers:
        try:
            preview = _simulated_preview(clean_workbook)
        except (InputError, KeyError) as exc:
            if isinstance(exc, InputError):
                code, target, reason = exc.code, exc.path, exc.detail
            else:
                code, target, reason = "SCHEMA_MISMATCH", str(exc), "Preview input is incomplete"
            blockers.append({
                "code": code,
                "target": target,
                "reason": reason,
                "remedy": "Kiểm tra kiểu dữ liệu fixture rồi phân tích lại.",
            })

    return {
        "snapshotId": snapshot_id,
        "planRevisionId": revision_id,
        "status": "blocked" if blockers else "review_ready",
        "scope": "W-21 deterministic fixture planner",
        "operations": operation_payload,
        "preview": preview,
        "warnings": [
            "Planner W-21 chỉ hỗ trợ schema fixture SalesTable/CommissionTable.",
            "Preview là mô phỏng; chưa phải kết quả Excel runtime.",
        ],
        "hardBlockers": blockers,
    }


def validate_current_plan(
    *,
    prompt: Any,
    workbook: Any,
    snapshot_id: Any,
    plan_revision_id: Any,
    operation_ids: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = create_fixture_plan(prompt, workbook)
    if plan["status"] != "review_ready":
        first = plan["hardBlockers"][0]
        raise InputError(first["code"], first["target"], first["reason"])
    if snapshot_id != plan["snapshotId"] or plan_revision_id != plan["planRevisionId"]:
        raise InputError("PLAN_STALE", "planRevisionId", "Workbook or prompt changed; analyze and approve a new revision")
    expected = [operation.id for operation in OPERATIONS]
    if not isinstance(operation_ids, list) or operation_ids != expected:
        raise InputError("APPROVAL_SCOPE", "operationIds", "W-21 requires explicit approval of the four ordered fixture operations")
    return plan, _validated_workbook(workbook)


def helper_operations() -> list[dict[str, Any]]:
    """Return the fixed allowlisted payload used by the trusted helper."""

    return [operation.public() for operation in OPERATIONS]

