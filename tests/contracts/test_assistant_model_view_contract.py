"""Closed-shape contract for the derived `modelView` (feature 004).

The schema lives in the application package (`core.resources.schema_path`) and
the fixtures are hand-written examples under `tests/fixtures/assistant/model_view/`.
Validation uses the stdlib oracle so no third-party JSON Schema library is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from pbip_assistant.core.resources import schema_path
from tests.support.json_schema_oracle import validate
from tests.support.paths import FIXTURES


ROOT = FIXTURES / "assistant" / "model_view"
SCHEMA_NAME = "assistant_model_view.schema.json"
STAR = "star_model_valid.json"


def load_schema() -> dict:
    path = schema_path(SCHEMA_NAME)
    return json.loads(path.read_text(encoding="utf-8"))


def read(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def follow(root: object, path: tuple) -> object:
    value = root
    for part in path:
        value = value[part]
    return value


def dict_paths(value: object, prefix: tuple = ()):
    """Yield the path of every dict reachable from `value`, root first."""
    if isinstance(value, dict):
        yield prefix
        for key, child in value.items():
            yield from dict_paths(child, prefix + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from dict_paths(child, prefix + (index,))


def clone(value: dict) -> dict:
    return json.loads(json.dumps(value))


class AssistantModelViewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema()
        cls.star = read(STAR)

    def test_valid_examples_pass(self) -> None:
        for path in sorted(ROOT.glob("*_valid.json")):
            with self.subTest(fixture=path.name):
                instance = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validate(instance, self.schema), [])

    def test_invalid_examples_fail(self) -> None:
        examples = json.loads((ROOT / "invalid_examples.json").read_text(encoding="utf-8"))
        self.assertTrue(examples, "invalid_examples.json must not be empty")
        for entry in examples:
            with self.subTest(example=entry["name"]):
                errors = validate(entry["modelView"], self.schema)
                self.assertTrue(errors, entry["name"] + ": expected at least one error")

    def test_unknown_key_rejected_at_every_level(self) -> None:
        injections = {
            "root": (),
            "counts": ("counts",),
            "table": ("tables", 0),
            "column": ("tables", 0, "columns", 0),
            "relationship": ("relationships", 0),
            "warning": ("warnings", 0),
            "date_range": ("tables", 0, "dateRange"),
            "grain_evidence": ("tables", 2, "grainEvidence"),
        }
        for label, path in injections.items():
            with self.subTest(level=label):
                instance = clone(self.star)
                target = follow(instance, path)
                target["extra"] = 1
                self.assertTrue(validate(instance, self.schema),
                                label + ": unknown key must be rejected")

    def test_enums_closed(self) -> None:
        bad_values = [
            ("mode", "graph"),
            ("measuredOn", "all"),
            ("structural", "star"),
            ("grainKind", "daily"),
            ("cardinality", "1:2"),
            ("wireState", "wavy"),
            ("role", "money"),
        ]
        for label, (field, value) in enumerate(bad_values):
            with self.subTest(field=field, value=value):
                instance = clone(self.star)
                if field == "structural":
                    instance["tables"][0]["structural"] = value
                elif field == "grainKind":
                    instance["tables"][0]["grainKind"] = value
                elif field == "role":
                    instance["tables"][0]["columns"][0]["role"] = value
                elif field == "cardinality":
                    instance["relationships"][0]["cardinality"] = value
                elif field == "wireState":
                    instance["relationships"][0]["wireState"] = value
                else:
                    instance[field] = value
                errors = validate(instance, self.schema)
                self.assertTrue(any("ngoài enum" in error for error in errors),
                                field + "=" + value + ": expected an enum error")

    def test_no_sample_or_evidence_keys_allowed(self) -> None:
        for key in ("sample", "evidence"):
            for path in dict_paths(self.star):
                with self.subTest(key=key, path=path):
                    instance = clone(self.star)
                    follow(instance, path)[key] = 1
                    errors = validate(instance, self.schema)
                    self.assertTrue(errors, key + " at " + ".".join(str(p) for p in path) + ": must be rejected")

    def test_columns_capped_at_200(self) -> None:
        instance = clone(self.star)
        table = instance["tables"][0]
        sample_column = table["columns"][0]
        table["columns"] = [clone(sample_column) for _ in range(200)]
        table["columnCount"] = 200
        self.assertEqual(validate(instance, self.schema), [])
        table["columns"].append(clone(sample_column))
        table["columnCount"] = 201
        errors = validate(instance, self.schema)
        self.assertTrue(any("nhiều phần tử hơn maxItems" in error for error in errors),
                        "201 columns must exceed the 200 cap")

    def test_schema_resolved_via_core_resources(self) -> None:
        path = schema_path(SCHEMA_NAME)
        self.assertTrue(path.is_file(), SCHEMA_NAME + " must exist under pbip_assistant/schemas/")
        resolved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(resolved, self.schema, "schema must be loaded through core.resources")
        # Every example must reference the exact same bundled schema, not a copy.
        self.assertIn("additionalProperties", resolved)
        self.assertFalse(resolved.get("additionalProperties"))


if __name__ == "__main__":
    unittest.main()