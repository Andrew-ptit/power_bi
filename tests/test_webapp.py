from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO

from examples.source_fixtures import build_fixtures
from pbip_assistant.webapp import UploadStore, create_server


class LocalWebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UploadStore(Path(self.temp.name) / "uploads")
        self.server = create_server("127.0.0.1", 0, store=self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        status, _, payload = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.token = payload["token"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.thread.join(timeout=2)

    def request(
        self,
        method: str,
        path: str,
        body: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = dict(headers or {})
        if isinstance(body, str):
            body = body.encode("utf-8")
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        header_map = {key: value for key, value in response.getheaders()}
        connection.close()
        return response.status, header_map, json.loads(payload.decode("utf-8"))

    def upload(self, name: str, payload: bytes) -> dict:
        status, _, response = self.request(
            "POST",
            "/api/files",
            payload,
            {
                "X-Local-Token": self.token,
                "X-File-Name": name,
                "Content-Type": "application/octet-stream",
            },
        )
        self.assertEqual(status, 201)
        return response["file"]

    def test_static_ui_and_security_headers_are_local_only(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Data Profiler", body)
        self.assertIn(".xlsx", body)
        self.assertIn("default-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
        connection.close()

    def test_token_and_origin_protect_mutations(self) -> None:
        captured = StringIO()
        with redirect_stdout(captured):
            status, _, payload = self.request(
                "POST",
                "/api/files",
                b"secret-cell-value",
                {"X-File-Name": "Orders.csv"},
            )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "TOKEN_REQUIRED")
        self.assertNotIn("secret-cell-value", captured.getvalue())
        status, _, payload = self.request(
            "POST",
            "/api/files",
            b"a,b\n1,2\n",
            {
                "X-Local-Token": self.token,
                "X-File-Name": "Orders.csv",
                "Origin": "https://example.com",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "ORIGIN_BLOCKED")

    def test_upload_and_profile_xlsx_csv_without_private_temp_paths(self) -> None:
        fixtures = build_fixtures()
        xlsx = self.upload("Orders.xlsx", fixtures["orders_synthetic.xlsx"])
        csv_file = self.upload("Orders.csv", fixtures["orders_synthetic.csv"])
        request = json.dumps({
            "preview_limit": 3,
            "files": [
                {"id": xlsx["id"], "options": {}},
                {"id": csv_file["id"], "options": {}},
            ],
        })
        status, _, result = self.request(
            "POST",
            "/api/profile",
            request,
            {
                "X-Local-Token": self.token,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["state"], "profile_ready")
        self.assertEqual(result["summary"]["file_count"], 2)
        self.assertEqual(len(result["workbooks"][0]["sheets"][0]["preview"]["rows"]), 3)
        self.assertEqual(len(result["csv_files"][0]["preview"]["rows"]), 3)
        serialized = json.dumps(result)
        self.assertNotIn(str(self.store.root), serialized)
        self.assertIn("Orders.xlsx", serialized)

    def test_csv_error_is_actionable_and_can_be_retried_with_options(self) -> None:
        uploaded = self.upload("Ambiguous.csv", b"A,B;C\n1,2;3\n")
        def profile(options: dict) -> tuple[int, dict]:
            status, _, result = self.request(
                "POST",
                "/api/profile",
                json.dumps({"files": [{"id": uploaded["id"], "options": options}]}),
                {"X-Local-Token": self.token, "Content-Type": "application/json"},
            )
            return status, result

        status, blocked = profile({})
        self.assertEqual(status, 200)
        self.assertEqual(blocked["errors"][0]["code"], "CSV_AMBIGUOUS_DELIMITER")
        status, ready = profile({"delimiter": ","})
        self.assertEqual(status, 200)
        self.assertEqual(ready["state"], "profile_ready")

    def test_upload_rejects_paths_and_unsupported_files(self) -> None:
        for name, code in (("../escape.csv", "INVALID_FILENAME"), ("notes.txt", "UNSUPPORTED_SOURCE")):
            with self.subTest(name=name):
                status, _, result = self.request(
                    "POST",
                    "/api/files",
                    b"payload",
                    {"X-Local-Token": self.token, "X-File-Name": name},
                )
                self.assertEqual(status, 400)
                self.assertEqual(result["error"]["code"], code)

    def test_percent_encoded_unicode_filename_is_preserved(self) -> None:
        status, _, result = self.request(
            "POST",
            "/api/files",
            b"A,B\n1,2\n",
            {
                "X-Local-Token": self.token,
                "X-File-Name": "%C4%90%C6%A1n-h%C3%A0ng.csv",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["file"]["name"], "Đơn-hàng.csv")

    def test_remove_and_reset_delete_temporary_copies(self) -> None:
        first = self.upload("A.csv", b"A,B\n1,2\n")
        second = self.upload("B.csv", b"A,B\n3,4\n")
        self.assertEqual(len(list(self.store.root.iterdir())), 2)
        status, _, _ = self.request(
            "DELETE",
            f"/api/files/{first['id']}",
            headers={"X-Local-Token": self.token},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(list(self.store.root.iterdir())), 1)
        status, _, _ = self.request(
            "POST",
            "/api/reset",
            "{}",
            {"X-Local-Token": self.token},
        )
        self.assertEqual(status, 200)
        self.assertEqual(list(self.store.root.iterdir()), [])
        self.assertNotEqual(first["id"], second["id"])


if __name__ == "__main__":
    unittest.main()
