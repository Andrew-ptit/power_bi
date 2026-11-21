"""Preparation-only approval, verified images and one-use native write handshakes."""
import base64
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.runtime import TempWorkspaceManager
from .journal import RestoreJournal, RECEIPT_RESERVE
from .model import OperationScope, require_hash
from .inventory import verify_inventory, safe_sheet_name
from .packages import build_packages, image_fingerprint, MAX_IMAGE_BYTES
from .image_model import image_full_fingerprint, preservation_fingerprint
from .direct import PreparationDirectMutation
from .package_preservation import (inspect_package, verify_package_delta, verify_package_group,
    verify_package_copy_delta, validate_delta_targets, validate_copy_targets)
from pbip_assistant.sources.assistant_ingest import canonical_hash


def _fail(code, detail): return InputError(code, "preparation", detail)
def _digest(data): return "sha256:" + hashlib.sha256(data).hexdigest()
def _encode(image): return json.dumps(image, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class PreparationMutation(PreparationDirectMutation):
    def _require_native_write(self, document=None):
        if not self._native_write_enabled:
            raise _fail("DP_UNSUPPORTED_PRESERVATION", "Native preservation and recovery qualification have not passed; writes stay disabled")
        if document is None or not document.get("nativeIdentityHash") or (self._backup_enabled and
                (not document.get("preservationFingerprint") or not getattr(self,"_evidence",None))):
            raise _fail("DP_BINDING_REQUIRED", "Fresh native identity and complete preservation evidence are required")

    def _mutation_init(self, workspace_manager=None):
        self._journal = None
        self._workspace_manager = workspace_manager
        self._points = {}
        self._upload_budget_key = "preparation_uploads_" + uuid4().hex
        self._metadata_budget_key = "preparation_packages_" + uuid4().hex

    def _sync_metadata_budget(self):
        budget = getattr(self, "_physical_budget", None)
        if budget is not None:
            # Exact package DTOs are immutable and shared by review/attempt/
            # history. Charge each distinct retained package set once.
            retained = {}
            groups = [point["packages"] for point in self._points.values()]
            groups += [(document.get("packageCache") or {}).get("packages", []) for document in self._documents.values()]
            groups += [(document.get("attempt") or {}).get("packages", []) for document in self._documents.values()]
            for packages in groups:
                if packages:
                    encoded = _encode(packages)
                    retained[_digest(encoded)] = len(encoded)
            budget.replace_usage(self._metadata_budget_key, sum(retained.values()))

    def _sync_upload_budget(self, extra=0):
        budget = getattr(self, "_physical_budget", None)
        if budget is not None:
            pending = sum(upload["length"] for document in self._documents.values()
                          for upload in (document.get("attempt") or {}).get("uploads", {}).values())
            budget.replace_usage(self._upload_budget_key, pending + extra)

    def _recovery(self):
        self._require_backup_mode()
        if self._journal is None:
            self._journal = RestoreJournal(self._workspace_manager or TempWorkspaceManager(start_janitor=False), clock=self._clock, physical_budget=getattr(self,"_physical_budget",None))
        return self._journal

    def _prune_point_metadata(self):
        if self._journal is not None:
            retained = {p["pointId"] for d in self._documents.values() for p in self._journal.state(d["id"])["points"]}
            self._points = {pid: point for pid, point in self._points.items() if pid in retained}
            self._sync_metadata_budget()

    def _current_review(self, document, kind):
        if kind == "import":
            review = document.get("importReview")
            if not review or document["inventory"] is None:
                raise _fail("DP_REVIEW_STALE", "Review the current import mapping")
            verify_inventory(document["inventory"])
            return review["reviewHash"]
        if kind == "cleanup" and document["preview"] is not None and not document["needsReview"]:
            return document["preview"].review_hash
        raise _fail("DP_REVIEW_STALE", "Review the current cleanup first")

    def packages(self, transport, preparation_id, review_hash, date_system=None, *, reuse_reviewed=True):
        with self._lock:
            d = self._get(transport, preparation_id)
            current_hash = self._current_review(d, "import")
            review = d["importReview"]
            if review_hash not in (current_hash, review["mappingReviewHash"]):
                raise _fail("DP_REVIEW_STALE", "Import mapping changed")
            cache = d.get("packageCache")
            if reuse_reviewed and date_system is None and cache:
                if not cache["packages"]:
                    raise _fail("DP_REVIEW_STALE", "No reviewed sheets are available to write")
                return deepcopy(cache)

            # Regenerate CSV report metadata on demand. Reuse the verified XLSX
            # transfer for this mapping so a report read never renormalizes it.
            reviewed_xlsx = {p["fileId"]: p for p in cache["packages"] if p["kind"] == "xlsx"} if cache else {}
            report = {}
            packages = build_packages(d["inventory"], d["inventory"].inventory_hash,
                review["mappings"], review["existingNames"], workspace_manager=self._workspace_manager,
                date_system=date_system, report=report, reviewed_xlsx=reviewed_xlsx)
            if reuse_reviewed and date_system is None and not packages:
                raise _fail("DP_REVIEW_STALE", "No reviewed sheets are available to write")
            has_dates = any("yyyy-mm-dd" in row for package in packages if package["kind"] == "csv"
                            for sheet in package["sheets"] for row in sheet["numberFormats"])
            frame_hash = (canonical_hash({"mapping": review["mappingReviewHash"], "dateSystem": date_system})
                          if has_dates else review["mappingReviewHash"])
            if cache is None or cache["reviewHash"] != frame_hash:
                cache = {"reviewHash": frame_hash, "packages": packages}
                d.update(packageCache=cache, grant=None)
                try:
                    self._sync_metadata_budget()
                except InputError:
                    d.pop("packageCache", None)
                    review["reviewHash"] = review["mappingReviewHash"]
                    self._sync_metadata_budget()
                    raise
                review["reviewHash"] = frame_hash
            return deepcopy({**cache, "importReport": report})

    def approve(self, transport, preparation_id, review_hash, kind, target):
        with self._lock:
            d = self._get(transport, preparation_id)
            self._require_native_write(d)
            if d.get("attempt"):
                raise _fail("DP_PARTIAL_UNKNOWN" if d["status"] == "partial_unknown" else "DP_REVIEW_STALE", "Finish the active attempt first")
            if self._current_review(d, kind) != review_hash:
                raise _fail("DP_REVIEW_STALE", "Approval must bind the exact current review")
            if not isinstance(target, dict) or set(target) != {"strategy", "sheetIds"} or not isinstance(target["sheetIds"], list) or not target["sheetIds"] or len(set(target["sheetIds"])) != len(target["sheetIds"]):
                raise _fail("INVALID_REQUEST", "Select exact reviewed target sheets")
            if kind == "import":
                if target["strategy"] != "import_new": raise _fail("INVALID_REQUEST", "Import creates new sheets only")
                self.packages(transport, preparation_id, review_hash)
            else:
                sources = {s.sheet_id for s in d["scan"].sources}
                if set(target["sheetIds"]) != sources:
                    raise _fail("DP_REVIEW_STALE", "Cleanup target differs from the reviewed sources")
                if target["strategy"] == "imported_inplace":
                    if not sources <= set(d.get("importedSheetIds", [])):
                        raise _fail("DP_BINDING_REQUIRED", "In-place cleanup requires verified import ownership")
                elif target["strategy"] != "personal_copy":
                    raise _fail("INVALID_REQUEST", "Personal sources require separate result copies")
            grant = {"grantId": uuid4().hex, "reviewHash": review_hash, "kind": kind, "target": deepcopy(target),
                     "sourceRevision": d["sourceRevision"], "answerRevision": d["answerRevision"]}
            d["grant"] = grant
            return deepcopy({k: grant[k] for k in ("grantId", "reviewHash", "kind", "target")})

    def begin_mutation(self, transport, preparation_id, grant_id, expected_fingerprint, expected_preservation_fingerprint=None):
        with self._lock:
            self._require_backup_mode()
            d = self._get(transport, preparation_id)
            self._require_native_write(d)
            require_hash(expected_fingerprint)
            self._check_preservation_head(d, expected_preservation_fingerprint)
            if expected_fingerprint != d["claimFingerprint"]:
                raise _fail("DP_SOURCE_STALE", "Workbook changed since attachment; reattach and review its current data")
            grant = d.get("grant")
            if (not grant or grant["grantId"] != grant_id or d.get("attempt")
                    or grant["reviewHash"] != self._current_review(d, grant["kind"])
                    or grant["sourceRevision"] != d["sourceRevision"] or grant["answerRevision"] != d["answerRevision"]):
                raise _fail("DP_REVIEW_STALE", "Approval is absent, consumed or stale")
            packages = self.packages(transport, preparation_id, grant["reviewHash"])["packages"] if grant["kind"] == "import" else []
            attempt = {"attemptId": uuid4().hex, "kind": grant["kind"], "operation": grant["kind"],
                "beforeFingerprint": expected_fingerprint, "beforePreservationFingerprint": expected_preservation_fingerprint, "writePermit": uuid4().hex,
                "scope": {"fullWorkbook": True, "sheetIds": []}, "packages": packages,
                "changes": deepcopy(list(d["preview"].changes)) if grant["kind"] == "cleanup" else [],
                "target": deepcopy(grant["target"]), "targetCopies": [], "uploads": {}, "images": {},
                "phase": "prepared", "reservation": None, "reviewHash": grant["reviewHash"]}
            for change in attempt["changes"]:
                source = next(s for s in d["scan"].sources if s.source_id == change["sourceId"])
                change["beforeNumberFormat"] = source.number_formats[change["row"]][change["column"]]
                change["row"] += source.row_offset
                change["column"] += source.column_offset
            d.update(attempt=attempt, grant=None, status="backup_pending")
            return self._attempt_public(attempt)

    def _attempt_public(self, attempt):
        hidden = {"uploads", "images", "reservation", "expectedImage", "phase", "reviewHash", "currentNativeEvidence", "currentImage"}
        result = deepcopy({k: v for k, v in attempt.items() if k not in hidden})
        if "image" in result:
            result["image"] = self._semantic_image(result["image"])
        return result

    @staticmethod
    def _semantic_image(image):
        return deepcopy({k:v for k,v in image.items() if k != "_nativeEvidence"})

    def _check_preservation_head(self, document, expected):
        if expected is None:
            raise _fail("DP_BINDING_REQUIRED", "Current complete preservation fingerprint is required")
        require_hash(expected)
        if document.get("preservationFingerprint") != expected:
            raise _fail("DP_RESTORE_CONFLICT", "Native workbook metadata or styles changed since the verified head")

    def _resolve_native_image(self, transport, image):
        # Client images remain closed; complete package evidence comes only from
        # an authenticated server inspection, never client-supplied parts.
        image_fingerprint(image)
        full = preservation_fingerprint(image)
        evidence = self._evidence.resolve(transport,image["preservation"]["evidenceId"])
        if (evidence["fullFingerprint"] != full or evidence["packageFingerprint"] != image["preservation"]["packageFingerprint"]
                or sorted(evidence["nativeSheetIds"]) != sorted(s["sheetId"] for s in image["sheets"])
                or evidence["semanticFingerprint"] != image_fingerprint(image)):
            raise _fail("DP_BACKUP_FAILED", "Native package capture does not match this semantic image and native identities")
        result=deepcopy(image);result["_nativeEvidence"]=evidence["evidence"]
        return result

    @staticmethod
    def _native_identity(image):
        return canonical_hash(sorted(s["sheetId"] for s in image["sheets"]))


    def _attempt(self, transport, preparation_id, attempt_id):
        d = self._get(transport, preparation_id, allow_closing=True)
        a = d.get("attempt")
        if not a or a["attemptId"] != attempt_id:
            raise _fail("DP_POINT_EXPIRED", "Attempt is unavailable for this workbook attachment")
        if a["phase"] == "partial_unknown": raise _fail("DP_PARTIAL_UNKNOWN", "Previous native write requires reconciliation")
        return d, a

    def image_begin(self, transport, preparation_id, attempt_id, purpose, byte_length, image_hash):
        with self._lock:
            self._require_backup_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            require_hash(image_hash)
            allowed = {"restore-readback"} if a.get("direction") else {"before", "after"}
            if purpose not in allowed or purpose in a["images"] or any(u["purpose"] == purpose for u in a["uploads"].values()):
                raise _fail("DP_BACKUP_FAILED", "Duplicate or unsupported attempt image")
            if (purpose == "before" and a["phase"] != "prepared" or purpose != "before" and a["phase"] != "writing"):
                raise _fail("DP_BACKUP_FAILED", "Image purpose does not match attempt phase")
            if type(byte_length) is not int or not 0 < byte_length <= MAX_IMAGE_BYTES:
                raise _fail("DP_BACKUP_LIMIT", "Image exceeds the bounded semantic envelope")
            # Process-wide outstanding transfer buffers are charged before receiving chunks.
            pending = sum(u["length"] for doc in self._documents.values() for u in (doc.get("attempt") or {}).get("uploads", {}).values())
            if pending + byte_length > 32 * 1024 * 1024:
                raise _fail("DP_BACKUP_LIMIT", "Pending image transfers exceed the process budget")
            self._sync_upload_budget(extra=byte_length)
            uid = uuid4().hex
            a["uploads"][uid] = {"purpose": purpose, "length": byte_length, "hash": image_hash, "data": bytearray(), "chunks": []}
            return {"uploadId": uid, "maxChunkBytes": 1048576}

    def image_chunk(self, transport, preparation_id, attempt_id, upload_id, index, offset, chunk_hash, data_base64):
        with self._lock:
            self._require_backup_mode()
            _, a = self._attempt(transport, preparation_id, attempt_id)
            u = a["uploads"].get(upload_id)
            try: data = base64.b64decode(data_base64, validate=True)
            except (ValueError, TypeError) as exc: raise _fail("INVALID_REQUEST", "Invalid image chunk encoding") from exc
            if not u or not 0 < len(data) <= 1048576 or _digest(data) != chunk_hash or type(index) is not int or type(offset) is not int:
                raise _fail("DP_BACKUP_FAILED", "Invalid bounded image chunk")
            if 0 <= index < len(u["chunks"]):
                old_offset, old_length, old_hash = u["chunks"][index]
                if (offset, len(data), chunk_hash) != (old_offset, old_length, old_hash) or u["data"][offset:offset + len(data)] != data:
                    raise _fail("DP_BACKUP_FAILED", "Conflicting image chunk retry")
            elif index == len(u["chunks"]) and offset == len(u["data"]) and offset + len(data) <= u["length"]:
                u["data"].extend(data); u["chunks"].append((offset, len(data), chunk_hash))
            else: raise _fail("DP_BACKUP_FAILED", "Image chunks must be sequential without overlap")
            return {"uploadId": upload_id, "receivedBytes": len(u["data"])}

    def _expected_image(self, d, a, before):
        expected = self._semantic_image(before); expected.pop("fingerprint", None)
        expected.pop("preservation",None);expected.pop("fullFingerprint",None)
        by_id = {s["sheetId"]: s for s in expected["sheets"]}
        if a["kind"] == "import":
            if set(a["target"]["sheetIds"]) - set(by_id): raise _fail("DP_SOURCE_STALE", "Reviewed destination sheets changed")
            occupied = {s["name"].casefold() for s in expected["sheets"]}
            for package in a["packages"]:
                for sheet in package["sheets"]:
                    if sheet["targetName"].casefold() in occupied: raise _fail("DP_SOURCE_STALE", "Destination name is now occupied")
                    occupied.add(sheet["targetName"].casefold())
                    expected["sheets"].append({"sheetId": sheet["sourceSheetId"], "name": sheet["targetName"],
                        **{k: deepcopy(sheet[k]) for k in ("rowOffset", "columnOffset", "values", "formulas", "formulaCells", "numberFormats")}})
        else:
            for source in d["scan"].sources:
                sheet = by_id.get(source.sheet_id)
                if sheet is None: raise _fail("DP_SOURCE_STALE", "Reviewed cleanup sheet disappeared")
                for r, row in enumerate(source.rows):
                    for c, value in enumerate(row):
                        rr, cc = source.row_offset + r - sheet["rowOffset"], source.column_offset + c - sheet["columnOffset"]
                        if rr < 0 or cc < 0 or rr >= len(sheet["values"]) or cc >= len(sheet["values"][rr]) or sheet["values"][rr][cc] != value or ([rr, cc] in sheet["formulaCells"]) != ((r, c) in source.formula_cells) or sheet["numberFormats"][rr][cc] != source.number_formats[r][c]:
                            raise _fail("DP_SOURCE_STALE", "Fresh workbook does not match reviewed cleanup data/formulas/formats")
            if a["target"]["strategy"] == "personal_copy":
                used = {s["name"] for s in expected["sheets"]}
                for sid in a["target"]["sheetIds"]:
                    if sid in d.get("importedSheetIds", []):
                        continue
                    original = by_id[sid]
                    # validate_copy_targets independently rejects explicit
                    # self-reference rewrites before native copying begins.
                    name = safe_sheet_name(original["name"] + "_Result", used)
                    copied = deepcopy(original); copied.update(sheetId="copy_" + uuid4().hex, name=name)
                    expected["sheets"].append(copied); by_id[sid] = copied
                    a["targetCopies"].append({"sourceSheetId": sid, "targetName": name})
            for change in a["changes"]:
                sheet = by_id[change["sheetId"]]
                r, c = change["row"] - sheet["rowOffset"], change["column"] - sheet["columnOffset"]
                if [r, c] in sheet["formulaCells"]: raise _fail("DP_SOURCE_STALE", "A reviewed literal became a formula")
                sheet["values"][r][c] = sheet["formulas"][r][c] = change["after"]
                if change["numberFormat"] is not None: sheet["numberFormats"][r][c] = change["numberFormat"]
        expected["fingerprint"] = image_fingerprint(expected)
        return expected

    @staticmethod
    def _native_changes(attempt, before):
        names = {sheet["sheetId"]: sheet["name"] for sheet in before["sheets"]}
        copies = {copy["sourceSheetId"]: copy["targetName"] for copy in attempt.get("targetCopies", [])}
        changes = []
        for change in attempt["changes"]:
            name = names.get(change["sheetId"])
            if name is None:
                raise _fail("DP_SOURCE_STALE", "Approved native delta identity is absent")
            changes.append({**change, "sheetName": copies.get(change["sheetId"], name)})
        return changes

    def _verify_native_result(self, attempt, image):
        from .package_preservation import verify_package_import, verify_package_copy_undo
        before = attempt["currentImage"] if attempt.get("direction") else attempt["images"]["before"]["image"]
        left, right = before["_nativeEvidence"], image["_nativeEvidence"]
        copies = [{"sourceName": next(s["name"] for s in before["sheets"] if s["sheetId"] == copy["sourceSheetId"]),
                   "targetName": copy["targetName"]} for copy in attempt.get("targetCopies", [])]
        if attempt.get("direction") == "undo":
            if attempt["kind"] == "import" or copies:
                removed = [s["name"] for s in before["sheets"] if s["name"] not in {s["name"] for s in image["sheets"]}]
                owned_names = [item["targetName"] for package in attempt["packages"] for item in package.get("namespace", {}).get("names", []) if item.get("scope") == "workbook"]
                if copies:
                    inverse = [{**change, "before": change["after"], "after": change["before"], "numberFormat": change["beforeNumberFormat"]}
                               for change in self._native_changes(attempt, before) if change["sheetName"] not in removed]
                    return verify_package_copy_undo(left, right, removed, inverse)
                return verify_package_group(left, right, deleted_sheet_names=removed, owned_defined_names=owned_names)
            changes = [{**change, "before": change["after"], "after": change["before"], "numberFormat": change["beforeNumberFormat"]}
                       for change in self._native_changes(attempt, before)]
            return verify_package_delta(left, right, changes)
        if attempt["kind"] == "import":
            return verify_package_import(left, right, attempt["packages"])
        changes = self._native_changes(attempt, before)
        return verify_package_copy_delta(left, right, copies, changes) if copies else verify_package_delta(left, right, changes)

    def image_finish(self, transport, preparation_id, attempt_id, upload_id):
        with self._lock:
            self._require_backup_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            u = a["uploads"].get(upload_id)
            if not u or len(u["data"]) != u["length"] or _digest(u["data"]) != u["hash"]:
                raise _fail("DP_BACKUP_FAILED", "Complete image length/hash verification failed")
            try: image = json.loads(u["data"].decode("utf-8"))
            except (ValueError, UnicodeError) as exc: raise _fail("DP_BACKUP_FAILED", "Invalid semantic image JSON") from exc
            image = self._resolve_native_image(transport,image)
            fingerprint = image_fingerprint(self._semantic_image(image))
            full_fingerprint = image_full_fingerprint(self._semantic_image(image),image["_nativeEvidence"]["fingerprint"])
            purpose = u["purpose"]
            if purpose == "before":
                if fingerprint != a["beforeFingerprint"]: raise _fail("DP_SOURCE_STALE", "Before image differs from the fresh begin fingerprint")
                if full_fingerprint != a["beforePreservationFingerprint"] or self._native_identity(image) != d["nativeIdentityHash"]:
                    raise _fail("DP_SOURCE_STALE", "Before native package or native identities differ from the reviewed binding")
                a["targetCopies"] = []
                expected = self._expected_image(d, a, image)
                a["expectedImage"] = expected
                if a["kind"] == "cleanup":
                    targets = [{**change, "sheetName": next(s["name"] for s in image["sheets"] if s["sheetId"] == change["sheetId"])} for change in a["changes"]]
                    validate_delta_targets(image["_nativeEvidence"], targets)
                    validate_copy_targets(image["_nativeEvidence"], [next(s["name"] for s in image["sheets"] if s["sheetId"] == copy["sourceSheetId"]) for copy in a["targetCopies"]])
                scope = OperationScope(a["kind"], tuple(s["sheetId"] for s in image["sheets"]), fingerprint, expected["fingerprint"])
                reservation = self._recovery().reserve_restore_point(d["id"], scope, 2 * 64 * 1024 * 1024 + RECEIPT_RESERVE)
                a["reservation"] = reservation.reservation_id
                a["expectedFingerprint"] = expected["fingerprint"]
            elif fingerprint != a["expectedFingerprint"]:
                # Preserve readback even on mismatch; complete records partial/unknown.
                a["readbackMismatch"] = True
            native_verified = purpose == "before"
            if purpose != "before":
                try:
                    self._verify_native_result(a, image)
                    native_verified = True
                except InputError:
                    a["readbackMismatch"] = True
            data = _encode(image)
            if len(data)>64*1024*1024:
                raise _fail("DP_BACKUP_LIMIT", "Complete canonical native recovery image exceeds 64 MiB")
            image_id = self._recovery().store_image(a["reservation"], purpose, data, _digest(data)) if purpose != "restore-readback" else uuid4().hex
            a["images"][purpose] = {"imageId": image_id, "image": image, "fingerprint": fingerprint, "fullFingerprint":full_fingerprint, "nativeVerified":native_verified}
            del a["uploads"][upload_id]
            self._sync_upload_budget()
            return {"imageId": image_id, "fingerprint": fingerprint, "fullFingerprint":full_fingerprint, "expectedFingerprint": a["expectedFingerprint"],
                    "targetCopies": deepcopy(a["targetCopies"])}

    def write_ready(self, transport, preparation_id, attempt_id, before_image_id, expected_fingerprint, expected_preservation_fingerprint=None):
        with self._lock:
            self._require_backup_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            self._require_native_write(d)
            self._check_preservation_head(d,expected_preservation_fingerprint)
            if expected_preservation_fingerprint != a["beforePreservationFingerprint"]:
                raise _fail("DP_RESTORE_CONFLICT", "Native preservation head changed before write")
            if a["phase"] != "prepared": raise _fail("DP_REVIEW_STALE", "Write permit has already been consumed")
            if expected_fingerprint != a["beforeFingerprint"]: raise _fail("DP_SOURCE_STALE", "Workbook changed immediately before native write")
            if a.get("direction"):
                if before_image_id != a["imageId"]: raise _fail("DP_BACKUP_FAILED", "Restore image changed")
                self._recovery().mark_restore_started(attempt_id, expected_fingerprint)
            else:
                saved = a["images"].get("before")
                if not saved or saved["imageId"] != before_image_id: raise _fail("DP_BACKUP_FAILED", "Verified before image is required")
                if self._current_review(d, a["kind"]) != a["reviewHash"]: raise _fail("DP_REVIEW_STALE", "Review changed before native write")
                self._recovery().mark_write_started(a["reservation"], expected_fingerprint)
            a["phase"] = "writing"; d["status"] = "writing"
            return {"attemptId": attempt_id, "writePermit": a["writePermit"], "currentFingerprint": expected_fingerprint, "currentPreservationFingerprint":expected_preservation_fingerprint, "operation": a["operation"]}

    def complete_mutation(self, transport, preparation_id, attempt_id, receipt):
        with self._lock:
            self._require_backup_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            if receipt.get("phase") == "prewrite_failed" and a["phase"] == "prepared":
                if a["reservation"]: self._recovery().abort_attempt(a["reservation"])
                d.update(attempt=None, status="needs_review")
                self._sync_upload_budget()
                return self._public(d)
            if a["phase"] != "writing": raise _fail("DP_BACKUP_FAILED", "No native write is awaiting a receipt")
            saved = a["images"].get("after")
            verified = (saved is not None and saved.get("nativeVerified") is True and receipt.get("imageId") == saved["imageId"]
                and receipt.get("phase") == "verified" and receipt.get("observedFingerprint") == saved["fingerprint"] == a["expectedFingerprint"])
            if verified:
                before_ids = {s["sheetId"] for s in a["images"]["before"]["image"]["sheets"]}
                after_sheets = saved["image"]["sheets"]
                created = [s["sheetId"] for s in after_sheets if s["sheetId"] not in before_ids]
                original_by_name = {s["name"]: s["sheetId"] for s in a["images"]["before"]["image"]["sheets"]}
                verified = (set(created) == set(receipt.get("actualSheetIds", [])) and all(
                    s["sheetId"] == original_by_name[s["name"]] for s in after_sheets if s["name"] in original_by_name))
            journal = self._recovery().complete_attempt(a["reservation"], {"phase": "verified" if verified else "partial_unknown", "observedFingerprint": saved["fingerprint"] if saved else None})
            if verified and journal["status"] == "ready":
                point_id = journal["points"][-1]["pointId"]
                self._points[point_id] = {"lineage": d["id"], "kind": a["kind"], "packages": a["packages"], "createdSheetIds": created,
                    "beforeFingerprint": a["beforeFingerprint"], "afterFingerprint": a["expectedFingerprint"],
                    "changes": deepcopy(a["changes"]), "targetCopies": deepcopy(a["targetCopies"]),
                    "beforeNames": [s["name"] for s in a["images"]["before"]["image"]["sheets"]],
                    "beforeIds": {s["name"]: s["sheetId"] for s in a["images"]["before"]["image"]["sheets"]},
                    "afterIds": {s["name"]: s["sheetId"] for s in after_sheets}}
                for copy in a["targetCopies"]:
                    actual_id = next(s["sheetId"] for s in after_sheets if s["name"] == copy["targetName"])
                    for change in self._points[point_id]["changes"]:
                        if change["sheetId"] == copy["sourceSheetId"]: change["sheetId"] = actual_id
                if a["kind"] == "import": d["importedSheetIds"] = sorted(set(d.get("importedSheetIds", [])) | set(created))
                d.update(attempt=None, status="verified", claimFingerprint=a["expectedFingerprint"], preservationFingerprint=saved["fullFingerprint"], nativeIdentityHash=self._native_identity(saved["image"]), nativeSheetIds={s["name"]: s["sheetId"] for s in saved["image"]["sheets"]}, preview=None, needsReview=True)
                self._prune_point_metadata()
            else:
                a["phase"] = "partial_unknown"; d["status"] = "partial_unknown"
            return self._finished_state(d)

    def checkout_recovery(self, transport, preparation_id, point_id, direction, expected_cursor, expected_fingerprint, expected_preservation_fingerprint=None):
        with self._lock:
            self._require_backup_mode()
            d = self._get(transport, preparation_id)
            self._require_native_write(d)
            self._check_preservation_head(d,expected_preservation_fingerprint)
            if d.get("attempt"): raise _fail("DP_PARTIAL_UNKNOWN", "Finish the existing attempt first")
            current_image = json.loads(self._recovery().read_current_image(d["id"]))
            # Only identities observed in a completed owner-verified receipt may
            # rebind immutable journal payloads after native owned-sheet Redo.
            for sheet in current_image["sheets"]:
                sheet["sheetId"] = d.get("nativeSheetIds", {}).get(sheet["name"], sheet["sheetId"])
            if self._native_identity(current_image) != d["nativeIdentityHash"]:
                raise _fail("DP_RESTORE_CONFLICT", "Current native identities differ from the verified head")
            if current_image["fullFingerprint"] != expected_preservation_fingerprint:
                raise _fail("DP_RESTORE_CONFLICT", "Committed native head differs from recovery request")
            restore = self._recovery().checkout_restore(d["id"], point_id, direction, expected_cursor, expected_fingerprint)
            image = json.loads(self._recovery().read_restore(restore.attempt_id))
            metadata = self._points.get(point_id, {})
            a = {"attemptId": restore.attempt_id, "kind": metadata.get("kind", "cleanup"), "operation": direction,
                "direction": direction, "pointId": point_id, "beforeFingerprint": expected_fingerprint, "beforePreservationFingerprint":expected_preservation_fingerprint,
                "expectedFingerprint": image_fingerprint(self._semantic_image(image)), "targetPreservationFingerprint":image["fullFingerprint"], "writePermit": uuid4().hex, "phase": "prepared",
                "scope": {"fullWorkbook": True, "sheetIds": []}, "image": image, "imageId": uuid4().hex,
                "packages": metadata.get("packages", []), "createdSheetIds": metadata.get("createdSheetIds", []),
                "changes": deepcopy(metadata.get("changes", [])),
                "uploads": {}, "images": {}, "reservation": None, "targetCopies": deepcopy(metadata.get("targetCopies", [])), "currentImage": current_image}
            if direction == "redo":
                for copy in a["targetCopies"]:
                    previous_id = metadata["afterIds"].get(copy["targetName"])
                    for change in a["changes"]:
                        if change["sheetId"] == previous_id: change["sheetId"] = copy["sourceSheetId"]
            old_names = {sid: name for table in (metadata.get("beforeIds", {}), metadata.get("afterIds", {})) for name, sid in table.items()}
            current_ids = {sheet["name"]: sheet["sheetId"] for sheet in current_image["sheets"]}
            for change in a["changes"]:
                change["sheetId"] = current_ids.get(old_names.get(change["sheetId"]), change["sheetId"])
            for copy in a["targetCopies"]:
                copy["sourceSheetId"] = current_ids.get(old_names.get(copy["sourceSheetId"]), copy["sourceSheetId"])
            d.update(attempt=a, grant=None, status="restore_pending")
            return self._attempt_public(a)

    def complete_recovery(self, transport, preparation_id, attempt_id, receipt):
        with self._lock:
            self._require_backup_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            if a.get("direction") and a["phase"] == "prepared" and receipt.get("phase") == "prewrite_failed":
                self._recovery().abort_restore(attempt_id)
                d.update(attempt=None, status="needs_review")
                self._sync_upload_budget()
                return self._finished_state(d)
            if not a.get("direction") or a["phase"] != "writing": raise _fail("DP_REVIEW_STALE", "No restore write awaits completion")
            saved = a["images"].get("restore-readback")
            verified = (saved is not None and saved.get("nativeVerified") is True and receipt.get("imageId") == saved["imageId"] and receipt.get("phase") == "verified"
                and receipt.get("observedFingerprint") == saved["fingerprint"] == a["expectedFingerprint"])
            if verified:
                metadata = self._points[a["pointId"]]
                expected_ids = metadata["beforeIds"] if a["direction"] == "undo" else metadata["afterIds"]
                recreated_names = set(metadata["afterIds"]) - set(metadata["beforeIds"]) if a["direction"] == "redo" else set()
                current_ids = {s["name"]: s["sheetId"] for s in a["currentImage"]["sheets"]}
                actual_created = [s["sheetId"] for s in saved["image"]["sheets"] if s["name"] not in current_ids]
                verified = (set(actual_created) == set(receipt.get("actualSheetIds", [])) and all(
                    s["name"] in recreated_names or s["sheetId"] == current_ids.get(s["name"], expected_ids.get(s["name"]))
                    for s in saved["image"]["sheets"]))
            journal = self._recovery().finish_restore(attempt_id, {"phase": "verified" if verified else "partial_unknown", "observedFingerprint": saved["fingerprint"] if saved else None})
            if verified and journal["status"] == "ready":
                if a["kind"] == "import":
                    ids = set(d.get("importedSheetIds", [])) - set(a["createdSheetIds"])
                    if a["direction"] == "redo":
                        before_names = set(self._points[a["pointId"]]["beforeNames"])
                        created = [s["sheetId"] for s in saved["image"]["sheets"] if s["name"] not in before_names]
                        ids.update(created); self._points[a["pointId"]]["createdSheetIds"] = created
                    d["importedSheetIds"] = sorted(ids)
                d.update(attempt=None, status="verified", claimFingerprint=a["expectedFingerprint"], preservationFingerprint=saved["fullFingerprint"], nativeIdentityHash=self._native_identity(saved["image"]), nativeSheetIds={s["name"]: s["sheetId"] for s in saved["image"]["sheets"]}, preview=None, needsReview=True)
            else: a["phase"] = d["status"] = "partial_unknown"
            return self._finished_state(d)

    def _finished_state(self, document):
        result = self._public(document)
        if document.get("closing"):
            result.update(status="expired", writeEnabled=False, writeBlocker="DP_POINT_EXPIRED")
            self._drop(document)
        return result
