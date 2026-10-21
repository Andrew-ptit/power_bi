from __future__ import annotations

import base64
from contextlib import redirect_stdout
import hashlib
import http.client
from http import HTTPStatus
from io import StringIO
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock
import struct
from xml.etree import ElementTree
from urllib.parse import parse_qs, urlsplit

from pbip_assistant.excel_addin_server import (
    CodexCooldown,
    DEFAULT_ADDIN_PORTS,
    ExcelAddinRequestHandler,
    create_server,
    create_server_from_port_pool,
    sync_runtime_manifest,
)
from pbip_assistant.excel_plan import OPERATIONS
from pbip_assistant.pq_typed import build_source_catalog
from tests.test_codex_excel import FakeCodex, workbook as codex_workbook
from tests.test_excel_connector import FakeExcelRunner
from tests.test_excel_plan import FIXTURE_ROOT, office_snapshot


class ExcelAddinServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "excel_mcp_sales_input.xlsx"
        self.workbook_bytes = (FIXTURE_ROOT / self.source.name).read_bytes()
        self.source.write_bytes(self.workbook_bytes)
        self.manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.workbook = office_snapshot(self.source)
        self.runner = FakeExcelRunner(self.manifest["expected_rows"])
        self.codex_runner = FakeCodex()
        self.server = create_server("127.0.0.1", 0, runner=self.runner, codex_runner=self.codex_runner)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        status, _, payload = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.token = payload["token"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: dict | None = None, headers: dict[str, str] | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers = dict(headers or {})
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        response_body = response.read()
        response_headers = {key: value for key, value in response.getheaders()}
        connection.close()
        if response_headers.get("Content-Type", "").startswith("application/json"):
            response_body = json.loads(response_body.decode("utf-8"))
        else:
            response_body = response_body.decode("utf-8")
        return response.status, response_headers, response_body

    def auth(self) -> dict[str, str]:
        return {"X-Local-Token": self.token, "Origin": f"http://127.0.0.1:{self.port}"}

    def test_taskpane_assets_and_bootstrap_capabilities(self) -> None:
        status, headers, body = self.request("GET", "/taskpane.html")
        self.assertEqual(status, 200)
        self.assertIn("Excel task pane", body)
        self.assertIn("appsforoffice.microsoft.com", body)
        self.assertEqual(body.count('id="formula-list-separator"'), 1)
        self.assertEqual(body.count('id="codex-status"'), 1)
        self.assertLess(body.index('class="connection-toolbar"'), body.index('<nav class="tab-bar"'))
        self.assertLess(body.index('id="formula-list-separator"'), body.index('id="prompt-title"'))
        self.assertNotIn('id="pq-source"', body)
        self.assertNotIn('id="pq-risk-check"', body)
        self.assertNotIn('id="pq-save-button"', body)
        self.assertIn('Chạy thử và mở sheet kết quả', body)
        self.assertEqual(body.count('id="pq-apply-source-button"'), 1)
        self.assertIn('id="pq2-mode-button" class="tab-button active"', body)
        self.assertLess(body.index('id="pq2-mode"'), body.index('id="pq-advanced-mode"'))
        self.assertEqual(body.count('id="pq-confirm-overlay"'), 1)
        self.assertEqual(body.count('id="pq-confirm-continue"'), 1)
        status, _, script = self.request("GET", "/assets/taskpane.js")
        self.assertEqual(status, 200)
        self.assertNotIn("window.confirm(", script)
        self.assertIn("appsforoffice.microsoft.com", headers["Content-Security-Policy"])
        status, _, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertFalse(bootstrap["capabilities"]["sourceWrite"])
        self.assertFalse(bootstrap["capabilities"]["mcpServer"])
        self.assertTrue(bootstrap["capabilities"]["codexAnalysis"])
        self.assertTrue(bootstrap["capabilities"]["pqTypedStepsV2"])
        self.assertTrue(bootstrap["capabilities"]["pqTypedStepDiagnostics"])

    def test_step_diagnostic_sample_profiles_once_then_uses_cache(self) -> None:
        request = {
            "workbook": self.workbook,
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
            "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        }
        status, _, first = self.request(
            "POST", "/api/pq/v2/step-diagnostics/samples", request, self.auth(),
        )
        self.assertEqual(status, 200, first)
        self.assertFalse(first["cacheHit"])
        self.assertTrue(first["profileId"].startswith("prof_"))
        self.assertEqual(first["sourceFingerprint"], first["sourceDataFingerprint"])
        self.assertLessEqual(len(first["sampleRows"]), 20)
        self.assertEqual(first["rowCount"], 6)
        _, catalog, _ = build_source_catalog(self.workbook)
        expected_source = next(item for item in catalog if item.get("objectName") == "SalesTable")
        self.assertEqual(
            first["columnTypes"],
            [column["inferredType"] for column in expected_source["columns"]],
        )
        self.assertEqual(len(first["columnTypes"]), first["columnCount"])
        status, _, second = self.request(
            "POST", "/api/pq/v2/step-diagnostics/samples", request, self.auth(),
        )
        self.assertEqual(status, 200, second)
        self.assertTrue(second["cacheHit"])
        self.assertEqual(second["profileId"], first["profileId"])
        self.assertEqual(second["sampleRows"], first["sampleRows"])
        self.assertEqual(second["columnTypes"], first["columnTypes"])

    def test_second_coordinator_cannot_bind_same_port(self) -> None:
        with self.assertRaises(OSError):
            duplicate = create_server("127.0.0.1", self.port, runner=self.runner, codex_runner=self.codex_runner)
            duplicate.server_close()

    def test_codex_analysis_does_not_invoke_excel_writer(self) -> None:
        status, _, plan = self.request(
            "POST", "/api/excel/analyze",
            {"prompt": "Tách mã đơn hàng", "workbook": codex_workbook(), "formulaListSeparator": ";"}, self.auth(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(plan["status"], "analysis_only")
        self.assertFalse(plan["canApply"])
        self.assertEqual(self.codex_runner.payload["formulaListSeparator"], ";")
        self.assertEqual(self.runner.requests, [])

    def test_codex_cooldown_rejects_repeat_without_calling_runner(self) -> None:
        self.server.app.codex_cooldown.note_rate_limit()
        status, headers, body = self.request(
            "POST", "/api/excel/analyze",
            {"prompt": "short prompt", "workbook": codex_workbook()}, self.auth(),
        )
        self.assertEqual(status, 429)
        self.assertEqual(body["error"]["code"], "CODEX_RATE_LIMITED")
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        self.assertIsNone(self.codex_runner.payload)

    def test_manifest_icon_is_a_real_64px_png(self) -> None:
        for size in (16, 32, 64, 80):
            with self.subTest(size=size):
                connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                connection.request("GET", f"/assets/icon-{size}.png")
                response = connection.getresponse()
                payload = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "image/png")
                self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", payload[16:24]), (size, size))
                connection.close()

    def test_manifest_targets_local_https_excel_workbook(self) -> None:
        manifest_path = Path(__file__).resolve().parents[1] / "tools" / "excel_addin" / "manifest.xml"
        root = ElementTree.parse(manifest_path).getroot()
        namespace = {"o": "http://schemas.microsoft.com/office/appforoffice/1.1"}
        self.assertEqual(root.attrib["{http://www.w3.org/2001/XMLSchema-instance}type"], "TaskPaneApp")
        manifest_version = tuple(int(part) for part in root.findtext("o:Version", namespaces=namespace).split("."))
        self.assertGreaterEqual(manifest_version, (1, 0, 0, 0))
        self.assertEqual(root.find("o:Hosts/o:Host", namespace).attrib["Name"], "Workbook")
        source_url = urlsplit(root.find("o:DefaultSettings/o:SourceLocation", namespace).attrib["DefaultValue"])
        self.assertEqual(source_url.scheme, "https")
        self.assertEqual(source_url.hostname, "localhost")
        self.assertIn(source_url.port, DEFAULT_ADDIN_PORTS)
        self.assertEqual(source_url.path, "/taskpane.html")
        channels = parse_qs(source_url.query).get("channel", [])
        self.assertEqual(len(channels), 1)
        self.assertRegex(channels[0], r"^[0-9a-f]{24}$")
        self.assertEqual(urlsplit(root.find("o:IconUrl", namespace).attrib["DefaultValue"]).path, "/assets/icon-64.png")
        self.assertEqual(root.findtext("o:Permissions", namespaces=namespace), "ReadWriteDocument")
        override_namespace = {
            "v": "http://schemas.microsoft.com/office/taskpaneappversionoverrides",
            "bt": "http://schemas.microsoft.com/office/officeappbasictypes/1.0",
        }
        overrides = root.find("v:VersionOverrides", override_namespace)
        self.assertIsNotNone(overrides)
        action = overrides.find(".//v:Action", override_namespace)
        self.assertEqual(action.attrib["{http://www.w3.org/2001/XMLSchema-instance}type"], "ShowTaskpane")
        self.assertEqual(action.find("v:SourceLocation", override_namespace).attrib["resid"], "Taskpane.Url")
        icon_urls = [
            item.attrib["DefaultValue"]
            for item in overrides.findall("v:Resources/bt:Images/bt:Image", override_namespace)
        ]
        self.assertEqual(
            [urlsplit(url).path for url in icon_urls],
            ["/assets/icon-16.png", "/assets/icon-32.png", "/assets/icon-80.png"],
        )
        for url in icon_urls:
            parsed = urlsplit(url)
            self.assertEqual(parsed.port, source_url.port)
            self.assertEqual(parse_qs(parsed.query).get("channel"), channels)

    def test_plan_and_apply_api_create_new_copy(self) -> None:
        plan_request = {"prompt": self.manifest["prompt"], "workbook": self.workbook}
        status, _, plan = self.request("POST", "/api/excel/plan", plan_request, self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(plan["status"], "review_ready")
        apply_request = {
            **plan_request,
            "snapshotId": plan["snapshotId"],
            "planRevisionId": plan["planRevisionId"],
            "operationIds": [item.id for item in OPERATIONS],
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
        }
        status, _, result = self.request("POST", "/api/excel/apply", apply_request, self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "excel_runtime_verified")
        self.assertNotEqual(Path(result["copy"]["path"]), self.source)
        self.assertTrue(Path(result["copy"]["path"]).is_file())

    def test_mutations_require_token_and_do_not_log_body(self) -> None:
        captured = StringIO()
        secret = "private-cell-value-must-not-log"
        with redirect_stdout(captured):
            status, _, result = self.request("POST", "/api/excel/plan", {"prompt": secret, "workbook": {}})
        self.assertEqual(status, 403)
        self.assertEqual(result["error"]["code"], "TOKEN_REQUIRED")
        self.assertNotIn(secret, captured.getvalue())

    def test_stale_plan_and_wrong_origin_are_blocked(self) -> None:
        plan_request = {"prompt": self.manifest["prompt"], "workbook": self.workbook}
        _, _, plan = self.request("POST", "/api/excel/plan", plan_request, self.auth())
        stale = {
            **plan_request,
            "prompt": self.manifest["prompt"] + " changed",
            "snapshotId": plan["snapshotId"],
            "planRevisionId": plan["planRevisionId"],
            "operationIds": [item.id for item in OPERATIONS],
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
        }
        status, _, result = self.request("POST", "/api/excel/apply", stale, self.auth())
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "PLAN_STALE")
        status, _, result = self.request(
            "POST",
            "/api/excel/plan",
            plan_request,
            {"X-Local-Token": self.token, "Origin": "https://example.com"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(result["error"]["code"], "ORIGIN_BLOCKED")

    def test_session_close_drains_body_and_sets_close_connection(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "POST",
            "/api/session/close",
            body=b"{}",
            headers={"X-Local-Token": self.token, "Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"},
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Connection"), "close")
        response.read()
        connection.close()

    def test_response_write_ignores_expected_client_abort(self) -> None:
        class AbortedWriter:
            def write(self, _payload: bytes) -> None:
                raise ConnectionAbortedError(10053, "client closed")

        handler = object.__new__(ExcelAddinRequestHandler)
        handler.close_connection = False
        handler.wfile = AbortedWriter()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler._security_headers = mock.Mock()

        handler._bytes(HTTPStatus.OK, b'{}', "application/json")

        self.assertTrue(handler.close_connection)

    def test_parse_request_recovers_from_stray_curly_prefix(self) -> None:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw_request = (
            b"{}GET /taskpane.html HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Connection: close\r\n\r\n"
        )
        sock.sendall(raw_request)
        response_bytes = sock.recv(4096)
        sock.close()
        self.assertTrue(response_bytes.startswith(b"HTTP/1.1 200 OK"))


class RuntimeCoordinatorBootstrapTests(unittest.TestCase):
    def test_codex_cooldown_backoff_and_success_reset(self) -> None:
        now = [100.0]
        cooldown = CodexCooldown(clock=lambda: now[0])
        self.assertEqual(cooldown.note_rate_limit(), 60)
        with self.assertRaisesRegex(Exception, "CODEX_RATE_LIMITED"):
            cooldown.check()
        now[0] = 160.0
        cooldown.check()
        self.assertEqual(cooldown.note_rate_limit(), 120)
        now[0] = 280.0
        cooldown.check()
        cooldown.note_success()
        self.assertEqual(cooldown.note_rate_limit(), 60)

    def test_port_pool_uses_first_available_port_in_descending_order(self) -> None:
        busy = OSError("busy")
        busy.winerror = 10048
        expected_server = object()
        with mock.patch(
            "pbip_assistant.excel_addin_server.create_server",
            side_effect=[busy, busy, expected_server],
        ) as create:
            actual = create_server_from_port_pool(
                "127.0.0.1", (3079, 3078, 3077), ssl_context=None,
            )
        self.assertIs(actual, expected_server)
        self.assertEqual([call.args[:2] for call in create.call_args_list], [
            ("127.0.0.1", 3079), ("127.0.0.1", 3078), ("127.0.0.1", 3077),
        ])

    def test_runtime_manifest_rewrites_port_channel_and_matches_catalog(self) -> None:
        manifest = Path(__file__).resolve().parents[1] / "tools" / "excel_addin" / "manifest.xml"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "repository" / "manifest.xml"
            catalog = Path(folder) / "catalog" / "manifest.xml"
            source.parent.mkdir()
            catalog.parent.mkdir()
            source.write_bytes(manifest.read_bytes())
            digest = sync_runtime_manifest(
                source, catalog, 3074, "0123456789abcdef01234567",
            )
            self.assertEqual(source.read_bytes(), catalog.read_bytes())
            rendered = source.read_text(encoding="utf-8")
            self.assertNotIn("localhost:3000", rendered)
            self.assertIn("localhost:3074", rendered)
            self.assertIn("channel=0123456789abcdef01234567", rendered)
            self.assertEqual(digest, "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()

