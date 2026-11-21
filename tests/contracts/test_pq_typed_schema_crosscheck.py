from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.excel_addin_server import create_server
from pbip_assistant.pq_typed import (
    AI_SCHEMA_PATH,
    CodexTypedRunner,
    _load_and_preflight_ai_schema,
)
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot


class TypedSchemaMutationOracleTests(unittest.TestCase):
    """Independent fail-closed checks against plausible schema drift."""

    def _assert_preflight_rejects(self, mutate) -> None:
        schema = json.loads(AI_SCHEMA_PATH.read_text(encoding="utf-8"))
        mutate(schema)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mutated.schema.json"
            path.write_text(json.dumps(schema), encoding="utf-8")
            with self.assertRaises(InputError) as caught:
                _load_and_preflight_ai_schema(path)
        self.assertEqual(caught.exception.code, "CODEX_SCHEMA_INVALID")

    def test_preflight_rejects_catalog_arity_and_expression_drift(self) -> None:
        mutations = {
            "operation discriminator": lambda schema: schema["$defs"]["filterRowsStep"]["properties"]["operationType"].update(enum=["table.unknown"]),
            "operation arity": lambda schema: schema["$defs"]["filterRowsStep"]["properties"].update(inputs={"$ref": "#/$defs/twoInputs"}),
            "non-local arity reference": lambda schema: schema["$defs"]["filterRowsStep"]["properties"].update(inputs={"$ref": "oneInput"}),
            "expression discriminator": lambda schema: schema["$defs"]["safeDivideExpression"]["properties"]["kind"].update(enum=["unsafeDivide"]),
            "object type removed": lambda schema: schema["$defs"]["filterParameters"].pop("type"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self._assert_preflight_rejects(mutate)

    @patch("pbip_assistant.adapters.codex.typed.subprocess.run")
    @patch("pbip_assistant.adapters.codex.typed.find_codex_executable")
    @patch("pbip_assistant.adapters.codex.typed._load_and_preflight_ai_schema")
    def test_schema_failure_occurs_before_executable_lookup_or_subprocess(
        self, preflight, find_executable, subprocess_run,
    ) -> None:
        preflight.side_effect = InputError(
            "CODEX_SCHEMA_INVALID", "codexSchema", "Synthetic preflight failure",
        )
        with self.assertRaises(InputError) as caught:
            CodexTypedRunner().propose({"operationCatalog": []})
        self.assertEqual(caught.exception.code, "CODEX_SCHEMA_INVALID")
        find_executable.assert_not_called()
        subprocess_run.assert_not_called()


class _ErrorTypedRunner:
    def __init__(self) -> None:
        self.code = "CODEX_FAILED"
        self.calls = 0

    def propose(self, _payload: dict) -> dict:
        self.calls += 1
        raise InputError(self.code, "codex", "Sanitized typed-planner failure")


class TypedPlannerHttpErrorOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = _ErrorTypedRunner()
        cls.server = create_server("127.0.0.1", 0, pq_typed_runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        status, _headers, bootstrap = cls._request("GET", "/api/bootstrap")
        if status != 200:
            raise AssertionError(bootstrap)
        cls.token = bootstrap["token"]
        cls.workbook = office_snapshot(FIXTURE_ROOT / "excel_mcp_sales_input.xlsx")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    @classmethod
    def _request(cls, method: str, path: str, body: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        headers: dict[str, str] = {}
        if hasattr(cls, "token"):
            headers = {
                "X-Local-Token": cls.token,
                "Origin": f"http://127.0.0.1:{cls.port}",
            }
        payload = None if body is None else json.dumps(body).encode("utf-8")
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        response_headers = dict(response.getheaders())
        result = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, response_headers, result

    def test_codex_failure_codes_have_the_release_http_contract(self) -> None:
        cases = {
            "CODEX_SCHEMA_INVALID": 500,
            "CODEX_AUTH_REQUIRED": 503,
            "CODEX_TIMEOUT": 504,
            "CODEX_UNAVAILABLE": 503,
            "CODEX_FAILED": 502,
            "CODEX_RATE_LIMITED": 429,
        }
        request = {
            "prompt": "Synthetic error mapping check",
            "workbook": self.workbook,
            "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        }
        for code, expected_status in cases.items():
            with self.subTest(code=code):
                self.runner.code = code
                status, headers, result = self._request("POST", "/api/pq/v2/plans", request)
                self.assertEqual(status, expected_status, result)
                self.assertEqual(result["error"]["code"], code)
                if code == "CODEX_RATE_LIMITED":
                    self.assertEqual(headers.get("Retry-After"), "60")
                    prior_calls = self.runner.calls
                    status, headers, result = self._request("POST", "/api/pq/v2/plans", request)
                    self.assertEqual(status, 429)
                    self.assertEqual(result["error"]["code"], "CODEX_RATE_LIMITED")
                    self.assertGreater(int(headers["Retry-After"]), 0)
                    self.assertEqual(self.runner.calls, prior_calls)


if __name__ == "__main__":
    unittest.main()
