from __future__ import annotations

import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from pbip_assistant.excel_addin_server import create_server
from pbip_assistant.pq_typed import DESTINATION_MARKER
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakeMProposal, FakePQRunner
from tests.support.pq_typed import FakeTypedPlanner


class TypedApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.path = Path(self.temp.name) / fixture.name
        self.payload = fixture.read_bytes()
        self.path.write_bytes(self.payload)
        self.workbook = office_snapshot(self.path)
        self.pq_runner = FakePQRunner()
        self.advanced_runner = FakeMProposal()
        self.typed_runner = FakeTypedPlanner()
        self.server = create_server(
            "127.0.0.1", 0, pq_runner=self.pq_runner,
            pq_codex_runner=self.advanced_runner, pq_typed_runner=self.typed_runner,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        _, bootstrap = self.request("GET", "/api/bootstrap")
        self.token = bootstrap["token"]

    def tearDown(self) -> None:
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: dict | None = None, *, auth: bool = False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if auth:
            headers = {"X-Local-Token": self.token, "Origin": f"http://127.0.0.1:{self.port}"}
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if payload is not None: headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, result

    def test_full_v2_api_and_advanced_contract_coexist(self) -> None:
        status, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue(bootstrap["capabilities"]["pqTypedStepsV2"])
        self.assertEqual(bootstrap["capabilities"]["pqTypedDestinationMarker"], DESTINATION_MARKER)

        status, plan = self.request("POST", "/api/pq/v2/plans", {
            "prompt": "Lọc và tính Profit", "workbook": self.workbook,
            "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        }, auth=True)
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["planStatus"], "reviewReady")
        encoded = base64.b64encode(self.payload).decode("ascii")
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": plan["revision"]["revisionId"], "workbook": self.workbook,
            "workbookBase64": encoded,
        }, auth=True)
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["status"], "excelRuntimePreview")
        self.assertNotIn("resultWorkbookBase64", preview)
        status, approval = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": plan["revision"]["revisionId"], "previewId": preview["previewId"],
            "destinationMarker": DESTINATION_MARKER,
        }, auth=True)
        self.assertEqual(status, 200, approval)
        status, prepared = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": approval["approvalId"], "workbookBase64": encoded,
            "destination": {"marker": DESTINATION_MARKER},
        }, auth=True)
        self.assertEqual(status, 200, prepared)
        status, completed = self.request("POST", "/api/pq/v2/applies/complete", {
            "applyId": prepared["applyId"],
            "readback": {
                "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
                "rowCount": prepared["expectedRows"], "columnCount": prepared["expectedColumns"],
            },
        }, auth=True)
        self.assertEqual(status, 200, completed)
        self.assertEqual(completed["status"], "applied")

        status, advanced = self.request("POST", "/api/pq/propose", {
            "prompt": "Advanced M", "workbook": self.workbook,
            "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        }, auth=True)
        self.assertEqual(status, 200)
        self.assertIn("mCode", advanced)

    def test_v2_mutations_require_token_and_approval_cannot_be_forged(self) -> None:
        status, body = self.request("POST", "/api/pq/v2/plans", {"prompt": "x", "workbook": self.workbook})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "TOKEN_REQUIRED")
        status, body = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": "apr_" + "0" * 24, "workbookBase64": base64.b64encode(self.payload).decode("ascii"),
            "destination": {"marker": DESTINATION_MARKER},
        }, auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "PQV2_APPROVAL_REQUIRED")


if __name__ == "__main__":
    unittest.main()
