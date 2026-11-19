"""Authenticated local preparation reads and guarded native write protocols."""
from http import HTTPStatus
from urllib.parse import urlsplit

from pbip_assistant.errors import InputError
from pbip_assistant.sources.preparation.wire import validate_request


class PreparationEndpoints:
    def _post_preparation(self):
        try:
            body = validate_request(self._read_json(10 * 1024 * 1024))
            action = urlsplit(self.path).path.rsplit("/", 1)[-1]
            if body["action"] != action:
                raise InputError("INVALID_REQUEST", "action", "Action must match the endpoint")
            token = self.headers.get("X-Local-Token", "")
            transport = self.app.runtime.sessions.authenticate(token, touch=False).session_id
            store = self.app.preparation
            if (not store._backup_enabled and action in {"preservation-begin", "preservation-chunk", "preservation-finish",
                    "begin", "image-begin", "image-chunk", "image-finish", "write-ready", "complete", "undo", "redo", "restore-complete"}):
                raise InputError("DP_UNSUPPORTED_PRESERVATION", "preparation", "Preparation backup and recovery are disabled")
            if action == "preservation-begin":
                result = self.app.preparation_evidence.begin(transport, body["byteLength"], body["packageHash"])
            elif action == "preservation-chunk":
                result = self.app.preparation_evidence.chunk(transport, body["uploadId"], body["index"], body["offset"], body["chunkHash"], body["dataBase64"])
            elif action == "preservation-finish":
                result = self.app.preparation_evidence.finish(transport, body["uploadId"], body["semanticImage"])
            elif action == "pick-folder":
                result = self.app.folder_picker()
            elif action == "attach":
                result = store.attach(transport, body["claim"])
            else:
                pid = body["preparationId"]
                if action in {"state", "detach"}:
                    current = store.state(transport, pid)
                    if current["claimVersion"] != body["expectedClaimVersion"]:
                        raise InputError("DP_REVIEW_STALE", "claimVersion", "Workbook attachment changed")
                    result = current if action == "state" else store.detach(transport, pid, body["expectedClaimVersion"])
                    if action == "detach":
                        self.app.runtime.sessions.close(token)
                elif action == "source-snapshot":
                    result = store.put_source_snapshot(transport, pid, body["snapshot"])
                elif action == "source-set":
                    result = store.put_source_set(transport, pid, body["snapshots"], body["expectedSourceRevision"])
                elif action == "browse":
                    result = store.browse(transport, pid, body["root"], body["relativePath"],
                                          expected_claim_version=body["expectedClaimVersion"])
                elif action == "inventory":
                    result = store.inventory(transport, pid, body["root"], body["items"],
                                             expected_claim_version=body["expectedClaimVersion"])
                elif action == "scan":
                    current = store.state(transport, pid)
                    available = {s["sourceId"]: s for s in current["sources"]}
                    for selected in body["sources"]:
                        known = available.get(selected["sourceId"])
                        if known is None or any(selected[k] != known[k] for k in ("sheetId", "fingerprint")):
                            raise InputError("DP_SOURCE_STALE", "sources", "Read the selected source again")
                    result = store.scan(transport, pid, body["sourceRevision"], body["expectedFingerprint"],
                                        [s["sourceId"] for s in body["sources"]])
                elif action == "answer":
                    result = store.answer_question(transport, pid, body["questionId"], body["answer"], body["expectedAnswerRevision"])
                elif action == "preview":
                    if body["kind"] != "cleanup":
                        raise InputError("INVALID_REQUEST", "kind", "Use reviewed inventory for an import preview")
                    if body["sourceRevision"] != store.state(transport, pid)["sourceRevision"]:
                        raise InputError("DP_SOURCE_STALE", "sourceRevision", "Source revision changed")
                    result = store.preview(transport, pid, body["expectedFingerprint"], body["answerRevision"])
                elif action == "review-import":
                    result = store.review_import(transport, pid, body["inventoryHash"], body["mappings"], body.get("existingNames", []))
                elif action == "packages":
                    result = store.packages(transport, pid, body["reviewHash"])
                elif action == "approve":
                    result = store.approve(transport, pid, body["reviewHash"], body["kind"], body["target"])
                elif action == "direct-begin":
                    result = store.direct_begin(transport, pid, body["grantId"], body["beforeImage"])
                elif action == "direct-write-ready":
                    result = store.direct_write_ready(transport, pid, body["attemptId"], body["writePermit"], body["currentFingerprint"])
                elif action == "direct-complete":
                    result = store.direct_complete(transport, pid, body["attemptId"], body["receipt"], body.get("afterImage"))
                elif action == "begin":
                    result = store.begin_mutation(transport, pid, body["grantId"], body["expectedFingerprint"], body["expectedPreservationFingerprint"])
                elif action == "image-begin":
                    result = store.image_begin(transport, pid, body["attemptId"], body["purpose"], body["byteLength"], body["imageHash"])
                elif action == "image-chunk":
                    result = store.image_chunk(transport, pid, body["attemptId"], body["uploadId"], body["index"], body["offset"], body["chunkHash"], body["dataBase64"])
                elif action == "image-finish":
                    result = store.image_finish(transport, pid, body["attemptId"], body["uploadId"])
                elif action == "write-ready":
                    result = store.write_ready(transport, pid, body["attemptId"], body["beforeImageId"], body["expectedFingerprint"], body["expectedPreservationFingerprint"])
                elif action == "complete":
                    result = store.complete_mutation(transport, pid, body["attemptId"], body["receipt"])
                elif action in {"undo", "redo"}:
                    result = store.checkout_recovery(transport, pid, body["pointId"], action, body["expectedCursor"], body["expectedFingerprint"], body["expectedPreservationFingerprint"])
                elif action == "restore-complete":
                    result = store.complete_recovery(transport, pid, body["attemptId"], body["receipt"])
                else:
                    raise InputError("INVALID_REQUEST", "action", "Unsupported read action")
            self._json(HTTPStatus.OK, result)
        except InputError as exc:
            status = (HTTPStatus.REQUEST_ENTITY_TOO_LARGE if exc.code == "REQUEST_LIMIT" else
                      HTTPStatus.CONFLICT if exc.code.startswith("DP_") else HTTPStatus.BAD_REQUEST)
            self._error(status, exc.code, exc.detail, path=exc.path)
