"""Validate only the bundled preparation request dialect, no external schemas."""
from copy import deepcopy
from functools import lru_cache
import json
import math
import re

from pbip_assistant.core.resources import schema_path
from pbip_assistant.errors import InputError


@lru_cache(maxsize=1)
def _contract():
    return json.loads(schema_path("preparation.schema.json").read_text(encoding="utf-8"))


def _reject(path):
    raise InputError("INVALID_REQUEST", path, "Preparation request does not match its closed contract")


def _check(value, rule, definitions, path):
    if not rule:
        # Semantic evidence is bounded/closed by its owner after envelope validation.
        return deepcopy(value)
    allowed = {"$ref", "type", "const", "enum", "anyOf", "properties", "required", "additionalProperties",
               "minLength", "maxLength", "pattern", "items", "minItems", "maxItems", "minimum", "maximum"}
    if set(rule) - allowed:
        raise RuntimeError("Unsupported keyword in bundled preparation contract")
    if "$ref" in rule:
        ref = rule["$ref"]
        if not ref.startswith("#/$defs/") or ref[8:] not in definitions:
            raise RuntimeError("Invalid local preparation contract reference")
        return _check(value, definitions[ref[8:]], definitions, path)
    if "anyOf" in rule:
        for choice in rule["anyOf"]:
            try:
                return _check(value, choice, definitions, path)
            except InputError:
                pass
        _reject(path)
    kind = rule.get("type")
    number = type(value) in {int, float} and (not isinstance(value, float) or math.isfinite(value))
    valid = {"string": isinstance(value, str), "number": number, "integer": number and (type(value) is int or value.is_integer()),
             "boolean": type(value) is bool, "null": value is None, "object": isinstance(value, dict), "array": isinstance(value, list)}
    if kind is not None and not valid.get(kind, False):
        _reject(path)
    if "const" in rule and (value != rule["const"] or type(value) is bool and type(rule["const"]) is not bool):
        _reject(path)
    if "enum" in rule and not any(value == candidate and (type(value) is not bool or type(candidate) is bool) for candidate in rule["enum"]):
        _reject(path)
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        if set(rule.get("required", [])) - set(value) or rule.get("additionalProperties") is False and set(value) - set(properties):
            _reject(path)
        return {key: _check(item, properties.get(key, {}), definitions, path + "." + key) for key, item in value.items()}
    if isinstance(value, list):
        if not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", len(value)):
            _reject(path)
        return [_check(item, rule["items"], definitions, path + "[" + str(i) + "]") for i, item in enumerate(value)]
    if isinstance(value, str):
        if (not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", len(value))
                or "pattern" in rule and re.fullmatch(rule["pattern"], value) is None):
            _reject(path)
    if number and not rule.get("minimum", value) <= value <= rule.get("maximum", value):
        _reject(path)
    return int(value) if kind == "integer" else value


def validate_request(value):
    if not isinstance(value, dict) or not isinstance(value.get("action"), str):
        _reject("request")
    contract = _contract()
    branch = next((r for r in contract["oneOf"] if r["properties"]["action"]["const"] == value["action"]), None)
    if branch is None:
        _reject("request.action")
    return _check(deepcopy(value), branch, contract["$defs"], "request")
