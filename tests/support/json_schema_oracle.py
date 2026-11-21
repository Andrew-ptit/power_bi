"""Oracle JSON Schema giới hạn, thuần stdlib, dùng cho fixture Assistant."""

from __future__ import annotations

import json
import math
import re
from typing import Any


_KEYWORDS = frozenset({
    "$schema", "$defs", "$ref", "type", "properties", "required",
    "additionalProperties", "items", "enum", "const", "pattern", "minimum",
    "maximum", "minLength", "maxLength", "minItems", "maxItems", "uniqueItems",
    "oneOf", "anyOf",
})
_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})


def _preflight(schema: Any, root: dict, seen: set[int]) -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError("Schema phải là object hoặc boolean")
    if id(schema) in seen:
        return
    seen.add(id(schema))
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise ValueError("Keyword không hỗ trợ: " + ", ".join(sorted(unknown)))
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not types or any(item not in _TYPES for item in types):
            raise ValueError("Kiểu schema không hỗ trợ")
    if "pattern" in schema:
        re.compile(schema["pattern"])
    if "$ref" in schema:
        _preflight(_resolve(schema["$ref"], root), root, seen)
    for keyword in ("properties", "$defs"):
        for child in schema.get(keyword, {}).values():
            _preflight(child, root, seen)
    for keyword in ("items", "additionalProperties"):
        if keyword in schema:
            _preflight(schema[keyword], root, seen)
    for keyword in ("oneOf", "anyOf"):
        for child in schema.get(keyword, []):
            _preflight(child, root, seen)


def _resolve(reference: str, root: dict) -> dict | bool:
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        raise ValueError("Chỉ hỗ trợ $ref local #/$defs/...")
    value: Any = root
    try:
        for part in reference[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError) as exc:
        raise ValueError("$ref local không tồn tại") from exc
    return value


def _equal(left: Any, right: Any) -> bool:
    # JSON boolean không đồng nhất với số 0/1 trong enum và uniqueItems.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def _is_type(instance: Any, expected: str) -> bool:
    number = isinstance(instance, (int, float)) and not isinstance(instance, bool)
    finite = number and (not isinstance(instance, float) or math.isfinite(instance))
    return {
        "object": isinstance(instance, dict), "array": isinstance(instance, list),
        "string": isinstance(instance, str), "number": finite,
        "integer": finite and (isinstance(instance, int) or instance.is_integer()),
        "boolean": isinstance(instance, bool), "null": instance is None,
    }[expected]


def validate(instance: Any, schema: dict) -> list[str]:
    """Trả lỗi có đường dẫn; keyword ngoài tập hỗ trợ luôn gây ValueError."""
    _preflight(schema, schema, set())

    def check(value: Any, rule: dict | bool, path: str, active: set[tuple[int, int]]) -> list[str]:
        if rule is True:
            return []
        if rule is False:
            return [f"{path}: schema từ chối giá trị"]
        pair = (id(value), id(rule))
        if pair in active:
            raise ValueError("$ref đệ quy không tiêu thụ cấu trúc instance")
        nested = active | {pair}
        errors: list[str] = []
        if "$ref" in rule:
            errors.extend(check(value, _resolve(rule["$ref"], schema), path, nested))
        for keyword in ("oneOf", "anyOf"):
            if keyword in rule:
                matches = sum(not check(value, child, path, nested) for child in rule[keyword])
                if (keyword == "oneOf" and matches != 1) or (keyword == "anyOf" and not matches):
                    errors.append(f"{path}: không khớp {keyword}")
        expected = rule.get("type")
        types = expected if isinstance(expected, list) else [expected]
        if expected is not None and not any(_is_type(value, kind) for kind in types):
            return errors + [f"{path}: sai kiểu dữ liệu"]
        if "enum" in rule and not any(_equal(value, item) for item in rule["enum"]):
            errors.append(f"{path}: ngoài enum")
        if "const" in rule and not _equal(value, rule["const"]):
            errors.append(f"{path}: khác const")
        if isinstance(value, dict):
            props = rule.get("properties", {})
            for name in rule.get("required", []):
                if name not in value:
                    errors.append(f"{path}.{name}: thiếu field bắt buộc")
            for name, item in value.items():
                if name in props:
                    errors.extend(check(item, props[name], f"{path}.{name}", nested))
                elif "additionalProperties" in rule:
                    errors.extend(check(item, rule["additionalProperties"], f"{path}.{name}", nested))
        if isinstance(value, list):
            if len(value) < rule.get("minItems", 0):
                errors.append(f"{path}: ít phần tử hơn minItems")
            if "maxItems" in rule and len(value) > rule["maxItems"]:
                errors.append(f"{path}: nhiều phần tử hơn maxItems")
            if rule.get("uniqueItems") and any(_equal(item, earlier) for i, item in enumerate(value) for earlier in value[:i]):
                errors.append(f"{path}: có phần tử trùng")
            if "items" in rule:
                for index, item in enumerate(value):
                    errors.extend(check(item, rule["items"], f"{path}[{index}]", nested))
        if isinstance(value, str):
            if len(value) < rule.get("minLength", 0):
                errors.append(f"{path}: ngắn hơn minLength")
            if "maxLength" in rule and len(value) > rule["maxLength"]:
                errors.append(f"{path}: dài hơn maxLength")
            if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
                errors.append(f"{path}: không khớp pattern")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                errors.append(f"{path}: nhỏ hơn minimum")
            if "maximum" in rule and value > rule["maximum"]:
                errors.append(f"{path}: lớn hơn maximum")
        return errors

    return check(instance, schema, "$", set())


def validate_or_raise(instance: Any, schema: dict) -> None:
    """Raise AssertionError khi instance không đúng hợp đồng."""
    errors = validate(instance, schema)
    if errors:
        raise AssertionError("\n".join(errors))
