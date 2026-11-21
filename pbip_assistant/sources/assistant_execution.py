"""Compile kế hoạch WL4 đóng, thuần bộ nhớ; không thực thi nguồn hoặc workbook."""

from __future__ import annotations

from copy import deepcopy
import re

from pbip_assistant.errors import InputError
from .assistant_brief import brief_hash
from .assistant_pack import validate_pack


MAX_STEPS = 128
_KINDS = frozenset({"recipe", "lookup", "join", "group", "calc", "filter", "sort", "output"})
_FIELDS = frozenset({"id", "kind", "label", "decisionRefs", "inputs", "params", "output", "dependsOn", "status", "guard"})
_SOURCES = frozenset({"ledger", "accounts", "cost_centers", "entities", "fx_rates", "budget",
                      "orders", "order_items", "customers", "products", "territories"})
_PARAMS = frozenset({"operation", "tableId", "sourceAlias", "columns", "formulaId", "chosenOptionId",
                     "chosenOptions", "policyModes", "rightGrain"})

# Closed recipes describe supported operations; they never contain source IDs or values.
_FIN = (
    ("recipe", "load", (), "ledger", None),
    ("recipe", "dedupe", ("SP-4",), None, None),
    ("calc", "normalize_sign", ("SP-4",), None, None),
    ("lookup", "map_account", ("SP-5",), "accounts", None),
    ("join", "join_coa", (), "accounts", None),
    ("join", "join_cost_center", ("SP-6",), "cost_centers", None),
    ("join", "join_entity", (), "entities", None),
    ("lookup", "lookup_fx", ("SP-2", "SP-8"), "fx_rates", None),
    ("recipe", "retain_key_collision", ("SP-9",), None, None),
    ("recipe", "separate_intercompany", ("SP-3",), None, None),
    ("group", "group", (), None, "grain"),
    ("join", "join_budget", (), "budget", None),
    ("calc", "variance_bridge", ("SP-1",), None, None),
    ("output", "output", (), None, None),
)
_SALES = (
    ("recipe", "folder_append", (), "orders", None),
    ("join", "join_order_items", (), "order_items", ("OrderID",)),
    ("join", "join_customers", ("SP-3",), "customers", ("CustomerID",)),
    ("join", "join_products", (), "products", ("ProductID",)),
    ("lookup", "resolve_territory", ("SP-4",), "territories", ("TerritoryID",)),
    ("filter", "exclude_cancelled", ("SP-1",), None, None),
    ("calc", "line_revenue_net_returns", ("SP-2",), None, None),
    ("group", "group_region", (), None, "grain"),
    ("sort", "sort_region", (), None, "grain"),
    ("output", "values_only", (), None, None),
)
_MODES = {
    "fin-pl-v1": {
        "SP-1": {"A": "include_rebate_in_net", "B": "present_rebate_below_gross_profit"},
        "SP-2": {"A": "separate_fx_from_op", "B": "reallocate_fx_into_op"},
        "SP-3": {"A": "exclude_both_sides_keep_reconciliation", "B": "keep_intercompany_flagged"},
        "SP-4": {"A": "dedupe_exact_and_normalize_sign", "B": "keep_duplicates_and_normalize_sign"},
        "SP-5": {"A": "prefix_mapping", "B": "unmapped_bucket"},
        "SP-6": {"A": "keep_flagged_cost_center", "B": "unallocated_cost_center_bucket"},
        "SP-8": {"A": "continue_unused_rate_warnings", "B": "require_complete_rate_catalog"},
        "SP-9": {"A": "retain_flagged_key_collision", "B": "drop_smaller_collision_amount"},
    },
    "generic": {
        "SP-1": {"A": "exclude_cancelled", "B": "include_cancelled_flagged"},
        "SP-2": {"A": "net_negative_returns", "B": "present_returns_separately"},
        "SP-3": {"A": "keep_unknown_customer_bucket", "B": "drop_orphan_customer"},
        "SP-4": {"A": "customer_territory_fallback", "B": "unknown_territory_bucket"},
    },
}
_LABELS = {
    "load": "Nạp nguồn chỉ đọc", "dedupe": "Áp dụng quy tắc dòng trùng",
    "normalize_sign": "Chuẩn hoá dấu theo quy tắc nguồn", "map_account": "Xử lý ánh xạ tài khoản",
    "join_coa": "Nối danh mục tài khoản", "join_cost_center": "Nối danh mục cost center",
    "join_entity": "Nối danh mục pháp nhân", "lookup_fx": "Tra tỷ giá và kiểm điều kiện thiếu nguồn",
    "retain_key_collision": "Xử lý xung đột khóa", "separate_intercompany": "Xử lý giao dịch nội bộ",
    "group": "Gộp dữ liệu về grain báo cáo", "join_budget": "Nối ngân sách cùng grain đã gộp",
    "variance_bridge": "Tính chỉ tiêu và cầu nối theo lựa chọn", "output": "Khai báo đầu ra có nhãn",
    "folder_append": "Nạp các file theo thứ tự tên", "join_order_items": "Nối các dòng chi tiết đơn",
    "join_customers": "Nối danh mục khách hàng", "join_products": "Nối danh mục sản phẩm",
    "resolve_territory": "Xác định khu vực theo lựa chọn", "exclude_cancelled": "Xử lý đơn huỷ",
    "line_revenue_net_returns": "Tính doanh thu và xử lý trả hàng", "group_region": "Gộp doanh thu theo khu vực",
    "sort_region": "Sắp xếp đầu ra tất định", "values_only": "Khai báo đầu ra chỉ giá trị",
}
_OPERATIONS = frozenset(_LABELS)
_OPERATION_KINDS = {operation: kind for kind, operation, *_ in _FIN + _SALES}
_OPERATION_SOURCES = {operation: source for _, operation, _, source, _ in _FIN + _SALES}
_OPERATION_POLICIES = {operation: refs for _, operation, refs, *_ in _FIN + _SALES}
_OPERATION_FAMILIES = {operation: family for family, recipe in (("fin-pl-v1", _FIN), ("generic", _SALES))
                       for _, operation, *_ in recipe}


def _invalid(detail: str, code: str = "AF_EXECUTION_INVALID") -> InputError:
    return InputError(code, "execution.steps", detail)


def _strings(value, *, unique: bool = True) -> bool:
    return (isinstance(value, list) and all(isinstance(x, str) and x for x in value)
            and (not unique or len(value) == len(set(value))))


def _budget(step) -> bool:
    if not isinstance(step, dict) or step.get("kind") != "join":
        return False
    params = step.get("params")
    return isinstance(params, dict) and (params.get("operation") == "join_budget" or
        params.get("sourceAlias") == "budget" or "source:budget" in step.get("inputs", []))


def _fan_out_guard(steps: list[dict]) -> None:
    for index, step in enumerate(steps):
        if not _budget(step):
            continue
        candidates = [group for group in steps[:index] if isinstance(group, dict) and
                      group.get("kind") == "group" and group.get("id") in step.get("dependsOn", [])
                      and group.get("output") in step.get("inputs", [])]
        if not candidates:
            raise _invalid("Chưa gộp dữ liệu trước khi nối ngân sách; nguy cơ nhân dòng.", "AF_FANOUT_RISK")
        expected = step["params"].get("rightGrain")
        if expected is not None and not any(group.get("params", {}).get("columns") == expected for group in candidates):
            raise _invalid("Grain ngân sách không khớp đầu vào đã gộp.", "AF_FANOUT_RISK")


def _catalog(steps: list[dict]) -> tuple[dict, dict]:
    if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS:
        raise _invalid("Danh sách step rỗng, sai kiểu hoặc vượt giới hạn.")
    by_id, by_output = {}, {}
    for step in steps:
        if not isinstance(step, dict) or set(step) != _FIELDS:
            raise _invalid("Step thiếu field hoặc có field ngoài hợp đồng.")
        if (not isinstance(step["id"], str) or not step["id"] or step["id"] in by_id or
                not isinstance(step["output"], str) or not step["output"] or step["output"] in by_output):
            raise _invalid("Step id và output phải duy nhất, không rỗng.")
        if (not isinstance(step["kind"], str) or step["kind"] not in _KINDS or
                not isinstance(step["label"], str) or not step["label"]):
            raise _invalid("Kind hoặc nhãn step không hợp lệ.")
        if any(not _strings(step[field]) for field in ("decisionRefs", "dependsOn", "inputs")):
            raise _invalid("Ref, dependency và input phải là danh sách identifier duy nhất.")
        if (not isinstance(step["status"], str) or step["status"] not in {"ok", "pending", "blocked"} or
                (step["guard"] is not None and step["guard"] != "AF_FANOUT_RISK")):
            raise _invalid("Status hoặc guard step không hợp lệ.")
        if step["guard"] is not None and step["status"] != "blocked":
            raise _invalid("Guard chỉ hợp lệ khi step bị chặn.")
        params = step["params"]
        if (not isinstance(params, dict) or set(params) - _PARAMS or
                not isinstance(params.get("operation"), str) or params["operation"] not in _OPERATIONS):
            raise _invalid("Operation hoặc params step không được hỗ trợ.")
        operation = params["operation"]
        if step["kind"] != _OPERATION_KINDS[operation]:
            raise _invalid("Kind không khớp operation của recipe đóng.")
        if step["decisionRefs"] != list(_OPERATION_POLICIES[operation]):
            raise _invalid("Decision refs không khớp operation của recipe đóng.")
        source = params.get("sourceAlias")
        if source is not None and (not isinstance(source, str) or source not in _SOURCES):
            raise _invalid("Alias nguồn không được hỗ trợ.")
        table_id = params.get("tableId")
        if table_id is not None and (not isinstance(table_id, str) or re.fullmatch(r"tbl_[a-f0-9]{12}", table_id) is None):
            raise _invalid("Table id phải là identifier đã khai báo hoặc null.")
        expected_source = _OPERATION_SOURCES[operation]
        if source != expected_source and not (source is None and table_id is not None):
            raise _invalid("Alias nguồn không khớp operation của recipe đóng.")
        for field in ("columns", "rightGrain"):
            if params.get(field) is not None and (not _strings(params[field]) or not params[field]):
                raise _invalid("Danh sách cột hoặc grain không hợp lệ.")
        formula_id = params.get("formulaId")
        if formula_id is not None and (not isinstance(formula_id, str) or re.fullmatch(r"fm_[a-z][a-z0-9_]*", formula_id) is None):
            raise _invalid("Formula id step không hợp lệ.")
        choices = params.get("chosenOptions")
        if choices is not None:
            if (not isinstance(choices, dict) or set(choices) != set(step["decisionRefs"]) or
                    any(value is not None and (not isinstance(value, str) or value not in {"A", "B"})
                        for value in choices.values())):
                raise _invalid("Mỗi decision ref phải có lựa chọn được bind riêng.")
            nonnull = set(choices.values())
            scalar = next(iter(nonnull)) if len(nonnull) == 1 else None
            if params.get("chosenOptionId") != scalar:
                raise _invalid("Lựa chọn scalar không khớp map quyết định.")
        modes = params.get("policyModes")
        if modes is not None and (not isinstance(modes, dict) or set(modes) != set(step["decisionRefs"]) or
                                  any(not isinstance(value, str) or not value for value in modes.values())):
            raise _invalid("Policy mode phải bind đúng decision ref.")
        if choices is not None and modes is not None:
            supported = _MODES[_OPERATION_FAMILIES[operation]]
            if any(choices[identifier] is None or mode != supported[identifier][choices[identifier]]
                   for identifier, mode in modes.items()):
                raise _invalid("Policy mode không khớp lựa chọn trong catalog đóng.")
        by_id[step["id"]] = step
        by_output[step["output"]] = step["id"]
    return by_id, by_output


def _parents(step: dict, by_id: dict, by_output: dict) -> set[str]:
    parents = set(step["dependsOn"])
    if any(parent not in by_id or parent == step["id"] for parent in parents):
        raise _invalid("Dependency không tồn tại hoặc tự tham chiếu.")
    for source in step["inputs"]:
        if source in by_output:
            producer = by_output[source]
            if producer == step["id"]:
                raise _invalid("Step không được đọc output của chính nó.")
            if producer not in parents:
                raise _invalid("Input output phải khai báo dependency tương ứng.")
        elif source.startswith("source:"):
            if source[7:] not in _SOURCES or source[7:] != step["params"].get("sourceAlias"):
                raise _invalid("Input nguồn không khớp alias được khai báo.")
        elif source != step["params"].get("tableId"):
            raise _invalid("Input không tồn tại trong graph hoặc nguồn được khai báo.")
    return parents


def verify_graph(steps) -> None:
    """Kiểm chính thứ tự nhận được; không sửa thứ tự hoặc mutate graph lỗi."""
    if not isinstance(steps, list):
        raise _invalid("Graph phải là danh sách step.")
    by_id, by_output = _catalog(steps)
    _fan_out_guard(steps)
    seen, outputs = set(), set()
    for index, step in enumerate(steps):
        parents = _parents(step, by_id, by_output)
        if not parents <= seen:
            raise _invalid("Dependency trỏ về step sau hoặc graph có cycle.")
        if index == 0:
            if step["kind"] != "recipe" or parents:
                raise _invalid("Graph phải bắt đầu bằng recipe nguồn không có dependency.")
        elif not any(source in outputs for source in step["inputs"]):
            raise _invalid("Step mồ côi: cần input từ output của step trước.")
        if any(source in by_output and source not in outputs for source in step["inputs"]):
            raise _invalid("Input trỏ tới output chưa có.")
        seen.add(step["id"])
        outputs.add(step["output"])


def order_steps(steps) -> list[dict]:
    """Topological order ổn định theo id; graph thiếu ref/cycle không được sửa giả."""
    by_id, by_output = _catalog(steps)
    dependencies = {identifier: _parents(step, by_id, by_output) for identifier, step in by_id.items()}
    result, emitted = [], set()
    while len(result) < len(steps):
        ready = sorted(identifier for identifier, parents in dependencies.items()
                       if identifier not in emitted and parents <= emitted)
        if not ready:
            raise _invalid("Dependency graph có cycle.")
        for identifier in ready:
            result.append(deepcopy(by_id[identifier]))
            emitted.add(identifier)
    verify_graph(result)
    return result


def compile_steps(brief, decisions, pack) -> list[dict]:
    """Ghép recipe đóng với lựa chọn tường minh; không tự chọn hoặc chạy dữ liệu."""
    from .assistant_decisions import freeze_blocked, validate_decisions

    if not isinstance(brief, dict) or brief.get("briefHash") != brief_hash(brief):
        raise _invalid("Brief không hợp lệ hoặc đã đổi.")
    validate_pack(pack)
    family = pack["id"]
    if family not in _MODES:
        raise _invalid("Chưa hỗ trợ recipe của pack này.")
    policy_ids = {policy["subProblemId"] for policy in pack["policies"]}
    problems = {problem["id"]: problem for problem in brief["subProblems"]}
    if set(problems) != policy_ids:
        raise _invalid("Brief và pack không cùng tập policy.")
    if freeze_blocked(brief, decisions)["blocked"]:
        raise _invalid("Policy chưa chốt; không tự chọn phương án để compile.", "AF_MISSING_DATA")
    validate_decisions(brief, decisions)
    choices = {entry["subProblemId"]: entry["optionId"] for entry in decisions["decisions"]}
    if set(choices) != set(_MODES[family]):
        raise _invalid("Recipe cần lựa chọn thực thi cho đúng policy; acknowledgement không thay lựa chọn.", "AF_MISSING_DATA")
    for identifier, option in choices.items():
        if option not in _MODES[family][identifier] or option not in {item["id"] for item in problems[identifier]["options"]}:
            raise _invalid("Phương án chưa có recipe thực thi được hỗ trợ.")
    grain = brief["outputContract"]["grain"]
    if not _strings(grain) or not grain or not set(grain) <= set(pack["outputContract"]["grain"]):
        raise _invalid("Grain không thuộc output contract của pack.")
    definitions = _FIN if family == "fin-pl-v1" else _SALES
    result = []
    for index, (kind, operation, refs, source, columns) in enumerate(definitions, 1):
        selected = {identifier: choices[identifier] for identifier in refs}
        values = set(selected.values())
        scalar = next(iter(values)) if len(values) == 1 else None
        params = {"operation": operation, "tableId": None, "sourceAlias": source,
                  "columns": list(grain) if columns == "grain" else list(columns) if columns else None,
                  "formulaId": None, "chosenOptionId": scalar, "chosenOptions": selected,
                  "policyModes": {identifier: _MODES[family][identifier][option] for identifier, option in selected.items()},
                  "rightGrain": list(grain) if operation == "join_budget" else None}
        previous = f"q_{index - 1:02d}"
        inputs = [] if index == 1 else [previous] + (["source:" + source] if source else [])
        label = _LABELS[operation]
        if refs:
            label = "; ".join(next(option["label"] for option in problems[identifier]["options"]
                                   if option["id"] == selected[identifier]) for identifier in refs)
        result.append({"id": f"st_{index:02d}", "kind": kind, "label": label,
                       "decisionRefs": list(refs), "inputs": inputs, "params": params,
                       "output": f"q_{index:02d}", "dependsOn": [] if index == 1 else [f"st_{index - 1:02d}"],
                       "status": "ok", "guard": None})
    verify_graph(result)
    return result
