from __future__ import annotations

import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from pbip_assistant.excel_addin_server import create_server
from pbip_assistant.pq_code_m import ADVANCED_M_POLICY_ID
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakeMProposal, FakePQRunner
from tests.support.workbook_fingerprint import repack


class PQApiTests(unittest.TestCase):
    def test_run_sheet_returns_static_values_without_creating_file_copy(self) -> None:
        encoded = base64.b64encode(self.source_bytes).decode("ascii")
        request = {
            "workbook": self.workbook, "source": self.selection, "mCode": self.code,
            "riskAccepted": False, "riskPolicyId": ADVANCED_M_POLICY_ID,
            "workbookBase64": encoded,
        }
        status, blocked = self.request("POST", "/api/pq/run-sheet", request, authorized=True)
        self.assertEqual(status, 400)
        self.assertEqual(blocked["error"]["code"], "PQ_RISK_ACK_REQUIRED")
        self.assertEqual(self.runner.requests, [])
        request["riskAccepted"] = True
        request["riskPolicyId"] = "advanced-m-trusted-v0"
        status, blocked = self.request("POST", "/api/pq/run-sheet", request, authorized=True)
        self.assertEqual(status, 409)
        self.assertEqual(blocked["error"]["code"], "PQ_RISK_POLICY_STALE")
        self.assertEqual(self.runner.requests, [])
        request["riskPolicyId"] = ADVANCED_M_POLICY_ID
        status, result = self.request("POST", "/api/pq/run-sheet", request, authorized=True)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "ready_for_open_workbook")
        self.assertEqual(result["resultWorkbookSheetName"], "PQ_Result_Values")
        self.assertTrue(base64.b64decode(result["resultWorkbookBase64"]).startswith(b"PK"))
        status, unchanged = self.request("POST", "/api/pq/check-source", {
            "sourceFingerprint": result["sourceFingerprint"],
            "workbookBase64": base64.b64encode(repack(self.source_bytes)).decode("ascii"),
        }, authorized=True)
        self.assertEqual(status, 200)
        self.assertEqual(unchanged, {"unchanged": True})
        status, changed = self.request("POST", "/api/pq/check-source", {
            "sourceFingerprint": result["sourceFingerprint"],
            "workbookBase64": base64.b64encode(repack(self.source_bytes, change_cell=True)).decode("ascii"),
        }, authorized=True)
        self.assertEqual(status, 200)
        self.assertEqual(changed, {"unchanged": False})
        status, invalid_ignore = self.request("POST", "/api/pq/check-source", {
            "sourceFingerprint": result["sourceFingerprint"],
            "workbookBase64": encoded,
            "ignoredSheetNames": ["Sales"],
        }, authorized=True)
        self.assertEqual(status, 400)
        self.assertEqual(invalid_ignore["error"]["code"], "PQ_PREVIEW_SHEET_INVALID")
        self.assertEqual(self.source_path.read_bytes(), self.source_bytes)
        self.assertFalse(list(Path(self.temp.name).glob("*_PQ_clean_*.xlsx")))

    def test_run_sheet_uses_office_export_for_remote_workbook(self) -> None:
        encoded = base64.b64encode(self.source_bytes).decode("ascii")
        for url in [
            "https://tenant.sharepoint.com/sites/data/orders.xlsx",
            "ms-excel:ofe|u|https://tenant.sharepoint.com/sites/data/orders.xlsx",
            "file:///C:/missing-folder/excel_mcp_sales_input.xlsx",
        ]:
            with self.subTest(url=url):
                workbook = {**self.workbook, "url": url}
                status, result = self.request("POST", "/api/pq/run-sheet", {
                    "workbook": workbook, "source": self.selection, "mCode": self.code,
                    "riskAccepted": True, "riskPolicyId": ADVANCED_M_POLICY_ID,
                    "workbookBase64": encoded,
                }, authorized=True)
                self.assertEqual(status, 200, result)
                self.assertEqual(result["status"], "ready_for_open_workbook")
                self.assertIsNone(result["sourceUnchanged"])
                self.assertFalse(list(Path(self.temp.name).glob("*_PQ_clean_*.xlsx")))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.source_path = Path(self.temp.name) / fixture.name
        self.source_bytes = fixture.read_bytes()
        self.source_path.write_bytes(self.source_bytes)
        self.workbook = office_snapshot(self.source_path)
        self.selection = {"kind": "table", "sheet": "Sales", "name": "SalesTable"}
        self.code = 'let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content] in Source'
        self.runner = FakePQRunner()
        self.proposer = FakeMProposal()
        self.server = create_server(
            "127.0.0.1", 0, pq_runner=self.runner, pq_codex_runner=self.proposer,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        _, bootstrap = self.request("GET", "/api/bootstrap")
        self.token = bootstrap["token"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: dict | None = None, *, authorized: bool = False):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if authorized:
            headers = {"X-Local-Token": self.token, "Origin": f"http://127.0.0.1:{self.port}"}
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, result

    def test_old_copy_endpoints_cannot_create_a_result_file(self) -> None:
        status, body = self.request("POST", "/api/pq/propose", {
            "prompt": "Bỏ dòng rỗng", "workbook": self.workbook, "source": self.selection,
        }, authorized=True)
        self.assertEqual(status, 200)
        self.assertIn("mCode", body)
        encoded = base64.b64encode(self.source_bytes).decode("ascii")
        request = {
            "workbook": self.workbook, "source": self.selection, "mCode": self.code,
            "riskAccepted": False, "riskPolicyId": ADVANCED_M_POLICY_ID,
            "workbookBase64": encoded,
        }
        status, body = self.request("POST", "/api/pq/preview", request, authorized=True)
        self.assertEqual(status, 410)
        self.assertEqual(body["error"]["code"], "PQ_COPY_FLOW_REMOVED")
        self.assertEqual(self.runner.requests, [])
        request["riskAccepted"] = True
        status, blocked = self.request("POST", "/api/pq/preview", request, authorized=True)
        self.assertEqual(status, 410)
        self.assertEqual(blocked["error"]["code"], "PQ_COPY_FLOW_REMOVED")
        status, blocked = self.request("POST", "/api/pq/save", {"previewId": "old"}, authorized=True)
        self.assertEqual(status, 410)
        self.assertEqual(blocked["error"]["code"], "PQ_COPY_FLOW_REMOVED")
        self.assertEqual(self.runner.requests, [])
        self.assertFalse(list(Path(self.temp.name).glob("*_PQ_clean_*.xlsx")))
        self.assertEqual(self.source_path.read_bytes(), self.source_bytes)

    def test_mutation_requires_session_token(self) -> None:
        status, body = self.request("POST", "/api/pq/propose", {
            "prompt": "x", "workbook": self.workbook, "source": self.selection,
        })
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "TOKEN_REQUIRED")
        self.assertIsNone(self.proposer.payload)


if __name__ == "__main__":
    unittest.main()
