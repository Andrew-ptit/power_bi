"""Locked, local Assistant v2 WL1/WL2 state; approval authority is added in wave E.

This store does not yet hold approval capabilities. Root paths and raw rows stay
private; every public method holds the reentrant lock and returns owned copies.
"""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
import base64
import hashlib
import json
from pathlib import Path
import random
import stat
from threading import RLock
from time import perf_counter
import secrets

from pbip_assistant.errors import InputError
from . import assistant_ingest as ingest_engine
from .assistant_ingest import canonical_hash, MODE_COMPUTE, MODE_DISCOVER
from .assistant_profile import build_snapshot, snapshot_hash
from .assistant_understand import build_understand, _bind_raw, _HASH_BASIS, understand_hash
from .assistant_keys import has_finance_schema, key_report
from .assistant_roles import assumption_ledger, warning_classification
from .assistant_model_view import build_model_view, grain_kind
from pbip_assistant.powerquery.typed_local import execute_plan
from .assistant_reconcile_v2 import (ENGINE, build_preview, reconcile_v2, build_ab_delta,
                                     bind_ab_identity, ab_identity_passed)
from .assistant_freeze import (build_frozen_spec, validate_frozen_spec, assert_freezable,
                               timestamp, workbook_identity, result_marker)
from .assistant_approval import issue_approval_v2, validate_approval_v2, consume_approval, approval_state
from .assistant_apply import verify_values_only, _package, _metadata, MAX_PACKAGE_BYTES
from .assistant_record_v2 import (build_v2_record, compute_v2_delta, record_node,
                                  detect_stale_v2, record_hash_v2)


_STAGES = ("new", "ingested", "understood", "planning", "branched", "frozen", "approved", "handoff", "partial", "applied", "recorded")
_MODES = (MODE_DISCOVER, MODE_COMPUTE)
_CACHE_MAX_BYTES = 64 * 1024 * 1024
_PREVIEW_MAX_BYTES = 1024 * 1024
# The single place that recognises bounded WL2 limit errors (task 403 item 5).
_WL2_LIMIT_MARKERS = ("exceeds the bounded",)


def _capture_apply_error_authority(*, may_prove_preconsume):
    """Bind rejection evidence before reset/another request can change the store.

    This flag describes the rejected attempt only; it does not grant a retry or
    replace any of the existing approval checks.
    """
    def decorate(operation):
        @wraps(operation)
        def guarded(self, *args, **kwargs):
            with self._lock:
                try:
                    return operation(self, *args, **kwargs)
                except (InputError, ValueError) as exc:
                    consumed = (self._write_attempted
                                or (self._approval is not None and self._approval.get("consumed") is True))
                    if consumed or may_prove_preconsume:
                        exc.assistant_approval_consumed = consumed
                    # A receipt refers to an earlier handoff. An empty/reset
                    # store cannot establish that earlier attempt's outcome.
                    raise
        return guarded
    return decorate


def _table_content_hash(raw: dict) -> str:
    return canonical_hash({key: raw[key] for key in ("header", "rows", "mode", "totalRows", "sampleOrdinals")})


def _questions(snapshot: dict, understand: dict, grain_proposals: dict | None = None) -> list[dict]:
    """Produce deterministic review questions from measured, non-AI evidence.

    `grain_proposals` maps tableId → (grainKind, grainEvidence) per spec 004 §6;
    when provided, snapshot tables get a `grain` confirmation question (contract §5).
    """
    result = []

    def add(topic, question, evidence, options=None):
        content = {"topic": topic, "question": question,
                   "whyItMatters": "Lựa chọn này ảnh hưởng cách hiểu và kế hoạch xử lý dữ liệu.",
                   "kind": "single_choice" if options else "text",
                   "options": options or [], "evidence": deepcopy(evidence), "source": "data"}
        result.append({"id": "q_" + canonical_hash(content)[7:19], **content})

    for warning in understand["warnings"]:
        add("warning", "Cần xác nhận cảnh báo: " + str(warning.get("message", warning.get("detail", warning.get("code", "")))),
            [{"kind": "warning", "value": deepcopy(warning)}])
    for link in understand["relationships"]:
        if link.get("status") == "needs_confirm" or link.get("fanOutRisk") == "high":
            add("relationship", "Xác nhận nối " + link["fromTable"] + " với " + link["toTable"] + " theo khóa đã đề xuất?"
                + (" Nguy cơ nhân dòng cao." if link.get("fanOutRisk") == "high" else ""),
                [{"kind": "relationship", "ref": link["id"], "value": deepcopy(link)}],
                ["Xác nhận", "Không nối", "Cần làm rõ"])
    for role in understand["roles"]:
        if role.get("confidence", 0) < 0.75:
            add("role", "Vai trò đề xuất của bảng/cột này đã đúng chưa?",
                [{"kind": "role", "value": deepcopy(role)}], ["Đúng", "Cần sửa"])
    if not understand["roles"]:
        add("role", "Chưa đủ bằng chứng cấu trúc; các bảng này đóng vai trò gì trong báo cáo?",
            [{"kind": "stats", "value": {"tableCount": len(snapshot["tables"]),
               "rowCount": sum(t["rowCount"] for t in snapshot["tables"])}}])
    for table in snapshot["tables"]:
        for column in table["columns"]:
            if column["nullRate"] > 0.2:
                add("nulls", "Cột " + table["name"] + "." + column["name"] + " có nhiều ô trống; xử lý thế nào?",
                    [{"kind": "stats", "ref": table["id"], "value": "nullRate=" + str(column["nullRate"])}],
                    ["Giữ trống", "Bỏ dòng", "Coi là 0", "Cần làm rõ"])
    for assumption in understand["assumptions"]:
        add("assumption", "Xác nhận giả định: " + assumption["statement"],
            [{"kind": "assumption", "value": deepcopy(assumption)}], ["Đúng", "Không đúng", "Chưa rõ"])
    if grain_proposals:
        roles_by_table = {role["tableId"]: role for role in understand["roles"]}
        for table in snapshot["tables"]:
            kind, evidence = grain_proposals.get(table["id"], ("unknown", None))
            if kind != "snapshot":
                continue
            role = roles_by_table.get(table["id"])
            structural = role["structural"] if role else "unclassified"
            if structural in ("dim", "lookup"):
                continue
            add("grain", f"Bảng {table['name']} là ảnh chụp theo ngày (không cộng dồn số liệu qua các ngày)?",
                [{"kind": "grain", "ref": table["id"], "value": evidence}],
                ["Đúng, là ảnh chụp", "Không, là sự kiện", "Chưa rõ"])
    return sorted(result, key=lambda item: item["id"])


class AssistantSessionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self.reset()

    def reset(self) -> dict:
        with self._lock:
            if hasattr(self, "_session"):
                ingest_engine.close(self._session)
            self._session = {}
            self._root = None
            self._workbook_only = False
            self._ingested = None
            self._raw_tables = []
            self._snapshot = None
            self._understand = None
            self._model_view = None
            self._questions = []
            self._planning = None
            self._branch_results = {}
            self._execution_cache = {}
            self._cache_bytes = 0
            self._delta = None
            self._stage = "new"
            self._mode = None
            self._ingest_requests = []
            self._clear_write_state()
            return self.state()

    def _clear_write_state(self):
        self._frozen_spec = None
        self._chosen_branch = None
        self._approval = None
        self._handoff = None
        self._apply_receipt = None
        self._write_attempted = False
        self._record = None
        self._record_node = None

    def close(self) -> None:
        with self._lock:
            self.reset()
            ingest_engine.close(self._session)

    def bind_workbook(self) -> dict:
        """Start local workbook-only analysis without granting filesystem access."""
        with self._lock:
            self.reset()
            self._workbook_only = True
            return self.state()

    def _bind_fresh(self, fresh):
        if self._workbook_only:
            fresh.bind_workbook()
        else:
            fresh.bind_root(str(self._root))

    def bind_root(self, root) -> dict:
        with self._lock:
            try:
                if not isinstance(root, str) or not root or not Path(root).is_absolute():
                    raise ValueError("Absolute root required")
                requested = Path(root)
                if ".." in requested.parts:
                    raise ValueError("Traversal is unsupported")
                for component in (requested, *requested.parents):
                    attributes = component.lstat()
                    if component.is_symlink() or getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise ValueError("Reparse roots are unsupported")
                resolved = requested.resolve(strict=True)
                if not resolved.is_dir():
                    raise ValueError("Root must be a directory")
            except (OSError, ValueError, TypeError):
                raise InputError("ASSISTANT_ROOT_INVALID", "root", "Chọn thư mục tuyệt đối đang tồn tại, không qua reparse point.") from None
            self.reset()
            self._root = resolved
            self._session["root"] = resolved
            return {**self.state(), "limits": {"maxFileBytes": ingest_engine.MAX_BYTES_PER_FILE,
                    "maxSessionBytes": ingest_engine.MAX_BYTES_PER_SESSION, "sampleRows": 20,
                    "maxRows": 100_000, "maxColumns": 256}}

    def ingest(self, requests, expected_planning_hash=None) -> dict:
        with self._lock:
            if self._root is None and not self._workbook_only:
                raise InputError("AF_STAGE_INVALID", "stage", "Chọn thư mục phiên trước khi nạp nguồn.")
            if not isinstance(requests, list) or not requests or any(not isinstance(r, dict) for r in requests):
                raise InputError("INVALID_REQUEST", "requests", "Cần danh sách nguồn được chọn.")
            if self._workbook_only and any(request.get("kind") != "workbook" for request in requests):
                raise InputError("ASSISTANT_WORKBOOK_REQUIRED", "requests", "Phiên này chỉ đọc dữ liệu trong workbook đang mở.")
            modes = [request.get("mode") for request in requests]
            if any(mode not in _MODES for mode in modes) or len(set(modes)) != 1:
                raise InputError("INVALID_REQUEST", "mode", "Mọi nguồn phải cùng chế độ discover hoặc compute.")
            mode = modes[0]
            prior_planning = None
            if expected_planning_hash is not None:
                if not isinstance(expected_planning_hash, str):
                    raise InputError("INVALID_REQUEST", "expectedPlanningHash", "Expected planning binding must be text")
                if (mode != MODE_COMPUTE or self._stage not in ("planning", "branched") or self._planning is None
                        or expected_planning_hash != self._planning["planningHash"]):
                    raise InputError("AF_SPEC_STALE", "expectedPlanningHash", "Kế hoạch đã đổi; hãy tạo lại trước khi đọc toàn bộ.")
                prior_planning = deepcopy(self._planning)
            result = self._collect_ingest_parts(requests, mode)
            self._session["_assistant_ingest"] = deepcopy(result)
            self._ingested = result
            self._raw_tables = deepcopy(result["tables"])
            self._snapshot = self._understand = self._model_view = None
            self._questions = []
            self._planning = None
            self._branch_results = {}
            self._execution_cache = {}
            self._cache_bytes = 0
            self._delta = None
            self._mode = mode
            self._ingest_requests = deepcopy(requests)
            self._clear_write_state()
            blocked = bool(result["errors"] or result["requiresRename"] or not result["tables"]
                           or any(item.get("needsClarification") for item in result["csvOptions"]))
            self._stage = "new" if blocked else "ingested"
            if not blocked:
                self._snapshot = build_snapshot(result)
                self._snapshot["snapshot"]["mode"] = mode
                by_name = {raw["name"]: raw for raw in self._raw_tables}
                for table in self._snapshot["tables"]:
                    raw = by_name[table["name"]]
                    table.update({key: deepcopy(raw[key]) for key in ("mode", "sampleOrdinals", "totalRows")})
                    table["contentHash"] = _table_content_hash(raw)
                self._snapshot["snapshotHash"] = snapshot_hash(self._snapshot)
                if prior_planning is not None:
                    # A discover plan survives the explicit full-data read only
                    # when its complete source schema still matches. Actual
                    # numbers remain absent until wave D executes the plans.
                    from pbip_assistant.adapters.codex.assistant_plan import assistant_source_catalog, validate_branch_response, planning_hash
                    sources = assistant_source_catalog(self._snapshot)
                    old_sources = prior_planning["branches"][0]["plan"]["sources"]
                    signature = lambda catalog: [(source["sourceId"], [(column["name"], column["inferredType"]) for column in source["columns"]]) for source in catalog]
                    if signature(sources) == signature(old_sources):
                        response = {key: deepcopy(prior_planning[key]) for key in ("summary", "questions", "assumptions")}
                        response["branches"] = [{**{key: deepcopy(branch[key]) for key in ("id", "label", "rationale", "controlTotal", "maxFanOut")},
                                                  "plan": deepcopy(branch["draft"])} for branch in prior_planning["branches"]]
                        self.understand()
                        self._planning = validate_branch_response(response, sources)
                        self._planning["requestHash"] = prior_planning["requestHash"]
                        self._planning["draftInputs"] = deepcopy(prior_planning["draftInputs"])
                        self._planning["planningHash"] = planning_hash(self._planning)
                        self._stage = "planning"
            return {**self.state(), "stage": "ingest_blocked" if blocked else self._stage,
                    "snapshot": deepcopy(self._snapshot), "sources": deepcopy(result["sources"]),
                    "tables": deepcopy(self._snapshot["tables"]) if self._snapshot else [],
                    **{key: deepcopy(result[key]) for key in ("errors", "requiresRename", "csvOptions", "warnings")}}

    def _collect_ingest_parts(self, requests: list[dict], mode: str) -> dict:
        """Resolve every selected source, enforce the byte limit and merge identities."""
        result = ingest_engine._empty()
        for request_index, request in enumerate(requests):
            if request.get("kind") == "workbook":
                payload = request.get("payload")
                if isinstance(payload, dict):
                    payload = {**payload, "mode": mode}
                part = ingest_engine.add_workbook_selection(payload)
                if request.get("name") is not None and part["tables"]:
                    part["tables"][0]["name"] = str(request["name"])
            else:
                part = ingest_engine.resolve({"root": self._root}, [request])
                if part["csvOptions"]:
                    selected = Path(request["path"])
                    if not selected.is_absolute():
                        selected = self._root / selected
                    # resolve has already confined this selection to root;
                    # even ambiguous CSVs need a public locator for retry.
                    origin = selected.resolve(strict=True).relative_to(self._root).as_posix()
                    for option in part["csvOptions"]:
                        option.update(origin=origin, requestIndex=request_index)
                for raw in part["tables"]:
                    total = len(raw["rows"])
                    if total == 0:
                        ingest_engine._fail(part, raw["name"], "Empty selections are unsupported")
                        raw.update(mode=mode, totalRows=0, sampleOrdinals=[])
                        continue
                    header_json = json.dumps(raw["header"], ensure_ascii=False, separators=(",", ":"))
                    seed_content = "|".join((header_json, str(total), str(len(raw["header"])),
                                             canonical_hash(raw["rows"][0]), canonical_hash(raw["rows"][-1])))
                    seed = hashlib.sha256(seed_content.encode("utf-8")).hexdigest()
                    ordinals = (list(range(total)) if total <= 20 else
                                sorted([0, total - 1, *random.Random(seed).sample(range(1, total - 1), 18)]))
                    raw.update(mode=mode, totalRows=total, sampleOrdinals=ordinals)
                    if mode == MODE_DISCOVER:
                        raw["rows"] = [raw["rows"][n] for n in ordinals]
            if result["sessionBytes"] + part["sessionBytes"] > ingest_engine.MAX_BYTES_PER_SESSION:
                ingest_engine._fail(result, "sources", "Session byte limit exceeded")
                break
            for key in ("sources", "tables", "csvOptions", "errors", "warnings"):
                result[key].extend(part[key])
            result["sessionBytes"] += part["sessionBytes"]
        if result["sessionBytes"] > ingest_engine.MAX_BYTES_PER_SESSION:
            ingest_engine._fail(result, "sources", "Session byte limit exceeded")
        result["sources"].sort(key=lambda item: (item["name"], item["id"]))
        result["tables"].sort(key=lambda item: (item["name"], item["sourceId"]))
        result["requiresRename"] = ingest_engine._rename_entries(result["tables"])
        # Multiple selections of one workbook/file share source identity.
        unique_sources, source_hashes = {}, {}
        for source in result["sources"]:
            unique_sources.setdefault(source["id"], deepcopy(source))
            source_hashes.setdefault(source["id"], set()).add(source["hash"])
        for source_id, hashes in source_hashes.items():
            if len(hashes) > 1:
                unique_sources[source_id]["hash"] = canonical_hash(sorted(hashes))
        result["sources"] = list(unique_sources.values())
        return result

    def understand(self) -> dict:
        with self._lock:
            if self._stage not in ("ingested", "understood") or self._snapshot is None:
                raise InputError("AF_STAGE_INVALID", "stage", "Nạp nguồn không có blocker trước khi hiểu dữ liệu.")
            try:
                self._verify_source_binding()
                model = build_understand(self._raw_tables, self._snapshot)
            except ValueError as exc:
                if any(marker in str(exc) for marker in _WL2_LIMIT_MARKERS):
                    raise InputError("AF_UNDERSTAND_LIMIT", "understand",
                                     "Dữ liệu vượt giới hạn đo cấu trúc trên toàn bộ dòng.") from None
                if str(exc) != "No largest table has repeated foreign keys and at least two targets":
                    raise InputError("AF_UNDERSTAND_INVALID", "understand", "Nguồn không khớp snapshot hoặc cấu trúc chưa hợp lệ.") from None
                # v2 treats the absence of a fact/lookup graph as uncertainty,
                # retaining the exact WL1 binding and WL2 evidence helpers.
                try:
                    bound = _bind_raw(self._raw_tables, self._snapshot)
                    finance = has_finance_schema(bound)
                    pack = {"id": "fin-pl-v1" if finance else "generic", "version": "1.0",
                            "genericMode": not finance,
                            "notice": None if finance else "Chưa có vai trò nghiệp vụ được xác nhận."}
                    report = key_report(bound)
                    context = {**deepcopy(self._snapshot), "pack": pack}
                    model = {"schemaVersion": "1.0", "snapshotHash": self._snapshot["snapshotHash"],
                             "pack": pack, "roles": [], "relationships": report["relationships"],
                             "assumptions": assumption_ledger(context, report),
                             "warnings": warning_classification(context, bound),
                             "variantOf": None, "variantReason": None, "hashBasis": list(_HASH_BASIS)}
                    model["understandHash"] = understand_hash(model)
                except ValueError as exc:
                    if any(marker in str(exc) for marker in _WL2_LIMIT_MARKERS):
                        raise InputError("AF_UNDERSTAND_LIMIT", "understand",
                                         "Dữ liệu vượt giới hạn đo cấu trúc trên toàn bộ dòng.") from None
                    raise InputError("AF_UNDERSTAND_INVALID", "understand", "Nguồn không khớp snapshot hoặc cấu trúc chưa hợp lệ.") from None
            # Derived modelView and grain questions, built under the same lock;
            # nothing is stored until every piece succeeded (no half state).
            try:
                bound = _bind_raw(self._raw_tables, self._snapshot)
                report = key_report(bound)
                bound_by_name = {raw["name"]: raw for raw in bound}
                grain_proposals = {}
                for table in self._snapshot["tables"]:
                    raw = bound_by_name[table["name"]]
                    keys = [key for key in report["keys"] if key["tableId"] == table["id"]]
                    grain_proposals[table["id"]] = grain_kind(raw, keys)
                questions = _questions(self._snapshot, model, grain_proposals)
                model_view = build_model_view(self._raw_tables, self._snapshot, model, questions)
            except ValueError as exc:
                if any(marker in str(exc) for marker in _WL2_LIMIT_MARKERS):
                    raise InputError("AF_UNDERSTAND_LIMIT", "understand",
                                     "Dữ liệu vượt giới hạn đo cấu trúc trên toàn bộ dòng.") from None
                raise InputError("AF_UNDERSTAND_INVALID", "understand", "Nguồn không khớp snapshot hoặc cấu trúc chưa hợp lệ.") from None
            self._understand = model
            self._model_view = model_view
            self._questions = questions
            self._stage = "understood"
            return {**self.state(), "snapshot": deepcopy(self._snapshot),
                    "understand": deepcopy(model), "questions": deepcopy(self._questions)}

    def _verify_source_binding(self) -> None:
        """Check full v2 row content, including tails beyond the WL1 profile sample.

        Later planning/execution phases must call this before using stored rows.
        The reentrant lock also permits callers already owning the store lock.
        """
        with self._lock:
            if self._snapshot is None:
                raise ValueError("A bound snapshot is required")
            bound = _bind_raw(self._raw_tables, self._snapshot)
            by_name = {raw["name"]: raw for raw in self._raw_tables}
            if len(bound) != len(by_name) or any(
                    table.get("contentHash") != _table_content_hash(by_name[table["name"]])
                    for table in self._snapshot["tables"]):
                raise ValueError("Stored source content differs from its snapshot")

    def plan_draft(self, prompt, answers, acknowledged, runner=None) -> dict:
        """Draft once after explicit disclosure; keep raw plans private."""
        with self._lock:
            if self._stage not in ("understood", "planning", "branched") or self._understand is None:
                raise InputError("AF_STAGE_INVALID", "stage", "Hiểu dữ liệu trước khi yêu cầu hai kế hoạch.")
            try:
                self._verify_source_binding()
                if (self._understand["snapshotHash"] != self._snapshot["snapshotHash"]
                        or understand_hash(self._understand) != self._understand["understandHash"]):
                    raise ValueError("Understanding differs from its snapshot")
            except ValueError:
                raise InputError("AF_PLAN_INVALID", "snapshot", "Nguồn hoặc cách hiểu đã thay đổi; hãy nạp lại.") from None
            from pbip_assistant.adapters.codex.assistant_plan import draft_branch_plans
            planning_snapshot = deepcopy(self._snapshot)
            planning_snapshot["_planningSamples"] = {}
            for raw in self._raw_tables:
                if raw["mode"] == MODE_DISCOVER:
                    ordinals, rows = raw["sampleOrdinals"], raw["rows"]
                else:
                    ordinals = raw["sampleOrdinals"]
                    if len(ordinals) > 20:
                        ordinals = [ordinals[index * (len(ordinals) - 1) // 19] for index in range(20)]
                    rows = [raw["rows"][ordinal] for ordinal in ordinals]
                planning_snapshot["_planningSamples"][raw["name"]] = {"rows": deepcopy(rows), "ordinals": list(ordinals)}
            drafted = draft_branch_plans(prompt, planning_snapshot, self._understand, answers, acknowledged, runner,
                                         questions=self._questions)
            cards = self._public_planning(drafted)
            self._planning = drafted
            self._branch_results = {}
            self._delta = None
            self._stage = "planning"
            return {"stage": self._stage, **cards}

    def _public_planning(self, planning=None) -> dict:
        planning = self._planning if planning is None else planning
        if planning is None:
            return {"branches": [], "planningHash": None, "draftInputs": None}
        result = {key: deepcopy(planning[key]) for key in ("summary", "questions", "assumptions")}
        result["planningHash"] = planning["planningHash"]
        result["draftInputs"] = deepcopy(planning["draftInputs"])
        result["branches"] = [{**{key: deepcopy(branch[key]) for key in ("id", "label", "rationale", "controlTotal", "maxFanOut", "planHash")},
                               **self._public_algorithm(branch)}
                              for branch in planning["branches"]]
        # Raw drafts and source samples are never part of the endpoint response.
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 64 * 1024:
            raise InputError("AF_PLAN_INVALID", "branches", "Plan cards exceed the 64 KiB response limit")
        return result

    @staticmethod
    def _public_algorithm(branch):
        """Expose the actual normalized algorithm, never the source catalog.

        Retain the existing compact card steps for older clients. The complete
        parameters/inputs let a reviewer distinguish algorithms with identical
        operation names before granting write authority. Derived contracts are
        repeated across wide pipelines; expose the final contract once while
        the frozen Spec and Record retain every full normalized step.
        """
        return {"steps": [{"id": step["stepId"], "operationType": step["operation"]["type"],
                           "label": step["actionDescription"]} for step in branch["plan"]["steps"]],
                "normalizedSteps": [{key: deepcopy(value) for key, value in step.items()
                                     if key != "outputContract"} for step in branch["plan"]["steps"]],
                "finalOutputStepId": branch["plan"]["finalOutputStepId"],
                "finalOutputContract": deepcopy(next(step["outputContract"] for step in branch["plan"]["steps"]
                    if step["stepId"] == branch["plan"]["finalOutputStepId"]))}

    @staticmethod
    def _public_execution_warnings(branch):
        """Project only known engine warnings and bound lineage, not cell text."""
        messages = {"AF_EXECUTOR_DATE_NULL": "Giá trị ngày không hợp lệ đã chuyển thành null; kiểm tra nguồn và kiểu ngày trước khi duyệt."}
        paths = {step["stepId"] + "." + column["columnId"]
                 for step in branch["plan"]["steps"] for column in step["outputContract"]["columns"]}
        paths.update("source." + column["columnId"]
                     for source in branch["plan"]["sources"] for column in source["columns"])
        result, seen = [], set()
        for warning in branch["result"].get("warnings", []):
            if not isinstance(warning, dict):
                continue
            code, path = warning.get("code"), warning.get("path")
            if not isinstance(code, str) or not isinstance(path, str) or code not in messages or path not in paths or (code, path) in seen:
                continue
            seen.add((code, path))
            result.append({"code": code, "path": path, "message": messages[code]})
        return result

    def run_branches(self, expected_planning_hash=None) -> dict:
        """Execute both plans against one verified compute snapshot, then reconcile.

        The bounded cache stores only execution results, never reconciliation or
        approval authority. Every invocation rechecks the current branch policy.
        """
        with self._lock:
            if self._stage not in ("planning", "branched") or self._planning is None:
                raise InputError("AF_STAGE_INVALID", "stage", "Tạo hai kế hoạch trước khi tính A/B.")
            if self._mode != MODE_COMPUTE:
                raise InputError("AF_SAMPLE_ONLY", "mode", "Chọn Đọc toàn bộ để tính; mẫu chưa đủ để đối soát.")
            if expected_planning_hash is not None and expected_planning_hash != self._planning["planningHash"]:
                raise InputError("AF_SPEC_STALE", "expectedPlanningHash", "Kế hoạch đã thay đổi.")
            try:
                self._verify_source_binding()
            except ValueError:
                raise InputError("AF_SPEC_STALE", "snapshot", "Nguồn lưu trong phiên không còn khớp snapshot.") from None
            from pbip_assistant.adapters.codex.assistant_plan import assistant_source_catalog, validate_branch_response, planning_hash
            if planning_hash(self._planning) != self._planning["planningHash"]:
                raise InputError("AF_SPEC_STALE", "planningHash", "Policy hoặc kế hoạch đã thay đổi ngoài revision được tạo.")
            response = {key: deepcopy(self._planning[key]) for key in ("summary", "questions", "assumptions")}
            response["branches"] = [{**{key: deepcopy(branch[key]) for key in ("id", "label", "rationale", "controlTotal", "maxFanOut")},
                                     "plan": deepcopy(branch["draft"])} for branch in self._planning["branches"]]
            validated = validate_branch_response(response, assistant_source_catalog(self._snapshot))
            for stored, current in zip(self._planning["branches"], validated["branches"]):
                if stored["planHash"] != current["planHash"] or canonical_hash(stored["plan"]) != canonical_hash(current["plan"]):
                    raise InputError("AF_PLAN_INVALID", "branches", "Kế hoạch không còn khớp catalog thật của snapshot compute.")
            snapshot_hash_value = self._snapshot["snapshotHash"]
            branches = {}
            for branch in self._planning["branches"]:
                key = (snapshot_hash_value, branch["planHash"])
                cached = key in self._execution_cache
                error = None
                size = None
                start = perf_counter()
                try:
                    if cached:
                        result = deepcopy(self._execution_cache[key]["result"])
                    else:
                        result = execute_plan(branch["plan"], self._raw_tables)
                        size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                except InputError as exc:
                    error = {"code": exc.code, "path": exc.path, "detail": exc.detail}
                    result = {"columns": [], "rows": [], "rowCount": 0, "fanOut": None}
                elapsed = max(0, int((perf_counter() - start) * 1000))
                try:
                    self._verify_source_binding()
                except ValueError:
                    raise InputError("AF_SOURCE_LOST", "snapshot", "Nguồn đã đổi trong lúc tính; không công bố kết quả.") from None
                if size is not None and size <= _CACHE_MAX_BYTES:
                    while self._execution_cache and (len(self._execution_cache) >= 2 or self._cache_bytes + size > _CACHE_MAX_BYTES):
                        removed = self._execution_cache.pop(next(iter(self._execution_cache)))
                        self._cache_bytes -= removed["bytes"]
                    self._execution_cache[key] = {"result": deepcopy(result), "bytes": size}
                    self._cache_bytes += size
                preview = build_preview(snapshot_hash_value, branch, result)
                reconciliation = reconcile_v2(preview, branch, self._raw_tables, result)
                branches[branch["id"]] = {**deepcopy(branch), "result": deepcopy(result), "preview": preview,
                    "reconciliation": reconciliation, "elapsedMs": elapsed, "cached": cached, "executionError": error}
            delta = build_ab_delta(branches["A"], branches["B"])
            for branch in branches.values():
                branch["reconciliation"] = bind_ab_identity(branch["reconciliation"], delta)
            self._branch_results, self._delta, self._stage = branches, delta, "branched"
            return {"stage": self._stage, "snapshotHash": snapshot_hash_value,
                    "planningHash": self._planning["planningHash"], "branches": self._public_branches(),
                    "delta": deepcopy(delta), "abIdentityPassed": ab_identity_passed(delta), "engine": deepcopy(ENGINE),
                    "allBlocked": not any(branch["reconciliation"]["selectable"] for branch in branches.values())}

    def _public_branches(self):
        result = []
        for identifier in ("A", "B"):
            branch = self._branch_results[identifier]
            full, reconciliation = branch["result"], branch["reconciliation"]
            rows, size = [], len(json.dumps(full["columns"], ensure_ascii=False).encode("utf-8"))
            for row in full["rows"][:200]:
                row_size = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
                if size + row_size > _PREVIEW_MAX_BYTES:
                    break
                rows.append(deepcopy(row))
                size += row_size
            error = branch["executionError"] or (deepcopy(reconciliation["blockers"][0]) if reconciliation["blockers"] else None)
            warnings = self._public_execution_warnings(branch)
            result.append({**{key: deepcopy(branch[key]) for key in ("id", "label", "rationale", "controlTotal", "maxFanOut", "planHash", "elapsedMs", "cached")},
                **self._public_algorithm(branch), "warnings": warnings, "warningCount": len(warnings),
                "snapshotHash": branch["preview"]["snapshotHash"], "previewHash": branch["preview"]["previewHash"],
                "resultDigest": branch["preview"]["resultDigest"], "columns": deepcopy(full["columns"]), "rows": rows,
                "totalRows": len(full["rows"]), "truncated": len(rows) < len(full["rows"]),
                "counts": {"before": {"rows": reconciliation["rowsIn"], "cols": reconciliation["colsIn"]},
                           "after": {"rows": reconciliation["rowsOut"], "cols": reconciliation["colsOut"]}},
                "reconciliation": deepcopy(reconciliation), "selectable": reconciliation["selectable"],
                "error": error, "engine": deepcopy(ENGINE), "previewLimit": {"maxRows": 200, "maxBytes": _PREVIEW_MAX_BYTES}})
        return result

    def _verify_fresh_sources(self, workbook_sources):
        """Re-read file/folder sources and compare freshly submitted full workbook selections.

        Workbook selections come from the add-in's independent Office.js read;
        they are not represented as values decoded from the exported package.
        No client-supplied source hash is trusted here.
        """
        if not isinstance(workbook_sources, list) or any(not isinstance(item, dict) or item.get("kind") != "workbook"
                or set(item) - {"kind", "mode", "payload", "name"} or not isinstance(item.get("payload"), dict)
                or any(not isinstance(item["payload"].get(key), str) for key in ("origin", "name", "sheet"))
                or type(item["payload"].get("table")) is not bool for item in workbook_sources):
            raise InputError("INVALID_REQUEST", "workbookSources", "Cần các lựa chọn workbook đầy đủ vừa đọc lại.")
        originals = [request for request in self._ingest_requests if request["kind"] == "workbook"]
        if len(originals) != len(workbook_sources):
            raise InputError("AF_SPEC_STALE", "workbookSources", "Danh sách nguồn workbook đã đổi.")
        def identity(request):
            payload = request.get("payload", {})
            return tuple(payload.get(key) for key in ("origin", "name", "sheet", "table"))
        fresh_by_id = {identity(request): request for request in workbook_sources}
        if len(fresh_by_id) != len(workbook_sources) or set(fresh_by_id) != {identity(request) for request in originals}:
            raise InputError("AF_SPEC_STALE", "workbookSources", "Bảng hoặc vùng nguồn workbook đã đổi.")
        requests = []
        for request in self._ingest_requests:
            current = deepcopy(fresh_by_id[identity(request)] if request["kind"] == "workbook" else request)
            current["mode"] = "compute"
            requests.append(current)
        fresh = AssistantSessionStore()
        try:
            self._bind_fresh(fresh)
            fresh.ingest(requests)
            if fresh._snapshot is None or fresh._snapshot["snapshotHash"] != self._snapshot["snapshotHash"]:
                raise InputError("AF_SPEC_STALE", "snapshot", "Nguồn hiện tại đã đổi; hãy nạp, tính và duyệt lại.")
        except (OSError, ValueError):
            raise InputError("AF_SOURCE_LOST", "sources", "Không đọc lại được nguồn hiện tại.") from None
        finally:
            fresh.close()

    def _frozen_branch(self):
        if self._frozen_spec is None or self._chosen_branch not in self._branch_results:
            raise InputError("AF_STAGE_INVALID", "stage", "Chốt nhánh trước khi duyệt hoặc ghi.")
        branch = self._branch_results[self._chosen_branch]
        try:
            self._verify_source_binding()
        except ValueError:
            raise InputError("AF_SPEC_STALE", "snapshot", "Nguồn lưu trong phiên đã đổi.") from None
        from pbip_assistant.adapters.codex.assistant_plan import planning_hash
        spec = self._frozen_spec
        self._verify_branch_reconciliation(branch)
        validate_frozen_spec(spec, branch["preview"])
        if (self._snapshot["snapshotHash"] != spec["snapshotHash"] or self._understand["understandHash"] != spec["understandHash"]
                or planning_hash(self._planning) != spec["planningHash"]
                or branch["reconciliation"]["reconcileHash"] != spec["reconcileHash"]
                or canonical_hash(branch["plan"]["steps"]) != canonical_hash(spec["steps"])
                or canonical_hash({"columns": branch["result"]["columns"], "rows": branch["result"]["rows"]}) != spec["resultDigest"]):
            raise InputError("AF_SPEC_STALE", "spec", "Spec hoặc kết quả đã đổi sau khi chốt.")
        assert_freezable(branch, spec["decisions"]["acknowledgeMissingControl"])
        return branch

    def _verify_branch_reconciliation(self, branch):
        fresh_preview = build_preview(self._snapshot["snapshotHash"], branch, branch["result"])
        fresh = bind_ab_identity(reconcile_v2(fresh_preview, branch, self._raw_tables, branch["result"]), self._delta)
        if branch.get("executionError") or fresh_preview != branch["preview"] or fresh != branch["reconciliation"]:
            raise InputError("AF_RECONCILE_FAILED", "reconciliation", "Đối soát không còn khớp số engine tính; không cấp quyền ghi.")

    def freeze(self, branch_id, created_at, workbook, acknowledge_missing_control=False, *,
               expected_planning_hash, expected_preview_hash, expected_result_digest):
        with self._lock:
            if not isinstance(branch_id, str) or branch_id not in ("A", "B") or type(acknowledge_missing_control) is not bool:
                raise InputError("INVALID_REQUEST", "branchId", "Chọn nhánh A hoặc B và acknowledgement boolean.")
            if self._write_attempted:
                raise InputError("AF_SPEC_STALE", "approval", "Quyền ghi đã dùng; không chốt lại để tự thử lại cùng lần ghi.")
            if self._mode != "compute":
                raise InputError("AF_SAMPLE_ONLY", "mode", "Đọc toàn bộ nguồn trước khi chốt nhánh.")
            if self._stage not in ("branched", "frozen", "approved") or branch_id not in self._branch_results:
                raise InputError("AF_STAGE_INVALID", "branchId", "Tính hai nhánh rồi chọn nhánh cần chốt.")
            preview = self._branch_results[branch_id]["preview"]
            if (expected_planning_hash != self._planning["planningHash"] or expected_preview_hash != preview["previewHash"]
                    or expected_result_digest != preview["resultDigest"]):
                raise InputError("AF_SPEC_STALE", "expectedPreviewHash", "Nhánh đang hiển thị đã đổi; rà soát lại trước khi chốt.")
            self._verify_source_binding()
            self._verify_branch_reconciliation(self._branch_results[branch_id])
            spec = build_frozen_spec(self._snapshot, self._understand, self._branch_results[branch_id],
                planning_hash=self._planning["planningHash"], created_at=created_at, workbook=workbook,
                acknowledge_missing_control=acknowledge_missing_control, assumptions=self._planning["assumptions"])
            self._frozen_spec, self._chosen_branch = spec, branch_id
            self._approval = None
            self._stage = "frozen"
            return {"stage": self._stage, "spec": deepcopy(spec), "chosenBranch": branch_id}

    def approve(self, approved_at, acknowledged, workbook, workbook_sources, *,
                expected_spec_fingerprint, expected_preview_hash, expected_result_digest):
        with self._lock:
            timestamp(approved_at)
            if self._write_attempted:
                raise InputError("AF_SPEC_STALE", "approval", "Quyền ghi đã dùng; không phát hành lại để thử lại.")
            if self._stage not in ("frozen", "approved") or acknowledged is not True:
                raise InputError("AF_APPROVAL_MISSING", "acknowledged", "Rà soát Spec và xác nhận duyệt tường minh.")
            branch = self._frozen_branch()
            self._check_reviewed_spec(expected_spec_fingerprint, expected_preview_hash, expected_result_digest)
            if workbook_identity(workbook) != self._frozen_spec["workbookIdentity"]:
                raise InputError("AF_SPEC_STALE", "workbookIdentity", "Workbook đã đổi.")
            self._verify_fresh_sources(workbook_sources)
            if self._approval is None:
                self._approval = issue_approval_v2(self._frozen_spec, branch["preview"], approved_at=approved_at)
            else:
                validate_approval_v2(self._approval, self._frozen_spec, branch["preview"])
            self._stage = "approved"
            return {"stage": self._stage, "approval": deepcopy(dict(self._approval)), "spec": deepcopy(self._frozen_spec)}

    def _check_reviewed_spec(self, fingerprint, preview_hash, digest):
        if (fingerprint != self._frozen_spec["fingerprint"] or preview_hash != self._frozen_spec["previewHash"]
                or digest != self._frozen_spec["resultDigest"]):
            raise InputError("AF_SPEC_STALE", "expectedSpecFingerprint", "Spec được rà soát không còn là revision hiện tại.")

    @_capture_apply_error_authority(may_prove_preconsume=True)
    def apply(self, workbook_base64, applied_at, workbook, workbook_sources, *,
              expected_spec_fingerprint, expected_preview_hash, expected_result_digest):
        with self._lock:
            if self._write_attempted:
                raise InputError("AF_WRITE_PARTIAL", "apply", "Quyền ghi đã tiêu thụ; lần ghi trước ở trạng thái chưa biết hoặc đã ghi, không tự thử lại.")
            if self._stage != "approved" or self._approval is None:
                raise InputError("AF_APPROVAL_MISSING", "approval", "Duyệt Spec trước khi ghi.")
            timestamp(applied_at)
            branch = self._frozen_branch()
            self._check_reviewed_spec(expected_spec_fingerprint, expected_preview_hash, expected_result_digest)
            spec = self._frozen_spec
            if workbook_identity(workbook) != spec["workbookIdentity"]:
                raise InputError("AF_SPEC_STALE", "workbookIdentity", "Workbook đang mở đã đổi.")
            self._verify_fresh_sources(workbook_sources)
            validate_approval_v2(self._approval, spec, branch["preview"])
            try:
                if not isinstance(workbook_base64, str) or len(workbook_base64) > (MAX_PACKAGE_BYTES * 4 // 3 + 8):
                    raise ValueError()
                package = base64.b64decode(workbook_base64, validate=True)
                verify_values_only(package)
                _, parts = _package(package)
                sheets, _ = _metadata(parts)
                if any(sheet["name"].casefold() == spec["target"]["sheet"].casefold() for sheet in sheets):
                    raise InputError("AF_WRITE_PARTIAL", "target.sheet", "Sheet đích đã tồn tại; chưa tiêu thụ quyền ghi.")
            except (ValueError, TypeError):
                raise InputError("AF_WRITE_PARTIAL", "workbookBase64", "Package workbook không hợp lệ; chưa tiêu thụ quyền ghi.") from None
            # Construct all potentially failing response material before burning the capability.
            result = deepcopy(branch["result"])
            if (len(result["rows"]) + 1) * len(result["columns"]) > 400000:
                raise InputError("AF_WRITE_PARTIAL", "result", "Kết quả vượt giới hạn 400.000 ô ghi; chưa tiêu thụ quyền ghi.")
            marker = result_marker(spec)
            receipt = {"handoffId": "handoff_" + secrets.token_hex(16), "specFingerprint": spec["fingerprint"],
                "previewHash": spec["previewHash"], "resultDigest": spec["resultDigest"], "sheet": spec["target"]["sheet"],
                "marker": marker, "rowCount": len(result["rows"]), "columnCount": len(result["columns"])}
            consumed = consume_approval(self._approval)
            self._write_attempted, self._stage = True, "handoff"
            self._handoff = {"receiptBinding": receipt, "appliedAt": applied_at, "approval": consumed}
            return {"stage": self._stage, "result": {"columns": result["columns"], "rows": result["rows"],
                    "totalRows": len(result["rows"]), "truncated": False}, "marker": marker, "labels": deepcopy(spec["labels"]),
                "resultDigest": spec["resultDigest"], "receiptBinding": deepcopy(receipt),
                "apply": {"target": deepcopy(spec["target"]), "written": {"rowCount": 0, "columnCount": 0},
                    "approval": consumed, "workbookSaved": False, "status": "handoff-unverified"}}

    @_capture_apply_error_authority(may_prove_preconsume=False)
    def complete_apply(self, receipt, applied_at):
        with self._lock:
            if not self._write_attempted or self._handoff is None or self._stage != "handoff":
                raise InputError("AF_SPEC_STALE", "receipt", "Không có bàn giao đang chờ đọc lại.")
            timestamp(applied_at)
            expected = self._handoff["receiptBinding"]
            if not isinstance(receipt, dict) or set(receipt) != {*expected, "verified"} or receipt.get("verified") is not True or any(type(receipt.get(key)) is not type(value) or receipt.get(key) != value for key, value in expected.items()):
                self._stage = "partial"
                raise InputError("AF_WRITE_PARTIAL", "receipt", "Read-back không khớp; workbook có thể đã ghi một phần, không tự thử lại.")
            self._apply_receipt = {**deepcopy(receipt), "appliedAt": applied_at, "workbookSaved": False}
            self._stage = "applied"
            return {"stage": self._stage, "apply": {"target": deepcopy(self._frozen_spec["target"]),
                    "written": {"rowCount": expected["rowCount"], "columnCount": expected["columnCount"]},
                    "workbookSaved": False, "status": "readback-verified", "approval": deepcopy(self._handoff["approval"])}}

    def approval_consumed(self):
        with self._lock:
            return self._write_attempted

    def _verified_apply_receipt(self):
        if not self._write_attempted or self._apply_receipt is None or self._handoff is None or self._approval is None:
            return False
        expected = self._handoff["receiptBinding"]
        receipt = self._apply_receipt
        return (set(receipt) == {*expected, "verified", "appliedAt", "workbookSaved"}
                and receipt.get("verified") is True and receipt.get("workbookSaved") is False
                and all(type(receipt.get(key)) is type(value) and receipt.get(key) == value for key, value in expected.items())
                and approval_state(self._approval)["consumed"] is True)

    def _record_freshness(self):
        # Workbook rows cannot be checked by a server-side body{} request.
        if any(request["kind"] == "workbook" for request in self._ingest_requests):
            return detect_stale_v2(self._record)
        fresh = AssistantSessionStore()
        try:
            self._bind_fresh(fresh)
            fresh.ingest([{**deepcopy(request), "mode": "compute"} for request in self._ingest_requests])
            if fresh._snapshot is None:
                return detect_stale_v2(self._record, source_unavailable=True)
            return detect_stale_v2(self._record, current_snapshot_hash=fresh._snapshot["snapshotHash"])
        except (InputError, OSError, ValueError):
            return detect_stale_v2(self._record, source_unavailable=True)
        finally:
            fresh.close()

    def record(self):
        with self._lock:
            if self._stage not in ("applied", "recorded") or not self._verified_apply_receipt():
                raise InputError("AF_STAGE_INVALID", "stage", "Chỉ tạo Record sau ghi và đọc lại đầy đủ bằng đúng quyền đã dùng.")
            if self._record is None:
                branch = self._frozen_branch()
                delta = compute_v2_delta(branch["plan"], self._raw_tables, branch["result"])
                self._record = build_v2_record(self._snapshot, branch["plan"], branch, self._frozen_spec,
                    branch["reconciliation"], delta, self._apply_receipt["appliedAt"],
                    source_evidence={"prompt": self._planning["draftInputs"]["prompt"]})
                self._record_node = record_node(self._record, self._chosen_branch)
            elif record_hash_v2(self._record) != self._record["hash"]:
                raise InputError("AF_RECORD_INVALID", "record", "Record lưu trong phiên đã đổi.")
            self._stage = "recorded"
            return {"stage": self._stage, "recordId": self._record["id"], "recordHash": self._record["hash"],
                "node": deepcopy(self._record_node), "record": deepcopy(self._record),
                "staleCheck": self._record_freshness(), "workbookSaved": False}

    def state(self) -> dict:
        with self._lock:
            return {"stage": self._stage, "mode": self._mode,
                    "rootLabel": "Workbook" if self._workbook_only else self._root.name if self._root else None,
                    "snapshotHash": self._snapshot["snapshotHash"] if self._snapshot else None,
                    "understandHash": self._understand["understandHash"] if self._understand else None,
                    "modelView": deepcopy(self._model_view) if self._model_view else None,
                    "chosenBranch": self._chosen_branch, "recordHash": self._record["hash"] if self._record else None,
                    "recordId": self._record["id"] if self._record else None,
                    "record": deepcopy(self._record), "node": deepcopy(self._record_node),
                    "staleCheck": detect_stale_v2(self._record) if self._record else None,
                    "spec": deepcopy(self._frozen_spec),
                    "approval": deepcopy(dict(self._approval)) if self._approval is not None else None,
                    "approvalConsumed": self._write_attempted,
                    "handoffStatus": "readback-verified" if self._stage in ("applied", "recorded") and self._verified_apply_receipt() else "partial-unknown" if self._write_attempted else None,
                    "allBlocked": bool(self._branch_results) and not any(branch["reconciliation"]["selectable"] for branch in self._branch_results.values()),
                    "workbookSourceSelections": [{**{key: deepcopy(request["payload"].get(key)) for key in ("sheet", "name", "origin", "table")},
                        **({"alias": request["name"]} if request.get("name") is not None else {})}
                        for request in self._ingest_requests if request["kind"] == "workbook"],
                    "snapshot": deepcopy(self._snapshot),
                    "understand": deepcopy(self._understand), "questions": deepcopy(self._questions),
                    "sources": deepcopy(self._ingested["sources"]) if self._ingested else [],
                    "tables": deepcopy(self._snapshot["tables"]) if self._snapshot else [],
                    **{key: deepcopy(self._ingested[key]) if self._ingested else []
                       for key in ("csvOptions", "errors", "requiresRename", "warnings")},
                    "sampleInfo": [{"name": raw["name"], "mode": raw["mode"],
                                    "totalRows": raw["totalRows"], "rowCount": len(raw["rows"]),
                                    "sampleOrdinals": list(raw["sampleOrdinals"])} for raw in self._raw_tables],
                    "branches": self._public_branches() if self._branch_results else self._public_planning()["branches"],
                    "planningHash": self._planning["planningHash"] if self._planning else None,
                    "draftInputs": deepcopy(self._planning["draftInputs"]) if self._planning else None,
                    "planSummary": self._planning["summary"] if self._planning else None,
                    "planQuestions": deepcopy(self._planning["questions"]) if self._planning else [],
                    "planAssumptions": deepcopy(self._planning["assumptions"]) if self._planning else [],
                    "delta": deepcopy(self._delta),
                    "abIdentityPassed": ab_identity_passed(self._delta) if self._delta else None,
                    "engine": deepcopy(ENGINE) if self._branch_results else None}
