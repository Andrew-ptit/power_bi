"""Đọc DomainPack đóng băng; chỉ cung cấp câu chữ và tham chiếu công thức."""

from __future__ import annotations

import json
import math
import re

from pbip_assistant.core.errors import InputError
from pbip_assistant.core.resources import package_path, schema_path


_PACK_FILES = {"fin-pl-v1": "fin_pl_v1.json", "generic": "generic.json"}
_SCHEMA_NAME = "assistant_domain_pack.schema.json"
_MAX_RESOURCE_BYTES = 1_048_576
_MAX_NODES = 20_000
_KEYWORDS = frozenset({
    "$schema", "$defs", "$ref", "type", "properties", "required",
    "additionalProperties", "items", "enum", "const", "pattern",
    "minLength", "maxLength", "minItems", "maxItems", "uniqueItems",
})
_MONEY_KEY = re.compile(r"amount|vnd|usd|value|total|delta", re.IGNORECASE)
_MONEY_UNIT = re.compile(
    r"(?i)(?:[0-9][0-9.,_ ]*)\s*(?:VND|USD|EUR|đồng|triệu|tỷ|nghìn)\b|"
    r"(?:VND|USD|EUR)\s*[:=]?\s*[0-9]",
)
_MONEY_CONTEXT = re.compile(
    r"(?i)(?:tổng|doanh\s*thu|lợi\s*nhuận|net\s*revenue|gross\s*profit|total)"
    r"[^\n0-9]{0,40}[0-9][0-9.,_ ]{3,}",
)


def _invalid(detail: str, path: str = "domainPack") -> InputError:
    return InputError("AF_PACK_INVALID", path, detail)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _constant_error(value: str) -> None:
    raise ValueError("nonfinite JSON number")


def _resource_json(path) -> dict:
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_RESOURCE_BYTES + 1)
        if len(payload) > _MAX_RESOURCE_BYTES:
            raise ValueError("resource exceeds bound")
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
                            parse_constant=_constant_error)
        if not isinstance(result, dict):
            raise ValueError("resource must be an object")
        return result
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise _invalid("Không đọc được tài nguyên DomainPack hợp lệ.") from exc


def _resolve(reference: str, root: dict):
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        raise _invalid("Schema DomainPack chỉ được dùng tham chiếu nội bộ.")
    current = root
    try:
        for part in reference[2:].split("/"):
            current = current[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError) as exc:
        raise _invalid("Tham chiếu schema DomainPack không tồn tại.") from exc
    return current


def _schema_preflight(schema: dict) -> None:
    seen = set()
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise _invalid("Schema DomainPack phải dùng draft đã được hỗ trợ.")

    def visit(rule) -> None:
        if not isinstance(rule, dict):
            raise _invalid("Schema DomainPack phải là object.")
        if id(rule) in seen:
            return
        seen.add(id(rule))
        if set(rule) - _KEYWORDS:
            raise _invalid("Schema DomainPack có keyword chưa được hỗ trợ.")
        expected = rule.get("type")
        if expected is not None:
            kinds = expected if isinstance(expected, list) else [expected]
            if not kinds or any(kind not in {"object", "array", "string", "boolean", "null"}
                                for kind in kinds):
                raise _invalid("Schema DomainPack dùng kiểu chưa được hỗ trợ.")
        if "pattern" in rule:
            try:
                re.compile(rule["pattern"])
            except (TypeError, re.error) as exc:
                raise _invalid("Pattern schema DomainPack không hợp lệ.") from exc
        if "$ref" in rule:
            visit(_resolve(rule["$ref"], schema))
        for field in ("properties", "$defs"):
            children = rule.get(field, {})
            if not isinstance(children, dict):
                raise _invalid("Schema DomainPack có mapping không hợp lệ.")
            for child in children.values():
                visit(child)
        if "items" in rule:
            visit(rule["items"])
        if rule.get("type") == "object":
            properties = rule.get("properties", {})
            if (rule.get("additionalProperties") is not False or
                    set(rule.get("required", [])) != set(properties)):
                raise _invalid("Object schema DomainPack phải đóng và yêu cầu đủ field.")

    visit(schema)


def _validate_schema(value, schema: dict) -> None:
    _schema_preflight(schema)
    count = 0

    def check(instance, rule: dict, depth: int = 0) -> None:
        nonlocal count
        count += 1
        if count > _MAX_NODES or depth > 32:
            raise _invalid("DomainPack vượt giới hạn cấu trúc.")
        if "$ref" in rule:
            check(instance, _resolve(rule["$ref"], schema), depth + 1)
        expected = rule.get("type")
        if expected is not None:
            kinds = expected if isinstance(expected, list) else [expected]
            tests = {
                "object": isinstance(instance, dict), "array": isinstance(instance, list),
                "string": isinstance(instance, str), "boolean": isinstance(instance, bool),
                "null": instance is None,
            }
            if any(kind not in tests for kind in kinds):
                raise _invalid("Schema DomainPack dùng kiểu chưa được hỗ trợ.")
            if not any(tests[kind] for kind in kinds):
                raise _invalid("DomainPack có field sai kiểu.")
        if "const" in rule and instance != rule["const"]:
            raise _invalid("DomainPack có giá trị ngoài hằng số schema.")
        if "enum" in rule and instance not in rule["enum"]:
            raise _invalid("DomainPack có giá trị ngoài enum.")
        if isinstance(instance, dict):
            props = rule.get("properties")
            if props is not None:
                if set(instance) != set(props):
                    raise _invalid("DomainPack thiếu field bắt buộc hoặc có field ngoài hợp đồng.")
                for key, child in instance.items():
                    check(child, props[key], depth + 1)
        elif isinstance(instance, list):
            if len(instance) < rule.get("minItems", 0) or len(instance) > rule.get("maxItems", _MAX_NODES):
                raise _invalid("DomainPack có số phần tử không hợp lệ.")
            if rule.get("uniqueItems"):
                markers = [json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False)
                           for item in instance]
                if len(markers) != len(set(markers)):
                    raise _invalid("DomainPack có phần tử trùng.")
            if "items" in rule:
                for child in instance:
                    check(child, rule["items"], depth + 1)
        elif isinstance(instance, str):
            if len(instance) < rule.get("minLength", 0) or len(instance) > rule.get("maxLength", _MAX_RESOURCE_BYTES):
                raise _invalid("DomainPack có chuỗi vượt giới hạn.")
            if "pattern" in rule and re.fullmatch(rule["pattern"], instance) is None:
                raise _invalid("DomainPack có identifier không hợp lệ.")

    check(value, schema)


def _reject_money(pack: dict) -> None:
    count, active = 0, set()

    def visit(value, key: str = "", depth: int = 0) -> None:
        nonlocal count
        count += 1
        if count > _MAX_NODES or depth > 32:
            raise _invalid("DomainPack vượt giới hạn cấu trúc.")
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise _invalid("DomainPack không được có cấu trúc vòng.")
            active.add(id(value))
            if isinstance(value, dict):
                if any(not isinstance(name, str) for name in value):
                    raise _invalid("Tên field DomainPack phải là chuỗi.")
                for name, child in value.items():
                    visit(child, name, depth + 1)
            else:
                for child in value:
                    visit(child, key, depth + 1)
            active.remove(id(value))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and not math.isfinite(value):
                raise _invalid("DomainPack không được chứa số không hữu hạn.")
            # Pack chỉ giữ định danh/câu chữ; mọi lượng số thuộc engine.
            raise _invalid("DomainPack không được chứa giá trị số hoặc số tiền.")
        elif isinstance(value, str):
            if (_MONEY_KEY.search(key) and re.fullmatch(r"\s*[+-]?[0-9][0-9.,_ ]*\s*", value)):
                raise _invalid("DomainPack không được chứa số tiền dưới dạng chuỗi.")
            if _MONEY_UNIT.search(value) or _MONEY_CONTEXT.search(value):
                raise _invalid("Câu chữ DomainPack không được chứa số tiền cố định.")

    visit(pack)


def validate_pack(pack: dict) -> None:
    """Kiểm schema và tham chiếu; pack không có quyền cấp số hay verified."""
    try:
        _reject_money(pack)
        schema = _resource_json(schema_path(_SCHEMA_NAME))
        _validate_schema(pack, schema)
        expected_count = 10 if pack["id"] == "fin-pl-v1" else 5
        if pack["industry"] != ("finance" if expected_count == 10 else "generic"):
            raise _invalid("Pack id và industry không nhất quán.")
        policy_ids = [policy["subProblemId"] for policy in pack["policies"]]
        if len(policy_ids) != len(set(policy_ids)) or set(policy_ids) != {f"SP-{i}" for i in range(1, expected_count + 1)}:
            raise _invalid("DomainPack thiếu hoặc trùng policy bắt buộc.")
        metric_ids = [metric["formulaId"] for metric in pack["metrics"]]
        if len(metric_ids) != len(set(metric_ids)):
            raise _invalid("DomainPack có formulaId trùng.")
        available = set(metric_ids)
        measures = pack["outputContract"]["measures"]
        if len({measure["name"] for measure in measures}) != len(measures):
            raise _invalid("DomainPack có measure name trùng.")
        refs = [measure["formulaId"] for measure in measures]
        refs.extend(insight["formulaId"] for insight in pack["insights"])
        for policy in pack["policies"]:
            options = policy["options"]
            if len({option["id"] for option in options}) != len(options):
                raise _invalid("DomainPack có option id trùng.")
            recommended = [option["id"] for option in options if option["recommended"]]
            if recommended != [policy["proposedOptionId"]]:
                raise _invalid("Mỗi policy phải có đúng một đề xuất khớp option.")
            metric = policy["consequenceMetric"]
            missing = policy["status"] == "missing_data"
            if missing != (metric is None) or missing != (policy["labels"] == ["out_of_scope"]):
                raise _invalid("Policy missing_data phải giữ consequence null và out_of_scope.")
            if metric is not None:
                refs.append(metric)
            rule = policy["evaluationRule"]
            if rule is not None and not (pack["id"] == "fin-pl-v1" and policy["subProblemId"] == "SP-4"
                                         and policy["status"] == "inferred" and policy["provenance"] == "data"):
                raise _invalid("Rule đo dữ liệu chỉ được khai báo đúng policy hỗ trợ.")
            if rule is not None:
                refs.extend(("fm_rows_raw", "fm_rows_deduped", "fm_exact_duplicates", "fm_key_collisions"))
        if not set(refs) <= available:
            raise _invalid("DomainPack tham chiếu công thức không được khai báo.")
        metric_units = {entry["formulaId"]: entry["unit"] for entry in pack["metrics"]}
        if any(metric_units[measure["formulaId"]] != pack["outputContract"]["currency"]
               for measure in measures):
            raise _invalid("Đơn vị measure không khớp currency của output contract.")
        if any(policy["consequenceMetric"] is not None and
               metric_units[policy["consequenceMetric"]] != "VND"
               for policy in pack["policies"]):
            raise _invalid("Đơn vị consequence không khớp phép đo tiền được hỗ trợ.")
        if {insight["kind"] for insight in pack["insights"]} != {"hypothesis", "slice"}:
            raise _invalid("DomainPack phải có hypothesis và slice.")
    except InputError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise _invalid("DomainPack không hợp lệ hoặc không nhất quán.") from exc


def load_pack(pack_id: str) -> dict:
    """Đọc đúng tài nguyên đóng gói, trả một object mới cho mỗi lần gọi."""
    if not isinstance(pack_id, str) or pack_id not in _PACK_FILES:
        raise _invalid("DomainPack được chọn không được hỗ trợ.", "domainPack.id")
    result = _resource_json(package_path("sources", "packs", _PACK_FILES[pack_id]))
    validate_pack(result)
    if result["id"] != pack_id:
        raise _invalid("Tài nguyên DomainPack không khớp id được chọn.")
    return result


def select_pack(understand: dict) -> str:
    """Chọn pack theo cờ generic đã được WL2 khai báo, không đoán từ prompt."""
    if not isinstance(understand, dict) or not isinstance(understand.get("pack"), dict):
        raise _invalid("Cần metadata pack của WL2.")
    metadata = understand["pack"]
    if type(metadata.get("genericMode")) is not bool:
        raise _invalid("genericMode của WL2 phải là boolean.")
    selected = "generic" if metadata["genericMode"] else "fin-pl-v1"
    if metadata.get("id") != selected:
        raise _invalid("id và genericMode của WL2 không nhất quán.")
    return selected
