"""Delta WL7 từ nguồn đã nạp và kết quả; chỉ đo, không cấp quyền Apply."""

from __future__ import annotations

from collections import Counter

from pbip_assistant.errors import InputError
from .assistant_execution import MAX_STEPS, _OPERATIONS
from .assistant_findings import _select
from .assistant_preview import (
    RESULT_COLUMNS, _matrix, _supported_recipe, _validated_raw, _validated_spec,
)


# Lineage là nghĩa của operation đóng trong Spec, không chọn theo scenario hoặc tên file.
# Thứ tự catalog cố định chỉ phục vụ hiển thị; bỏ operation sẽ bỏ đúng lineage của nó.
_LINEAGE = (
    ("normalize_sign", "DebitCredit→amountSigned"),
    ("map_account", "AccountCode→accountMapped"),
    ("lookup_fx", "Amount→amountVnd"),
    ("line_revenue_net_returns", "Quantity×UnitPrice×DiscountPct→revenue"),
    ("resolve_territory", "TerritoryID→region"),
    ("join_customers", "CustomerID→customerBucket"),
)


def _invalid(message: str) -> InputError:
    return InputError("AF_DELTA_INVALID", "delta", message)


def _blank(value) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def null_profile(columns: list[str], rows: list) -> dict[str, int]:
    """Đếm ô null/rỗng/whitespace; số 0 không phải ô rỗng."""
    _matrix(columns, rows)
    return {name: sum(_blank(row[index]) for row in rows)
            for index, name in enumerate(columns)}


def changed_columns(spec) -> list[str]:
    """Đọc lineage operation khai báo; helper này không xác nhận một Spec đã freeze."""
    if (not isinstance(spec, dict) or not isinstance(spec.get("steps"), list)
            or len(spec["steps"]) > MAX_STEPS):
        raise _invalid("Cần danh sách step khai báo trong giới hạn hỗ trợ.")
    operations = set()
    for step in spec["steps"]:
        params = step.get("params") if isinstance(step, dict) else None
        operation = params.get("operation") if isinstance(params, dict) else None
        if not isinstance(operation, str) or operation not in _OPERATIONS:
            raise _invalid("Step cần operation thuộc catalog đã hỗ trợ.")
        operations.add(operation)
    return [lineage for operation, lineage in _LINEAGE if operation in operations]


def _duplicates(rows, indexes=None) -> int:
    keys = (tuple(row) if indexes is None else tuple(row[index] for index in indexes)
            for row in rows)
    return sum(count - 1 for count in Counter(keys).values())


def compute_delta(raw_tables, result, spec, *, scenario) -> dict:
    """Đo raw/result hiện tại; kết quả lỗi đối soát vẫn có delta diagnostic thật."""
    if not isinstance(scenario, str) or scenario not in RESULT_COLUMNS:
        raise _invalid("Scenario delta không được hỗ trợ.")
    _validated_spec(spec)
    _supported_recipe(spec, scenario)
    tables = _validated_raw(raw_tables)
    if (not isinstance(result, dict) or set(result) != {"columns", "rows"}
            or result["columns"] != RESULT_COLUMNS[scenario]):
        raise _invalid("Kết quả không đúng cột của recipe cần đo delta.")
    output_nulls = null_profile(result["columns"], result["rows"])
    if scenario == "tp-fin":
        primary = _select(tables, {"DocNo", "LineNo", "PostingDate", "DebitCredit", "Amount",
                                   "PartnerEntity", "AccountCode", "CostCenter", "EntityCode", "Ledger"})
        input_nulls = null_profile(primary["header"], primary["rows"])
        nulls_before = {"PartnerEntity": input_nulls["PartnerEntity"]}
        # PartnerEntity không còn trong output: pnlLine là coverage của bucket đã map.
        nulls_after = {"PartnerEntity": output_nulls["pnlLine"]}
        grain = ("pnlLine", "accountCode", "costCenter", "entityCode")
    else:
        primary = _select(tables, {"OrderID", "ProductID", "Quantity", "UnitPrice", "DiscountPct"})
        orders = _select(tables, {"OrderID", "OrderDate", "CustomerID", "TerritoryID", "Status"})
        input_nulls = null_profile(orders["header"], orders["rows"])
        nulls_before = {name: input_nulls[name] for name in ("CustomerID", "TerritoryID")}
        # Hai chỉ số là coverage cột nguồn sau mapping/group, không phải cột raw được giữ lại.
        nulls_after = {"CustomerID": output_nulls["customerCount"],
                       "TerritoryID": output_nulls["region"]}
        grain = ("region",)
    indexes = [result["columns"].index(name) for name in grain]
    return {"rowsIn": len(primary["rows"]), "rowsOut": len(result["rows"]),
            "nullsBefore": nulls_before, "nullsAfter": nulls_after,
            "duplicatesBefore": _duplicates(primary["rows"]),
            "duplicatesAfter": _duplicates(result["rows"], indexes),
            "changedColumns": changed_columns(spec)}
