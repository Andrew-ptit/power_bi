from __future__ import annotations
from copy import deepcopy
from io import BytesIO
import base64
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from xml.etree import ElementTree as ET
from pbip_assistant.errors import InputError
from pbip_assistant.excel_addin_server import ExcelAddinApp, create_server
from pbip_assistant.excel_connector import PowerShellExcelRunner
from pbip_assistant.pq_typed import DESTINATION_MARKER
from pbip_assistant.problem_chain import (
    MAX_CANONICAL_JSON_BYTES,
    ProblemChainStore,
    canonical_json,
    compute_history_hash,
    compute_review_hash,
    source_schema_fingerprint,
    validate_document,
)
from pbip_assistant.workbook_fingerprint import MAIN, workbook_data_fingerprint
from tests.support.excel_plan import FIXTURE_ROOT
from tests.support.excel_plan import office_snapshot
from tests.support.pq_code_m import FakePQRunner
from tests.support.pq_typed import FakeTypedPlanner
from tests.support.problem_chain import typed_plan
from tests.support.workbook_fingerprint import repack

from tests.support.problem_chain_journey import (_independent_hash, _review_basis, _mutate_first_cell, CountingPlanner, BlockingContinuationPlanner, _two_step_plan, PipelineResetPlanner, ClientRefCollisionPlanner, UnknownChangeFieldPlanner, DynamicContinuationPlanner, LeftMergeContinuationPlanner, CountingTypedPlanner, ProblemChainHttpHarness)

class ProblemChainIntegrityCrosscheck(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = CountingPlanner()
        self.store = ProblemChainStore(self.planner)
        self.addCleanup(self.store.close)

    def root(self) -> dict:
        return self.store.create_problem(None, None, "Vấn đề gốc", typed_plan=typed_plan())

    def assert_code(self, code: str, action) -> InputError:
        with self.assertRaises(InputError) as caught:
            action()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_canonical_hash_matches_independent_utf8_oracle(self) -> None:
        candidate = self.root()
        document = candidate["document"]
        self.assertEqual(canonical_json(document), json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"))
        self.assertEqual(compute_history_hash(document), _independent_hash(document))
        self.assertEqual(candidate["historyHash"], _independent_hash(document))

    def test_review_hash_excludes_only_envelope_fields_not_semantics(self) -> None:
        revision = self.root()["revision"]
        self.assertEqual(compute_review_hash(revision), _independent_hash(_review_basis(revision)))
        for key, value in {
            "revisionId": "rev_" + "a" * 24,
            "parentRevisionId": "rev_" + "b" * 24,
            "createdAt": "2099-01-01T00:00:00+00:00",
            "name": "Bản quan trọng",
            "note": "Chỉ là chú thích, không phải business rule",
            "annotationUpdatedAt": "2099-01-01T00:00:00+00:00",
            "runtimeSummary": {"historical": True},
            "validationAtCreation": {"historical": True},
        }.items():
            changed = deepcopy(revision)
            changed[key] = value
            self.assertEqual(revision["reviewHash"], compute_review_hash(changed), key)
        for key, value in {
            "problemPrompt": "Business rule changed",
            "summary": "Different semantic summary",
            "finalOutputStepId": "stp_other",
        }.items():
            changed = deepcopy(revision)
            changed[key] = value
            self.assertNotEqual(revision["reviewHash"], compute_review_hash(changed), key)

    def test_cas_conflict_has_zero_planner_calls_and_candidate_is_retryable(self) -> None:
        root = self.root()
        self.assert_code(
            "PQPC_HISTORY_CONFLICT",
            lambda: self.store.create_problem(root["document"], "sha256:" + "0" * 64, "stale"),
        )
        self.assertEqual(self.planner.calls, [])
        self.assert_code(
            "PQPC_HISTORY_CONFLICT",
            lambda: self.store.commit(root["mutationId"], "sha256:" + "f" * 64),
        )
        committed = self.store.commit(root["mutationId"], root["historyHash"])
        self.assertEqual(committed["historyHash"], root["historyHash"])
        self.assert_code(
            "PQPC_MUTATION_NOT_COMMITTED",
            lambda: self.store.commit(root["mutationId"], root["historyHash"]),
        )

    def test_load_generation_change_rejects_inflight_planner_candidate(self) -> None:
        planner = BlockingContinuationPlanner()
        store = ProblemChainStore(planner)
        other_store = ProblemChainStore()
        self.addCleanup(store.close)
        self.addCleanup(other_store.close)
        root = store.create_problem(None, None, "Workbook A", typed_plan=typed_plan())
        committed = store.commit(root["mutationId"], root["historyHash"])
        other = other_store.create_problem(None, None, "Workbook B", typed_plan=typed_plan())
        candidates: list[dict] = []
        failures: list[InputError] = []

        def continue_a() -> None:
            try:
                candidates.append(store.create_problem(
                    committed["document"], committed["historyHash"], "Continue A",
                ))
            except InputError as exc:
                failures.append(exc)

        worker = threading.Thread(target=continue_a)
        worker.start()
        self.assertTrue(planner.started.wait(timeout=2))
        store.load(other["document"])
        planner.release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(candidates, [])
        self.assertEqual([item.code for item in failures], ["PQPC_HISTORY_CONFLICT"])
        self.assertIsNone(store.active_revision(committed["document"]["headRevisionId"]))
        self.assertIsNotNone(store.active_revision(other["document"]["headRevisionId"]))

    def test_session_expiry_clears_problem_chain_runtime_state(self) -> None:
        clock = [1_000.0]
        app = ExcelAddinApp(
            session_clock=lambda: clock[0], idle_timeout_seconds=10,
            absolute_timeout_seconds=100,
        )
        self.addCleanup(app.close)
        bootstrap = app.bootstrap()
        candidate = app.problem_chains.create_problem(
            None, None, "Session-bound root", typed_plan=typed_plan(),
        )
        committed = app.problem_chains.commit(
            candidate["mutationId"], candidate["historyHash"],
        )
        revision_id = committed["document"]["headRevisionId"]
        self.assertIsNotNone(app.problem_chains.active_revision(revision_id))
        clock[0] += 10
        with self.assertRaises(InputError) as caught:
            app.runtime.sessions.authenticate(bootstrap["token"])
        self.assertEqual(caught.exception.code, "TOKEN_EXPIRED")
        self.assertIsNone(app.problem_chains.active_revision(revision_id))

    def test_tree_rejects_missing_parent_cycle_second_root_and_missing_head(self) -> None:
        root = self.root()
        second = self.store.create_problem(
            root["document"], root["historyHash"], "Vấn đề tiếp theo",
        )["document"]
        attacks = []
        missing_parent = deepcopy(second)
        missing_parent["revisions"][1]["parentRevisionId"] = "rev_" + "e" * 24
        attacks.append(missing_parent)
        cycle = deepcopy(second)
        cycle["revisions"][0]["parentRevisionId"] = cycle["revisions"][1]["revisionId"]
        attacks.append(cycle)
        second_root = deepcopy(second)
        second_root["revisions"][1]["parentRevisionId"] = None
        attacks.append(second_root)
        missing_head = deepcopy(second)
        missing_head["headRevisionId"] = "rev_" + "d" * 24
        attacks.append(missing_head)
        duplicate = deepcopy(second)
        duplicate["revisions"][1]["revisionId"] = duplicate["revisions"][0]["revisionId"]
        attacks.append(duplicate)
        for index, document in enumerate(attacks):
            with self.subTest(attack=index):
                self.assert_code("PQPC_DOCUMENT_INVALID", lambda document=document: validate_document(document))

    def test_checkout_old_revision_requires_explicit_branch_intent(self) -> None:
        root = self.root()
        second = self.store.create_problem(
            root["document"], root["historyHash"], "Vấn đề 2",
        )
        old_revisions = deepcopy(second["document"]["revisions"])
        checked = self.store.checkout(second["document"], second["historyHash"], root["revision"]["revisionId"])
        self.assertEqual(checked["document"]["revisions"], old_revisions)
        planner_calls_before_branch = len(self.planner.calls)
        self.assert_code(
            "PQPC_BRANCH_INTENT_REQUIRED",
            lambda: self.store.create_problem(checked["document"], checked["historyHash"], "Không được tạo nhánh"),
        )
        self.assertEqual(len(self.planner.calls), planner_calls_before_branch)

    def test_continuation_cannot_silently_replace_the_base_pipeline(self) -> None:
        reset_planner = PipelineResetPlanner()
        store = ProblemChainStore(reset_planner)
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Tạo nguồn và chọn OrderID", typed_plan=_two_step_plan())
        with self.assertRaises(InputError, msg="continuation dropped a stable step without an explicit typed change"):
            store.create_problem(root["document"], root["historyHash"], "Tiếp tục xử lý")
        self.assertEqual(len(reset_planner.calls), 1)
        self.assertEqual(len(root["revision"]["steps"]), 2)

    def test_client_ref_resolution_cannot_rewrite_descriptions_or_parameters(self) -> None:
        store = ProblemChainStore(ClientRefCollisionPlanner())
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Create source", typed_plan=typed_plan())
        continued = store.create_problem(root["document"], root["historyHash"], "Select OrderID")
        inserted = continued["revision"]["steps"][1]
        self.assertRegex(inserted["stepId"], r"^stp_[0-9a-f]{24}$")
        self.assertEqual(inserted["actionDescription"], "selected")
        self.assertEqual(continued["revision"]["finalOutputStepId"], inserted["stepId"])

    def test_unknown_continuation_change_field_is_rejected(self) -> None:
        store = ProblemChainStore(UnknownChangeFieldPlanner())
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Create source", typed_plan=typed_plan())
        self.assert_code(
            "PQPC_DOCUMENT_INVALID",
            lambda: store.create_problem(root["document"], root["historyHash"], "Unknown field"),
        )

    def test_fifty_revision_limit_blocks_before_planner(self) -> None:
        root = self.root()
        document = deepcopy(root["document"])
        parent = document["revisions"][0]["revisionId"]
        template = document["revisions"][0]
        for number in range(2, 51):
            item = deepcopy(template)
            item["revisionId"] = f"rev_{number:024x}"
            item["parentRevisionId"] = parent
            document["revisions"].append(item)
            parent = item["revisionId"]
        document["headRevisionId"] = parent
        document["storageVersion"] = 50
        validate_document(document)
        self.assert_code(
            "PQPC_HISTORY_LIMIT",
            lambda: self.store.create_problem(document, compute_history_hash(document), "Revision 51"),
        )
        self.assertEqual(self.planner.calls, [])

    def test_near_two_mib_history_blocks_before_planner(self) -> None:
        document = deepcopy(self.root()["document"])
        base_size = len(canonical_json(document))
        # validationAtCreation is historical evidence and outside reviewHash. Fill the
        # valid document to leave too little room for even the next prompt/revision.
        target_slack = 32
        padding = MAX_CANONICAL_JSON_BYTES - base_size - target_slack - len(',"padding":""')
        document["revisions"][0]["validationAtCreation"]["padding"] = "x" * padding
        while len(canonical_json(document)) > MAX_CANONICAL_JSON_BYTES:
            document["revisions"][0]["validationAtCreation"]["padding"] = document["revisions"][0]["validationAtCreation"]["padding"][:-1]
        validate_document(document)
        self.assertLessEqual(MAX_CANONICAL_JSON_BYTES - len(canonical_json(document)), target_slack)
        self.assert_code(
            "PQPC_HISTORY_LIMIT",
            lambda: self.store.create_problem(document, compute_history_hash(document), "Cannot fit"),
        )
        self.assertEqual(self.planner.calls, [], "planner must not receive prompt/history when no revision can fit")

    def test_schema_fingerprint_and_runtime_data_fingerprint_are_independent(self) -> None:
        sources = deepcopy(typed_plan()["sources"])
        schema_before = source_schema_fingerprint(sources)
        sources[0]["sourceId"] = "src_runtime_alias_changed"
        sources[0]["sheetName"] = "Display locator changed"
        sources[0]["totalRows"] += 10_000
        self.assertEqual(schema_before, source_schema_fingerprint(sources))
        type_changed = deepcopy(sources)
        type_changed[0]["columns"][1]["inferredType"] = "number"
        self.assertNotEqual(schema_before, source_schema_fingerprint(type_changed))

        used_range = deepcopy(sources)
        used_range[0]["kind"] = "usedRange"
        used_range[0].pop("objectName")
        used_range[0]["sheetName"] = "Sales"
        used_range[0]["headerRow"] = 1
        range_before = source_schema_fingerprint(used_range)
        used_range[0]["sheetName"] = "SalesMoved"
        self.assertNotEqual(range_before, source_schema_fingerprint(used_range))

        payload = (FIXTURE_ROOT / "excel_mcp_sales_input.xlsx").read_bytes()
        changed_payload = _mutate_first_cell(payload)
        self.assertNotEqual(workbook_data_fingerprint(payload), workbook_data_fingerprint(changed_payload))
        self.assertEqual(schema_before, source_schema_fingerprint(sources))

    def test_load_rehydrates_metadata_but_never_runtime_authority(self) -> None:
        root = self.root()
        committed = self.store.commit(root["mutationId"], root["historyHash"])
        fresh_session = ProblemChainStore(CountingPlanner())
        self.addCleanup(fresh_session.close)
        loaded = fresh_session.load(committed["document"])
        self.assertEqual(loaded["document"], committed["document"])
        serialized = canonical_json(loaded["document"])
        for forbidden in (b'"approval"', b'"approvalId"', b'"previewId"', b'"sessionToken"'):
            self.assertNotIn(forbidden, serialized)
        polluted = deepcopy(committed["document"])
        polluted["revisions"][0]["validationAtCreation"]["approvalId"] = "apr_forged"
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: fresh_session.load(polluted))

    def test_raw_m_sample_and_external_secret_metadata_are_rejected(self) -> None:
        root = self.root()["document"]
        raw = deepcopy(root)
        raw["revisions"][0]["steps"][0]["operation"]["parameters"]["rawM"] = 'Web.Contents("https://evil")'
        self.assert_code("PQV2_POLICY_VIOLATION", lambda: validate_document(raw))
        sample = deepcopy(root)
        sample["revisions"][0]["sources"][0]["sampleRows"] = [["CELL_SENTINEL"]]
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(sample))
        for key, value in {
            "localPath": r"C:\\secret\\payroll.xlsx",
            "url": "https://example.invalid/exfiltrate",
            "credential": "secret-token",
            "unknownField": "must fail closed",
        }.items():
            polluted = deepcopy(root)
            polluted["revisions"][0]["sources"][0][key] = value
            polluted["revisions"][0]["reviewHash"] = compute_review_hash(polluted["revisions"][0])
            with self.subTest(key=key):
                self.assert_code("PQPC_DOCUMENT_INVALID", lambda polluted=polluted: validate_document(polluted))

