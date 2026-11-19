"""Real local HTTP guards and scan/answer/preview, no live Excel claims."""
import http.client
import json
import threading
import unittest

from pbip_assistant.coordinator.server import create_server
from tests.support.codex_excel import FakeCodex


class PreparationApiTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0, codex_runner=FakeCodex())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        _, bootstrap = self.call("GET", "/api/bootstrap")
        self.token = bootstrap["token"]

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def call(self, method, path, payload=None, token=None, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Local-Token"] = token
        if origin:
            headers["Origin"] = origin
        try:
            connection.request(method, path, None if payload is None else json.dumps(payload), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def post(self, action, **fields):
        return self.call("POST", "/api/preparation/" + action,
                         {"schemaVersion": 1, "action": action, **fields}, self.token)

    def attach(self, marker=None, version=0):
        return self.post("attach", claim={"marker": marker, "semanticFingerprint": "sha256:" + "1" * 64,
            "targetConfirmed": True, "expectedClaimVersion": version, "workbookName": "Synthetic", "locationHash": None})

    def test_guarded_local_read_workflow_and_no_write_capability(self):
        _, boot = self.call("GET", "/api/bootstrap")
        self.assertIs(boot["capabilities"].get("preparationReadV1"), True)
        self.assertIs(boot["capabilities"].get("preparationV1"), True)
        self.assertEqual(boot["capabilities"].get("preparationNativeQualification"), "user_pending")
        status, state = self.attach()
        self.assertEqual(status, 200)
        pid = state["preparationId"]
        status, state = self.post("source-snapshot", preparationId=pid, snapshot={
            "sourceId": "source_01", "sheetId": "{sheet_01}", "headers": ["Date"], "rows": [["03/04/2026"]],
            "formulaCells": [], "columnKinds": ["unknown"], "numberFormats": [["General"]],
            "dateSystem": "1900", "rowOffset": 1, "columnOffset": 0})
        self.assertEqual(status, 200)
        status, state = self.post("scan", preparationId=pid, sourceRevision=state["sourceRevision"],
            expectedFingerprint=state["sourceHash"], sources=[{**{k: state["sources"][0][k] for k in ("sourceId", "sheetId", "fingerprint")}, "kind": "usedRange"}])
        self.assertEqual(status, 200)
        status, state = self.post("answer", preparationId=pid, questionId=state["questions"][0]["questionId"],
            expectedAnswerRevision=state["answerRevision"], answer={"choice": "DMY", "reason": None})
        self.assertEqual(status, 200)
        status, state = self.post("preview", preparationId=pid, kind="cleanup", sourceRevision=state["sourceRevision"],
            answerRevision=state["answerRevision"], expectedFingerprint=state["sourceHash"])
        self.assertEqual(status, 200)
        self.assertEqual(state["preview"]["examples"][0]["after"], 46115)
        self.assertFalse(state["writeEnabled"])
        self.assertEqual(self.post("approve", preparationId=pid, kind="cleanup", reviewHash=state["preview"]["reviewHash"],
                target={"strategy": "personal_copy", "sheetIds": ["{sheet_01}"]})[0], 409)

    def test_no_token_origin_and_unknown_keys_fail_before_workflow(self):
        payload = {"schemaVersion": 1, "action": "state", "preparationId": "unknown", "expectedClaimVersion": 0}
        self.assertEqual(self.call("POST", "/api/preparation/state", payload)[0], 403)
        self.assertEqual(self.call("POST", "/api/preparation/state", payload, self.token, "https://untrusted.invalid")[0], 403)
        self.assertEqual(self.post("state", preparationId="unknown", expectedClaimVersion=0, allowSourceWrite=True)[0], 400)

    def test_folder_dialog_is_explicit_authenticated_and_cancel_is_harmless(self):
        calls = []
        self.server.app.folder_picker = lambda: (calls.append(True) or {"cancelled": True, "path": None, "name": None})
        status, result = self.post("pick-folder")
        self.assertEqual(status, 200)
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.post("pick-folder", root="unexpected")[0], 400)
        self.assertEqual(self.call("POST", "/api/preparation/pick-folder", {"schemaVersion": 1, "action": "pick-folder"})[0], 403)
        self.assertEqual(calls, [True])

    def test_detach_retires_transport_and_explicit_close_clears_retained_metadata(self):
        status, state = self.attach()
        self.assertEqual(status, 200)
        self.assertEqual(self.post("detach", preparationId=state["preparationId"], expectedClaimVersion=state["claimVersion"])[0], 200)
        self.assertEqual(self.post("state", preparationId=state["preparationId"], expectedClaimVersion=state["claimVersion"])[0], 401)
        _, boot = self.call("GET", "/api/bootstrap")
        self.token = boot["token"]
        status, resumed = self.attach(state["marker"], state["claimVersion"])
        self.assertEqual(status, 200)
        self.assertEqual(resumed["preparationId"], state["preparationId"])
        self.assertEqual(resumed["questions"], [])
        self.assertEqual(self.call("POST", "/api/session/close", {}, self.token)[0], 200)
        _, boot = self.call("GET", "/api/bootstrap")
        self.token = boot["token"]
        self.assertEqual(self.attach(resumed["marker"], resumed["claimVersion"])[0], 409)


if __name__ == "__main__":
    unittest.main()

class PreservationEvidenceApiTests(unittest.TestCase):
    setUp = PreparationApiTests.setUp
    stop = PreparationApiTests.stop
    call = PreparationApiTests.call
    post = PreparationApiTests.post

    def test_native_evidence_upload_requires_auth_and_retires_with_transport(self):
        body = {"schemaVersion": 1, "action": "preservation-begin", "byteLength": 12, "packageHash": "sha256:" + "1" * 64}
        self.assertEqual(self.call("POST", "/api/preparation/preservation-begin", body)[0], 403)
        status, result = self.post("preservation-begin", byteLength=12, packageHash="sha256:" + "1" * 64)
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "DP_UNSUPPORTED_PRESERVATION")
        self.assertIsNone(self.server.app.preparation_evidence)
        self.assertIsNone(self.server.app.preparation._journal)
        self.assertEqual(self.call("POST", "/api/session/close", {}, self.token)[0], 200)
        self.assertEqual(self.post("preservation-begin", byteLength=12, packageHash="sha256:" + "1" * 64)[0], 401)

    def test_preservation_routes_reject_unknown_outer_fields_and_bad_frame(self):
        self.assertEqual(self.post("preservation-begin", byteLength=12, packageHash="sha256:" + "1" * 64, path="../escape")[0], 400)
        for action, fields in (
            ("preservation-chunk", {"uploadId": "none", "index": 0, "offset": 0, "chunkHash": "sha256:" + "1" * 64, "dataBase64": "eA=="}),
            ("preservation-finish", {"uploadId": "none", "semanticImage": {}}),
        ):
            status, result = self.post(action, **fields)
            self.assertEqual(status, 409)
            self.assertEqual(result["error"]["code"], "DP_UNSUPPORTED_PRESERVATION")
        self.assertIsNone(self.server.app.preparation_evidence)
