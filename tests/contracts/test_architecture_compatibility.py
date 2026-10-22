"""Behavioral import/resource/schema contracts protecting the folder migration."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from pbip_assistant.core.resources import package_path, repository_path, schema_path
from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import ProblemChainStore
from tests.support.problem_chain import typed_plan
from tests.support.problem_chain_journey import _review_basis


class ArchitectureCompatibilityTests(unittest.TestCase):
    def test_legacy_modules_are_identical_and_share_monkeypatches(self) -> None:
        aliases = {
            "excel_addin_server": "coordinator.server", "coordinator_runtime": "coordinator.runtime",
            "codex_excel": "adapters.codex.excel", "codex_pq": "adapters.codex.powerquery",
            "excel_connector": "excel.connector", "excel_plan": "excel.planning",
            "pq_code_m": "powerquery.advanced.runtime", "step_diagnostic_sampler": "powerquery.diagnostics.sampler",
            "errors": "core.errors", "xlsx": "sources.xlsx", "csv_source": "sources.csv_source",
            "schema": "sources.schema", "workbook_fingerprint": "sources.workbook_fingerprint",
            "source_workflow": "sources.source_workflow", "workflow": "sources.workflow",
            "pbip": "powerbi.pbip", "pbir": "powerbi.pbir", "tmdl": "powerbi.tmdl", "planning": "powerbi.planning",
        }
        for old_name, new_name in aliases.items():
            with self.subTest(module=old_name):
                old = importlib.import_module("pbip_assistant." + old_name)
                new = importlib.import_module("pbip_assistant." + new_name)
                self.assertIs(old, new)
                sentinel = object()
                with patch.object(old, "_compatibility_probe", sentinel, create=True):
                    self.assertIs(new._compatibility_probe, sentinel)
                self.assertFalse(hasattr(new, "_compatibility_probe"))

    def test_schema_bytes_and_resource_locations_preserve_baseline_contract(self) -> None:
        expected = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "schema_sha256.json").read_text())
        for name, digest in expected["sha256"].items():
            with self.subTest(schema=name):
                path = schema_path(name)
                self.assertEqual(path, package_path("schemas", name))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            with self.subTest(schema=name, compatibility="legacy_resource_path"):
                # Pre-refactor coordinators can retain the flat SCHEMA_PATH
                # until restart. Canonical schemas remain the source of truth.
                self.assertEqual(package_path(name).read_bytes(), schema_path(name).read_bytes())
        self.assertTrue(repository_path("tools", "excel_connector", "Invoke-PQCodeM.ps1").is_file())
        self.assertTrue(package_path("excel_addin", "taskpane.js").is_file())

    def test_typed_catalog_is_closed_paired_and_rejects_unknown_operation(self) -> None:
        from pbip_assistant.powerquery.typed.model import OPERATION_ARITY, PARAMETER_KEYS, EXPRESSION_KEYS
        from pbip_assistant.powerquery.typed.registry import OPERATION_REGISTRY, EXPRESSION_KINDS
        from pbip_assistant.powerquery.typed.validation import _normalize_steps
        self.assertEqual(len(OPERATION_REGISTRY), 15)
        self.assertEqual(set(OPERATION_REGISTRY), set(OPERATION_ARITY))
        self.assertEqual(set(OPERATION_REGISTRY), set(PARAMETER_KEYS))
        self.assertEqual(set(EXPRESSION_KINDS), set(EXPRESSION_KEYS))
        self.assertEqual(len(EXPRESSION_KINDS), 10)
        for handler in OPERATION_REGISTRY.values():
            self.assertTrue(callable(handler.normalize))
            self.assertTrue(callable(handler.compile))
        with self.assertRaises(TypeError):
            OPERATION_REGISTRY["table.untrusted"] = next(iter(OPERATION_REGISTRY.values()))
        step = {
            "clientRef": "unsafe", "variableName": "Untrusted", "actionDescription": "Unknown operation",
            "operationType": "table.untrusted", "parameters": {}, "inputs": [],
        }
        _, _, blockers, _ = _normalize_steps([step], "unsafe", [], draft=True)
        self.assertIn("PQV2_OPERATION_UNSUPPORTED", {issue["code"] for issue in blockers})

    def test_contract_model_import_does_not_load_runtime_stores(self) -> None:
        probe = "import sys; import pbip_assistant.powerquery.typed.model; assert 'pbip_assistant.pq_typed' not in sys.modules; assert 'pbip_assistant.problem_chain' not in sys.modules; assert 'pbip_assistant.coordinator.server' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", probe], cwd=repository_path(), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_history_hashes_preserve_independent_canonical_basis_and_reserved_fields(self) -> None:
        from pbip_assistant import problem_chain as facade
        from pbip_assistant.powerquery.history import document as contract
        for name in ("canonical_json", "compute_review_hash", "compute_history_hash", "source_schema_fingerprint", "validate_document"):
            self.assertIs(getattr(facade, name), getattr(contract, name))
        store = ProblemChainStore()
        self.addCleanup(store.close)
        candidate = store.create_problem(None, None, "Read Sales", typed_plan=typed_plan())
        document = candidate["document"]
        revision = document["revisions"][0]
        canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(facade.canonical_json(document), canonical(document))
        self.assertEqual(facade.compute_history_hash(document), "sha256:" + hashlib.sha256(canonical(document)).hexdigest())
        self.assertEqual(revision["reviewHash"], "sha256:" + hashlib.sha256(canonical(_review_basis(revision))).hexdigest())
        for field, unsupported in (("name", "A name"), ("note", "A note"), ("annotationUpdatedAt", "2026-10-21T00:00:00Z"), ("runtimeSummary", {})):
            with self.subTest(field=field):
                self.assertIsNone(revision[field])
                value = deepcopy(document)
                value["revisions"][0][field] = unsupported
                with self.assertRaises(InputError) as caught:
                    facade.validate_document(value)
                self.assertEqual(caught.exception.code, "PQPC_DOCUMENT_INVALID")
