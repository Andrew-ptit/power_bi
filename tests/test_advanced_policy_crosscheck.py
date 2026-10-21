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
from tests.test_excel_plan import FIXTURE_ROOT, office_snapshot
from tests.test_pq_code_m import FakeMProposal, FakePQRunner


EXPECTED_POLICY = {
    "policyId": "advanced-m-trusted-v1",
    "mode": "trusted",
    "enabled": True,
    "riskAcknowledgementRequired": True,
    "acknowledgementScope": "workbookPanelSession",
    "externalConnectors": "allowed",
    "previewIsolation": "temporaryWorkbookNotSandbox",
    "applyToSource": "explicitConfirmation",
    "backupPolicy": "none",
    "autoSave": False,
}


class AdvancedPolicyIndependentCrosscheck(unittest.TestCase):
    """Reviewer-owned HTTP oracle, independent from the Trusted Mode UI tests."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.source_path = Path(self.temp.name) / fixture.name
        self.source_path.write_bytes(fixture.read_bytes())
        self.runner = FakePQRunner()
        self.server = create_server(
            "127.0.0.1", 0, pq_runner=self.runner, pq_codex_runner=FakeMProposal(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        status, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.token = bootstrap["token"]
        self.bootstrap = bootstrap

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers: dict[str, str] = {}
        if method == "POST":
            headers = {
                "X-Local-Token": getattr(self, "token", ""),
                "Origin": f"http://127.0.0.1:{self.port}",
                "Content-Type": "application/json",
            }
        payload = None if body is None else json.dumps(body).encode("utf-8")
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, result

    def test_bootstrap_policy_is_exact_release_contract(self) -> None:
        self.assertEqual(ADVANCED_M_POLICY_ID, EXPECTED_POLICY["policyId"])
        self.assertEqual(self.bootstrap["capabilities"]["advancedMPolicy"], EXPECTED_POLICY)

    def test_rejected_acknowledgements_never_reach_excel_runner(self) -> None:
        base = {
            "workbook": office_snapshot(self.source_path),
            "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
            "mCode": 'let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content] in Source',
            "workbookBase64": base64.b64encode(self.source_path.read_bytes()).decode("ascii"),
        }
        cases = (
            ({}, "PQ_RISK_ACK_REQUIRED"),
            ({"riskAccepted": False, "riskPolicyId": ADVANCED_M_POLICY_ID}, "PQ_RISK_ACK_REQUIRED"),
            ({"riskAccepted": True}, "PQ_RISK_POLICY_STALE"),
            ({"riskAccepted": True, "riskPolicyId": "advanced-m-trusted-v0"}, "PQ_RISK_POLICY_STALE"),
        )
        for updates, expected_code in cases:
            with self.subTest(updates=updates):
                status, result = self.request("POST", "/api/pq/run-sheet", {**base, **updates})
                self.assertIn(status, {400, 409})
                self.assertEqual(result["error"]["code"], expected_code)
                self.assertEqual(self.runner.requests, [])


if __name__ == "__main__":
    unittest.main()
