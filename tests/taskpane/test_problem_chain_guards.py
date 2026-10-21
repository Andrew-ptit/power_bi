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

class ProblemChainTaskPaneStaticCrosscheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (
            Path(__file__).resolve().parents[2] / "pbip_assistant" / "excel_addin" / "taskpane.js"
        ).read_text(encoding="utf-8")

    def function_body(self, name: str, next_name: str) -> str:
        start = self.script.index(f"async function {name}(")
        end = self.script.index(f"async function {next_name}(", start)
        return self.script[start:end]

    def test_continuation_request_never_sends_full_typed_plan(self) -> None:
        helper = self.function_body("createProblemMutation", "createProblemContinuation")
        continuation = self.function_body("createProblemContinuation", "submitProblemBranchDraft")
        self.assertNotIn("typedPlan:", helper + continuation)
        self.assertIn("document: state.problemChainDocument", helper)
        self.assertIn("workbook: state.workbook", helper)
        self.assertIn("source,", helper)
        self.assertIn("state.problemChainDocument?.headRevisionId", continuation)
        self.assertIn('creationMode: "continue"', continuation)

    def test_hydration_discards_session_only_runtime_authority(self) -> None:
        body = self.function_body("hydrateProblemChain", "persistProblemChainCandidate")
        self.assertIn("state.pqTypedPreview = null", body)
        self.assertIn("state.pqTypedApproval = null", body)
        self.assertIn('setHidden("pq2-preview-section", true)', body)

    def test_custom_xml_cas_compares_hash_and_payload_without_saving_workbook(self) -> None:
        body = self.function_body("persistProblemChainCandidate", "createProblemContinuation")
        self.assertIn("current.historyHash !== expectedBase", body)
        self.assertIn("canonicalProblemChainJson(current.document)", body)
        self.assertIn("canonicalProblemChainJson(state.problemChainDocument)", body)
        self.assertIn("committed.historyHash !== candidate.historyHash", body)
        self.assertNotIn("workbook.save", body)
        self.assertNotIn("context.workbook.worksheets", body)

    def test_manual_step_edits_use_candidate_persistence_not_legacy_revision_api(self) -> None:
        start = self.script.index("async function createTypedRevision(")
        end = self.script.index("function typedActionButton(", start)
        body = self.script[start:end]
        chain_call = body.index('api("/api/pq/v2/problem-chains/revisions"')
        persist_call = body.index("await persistProblemChainCandidate(candidate)")
        legacy_call = body.index('api("/api/pq/v2/revisions"')
        self.assertLess(chain_call, persist_call)
        self.assertLess(persist_call, legacy_call)
        chain_branch = body[:legacy_call]
        self.assertIn("document: state.problemChainDocument", chain_branch)
        self.assertIn("baseHistoryHash: state.problemChainHistoryHash", chain_branch)
        self.assertIn("baseRevisionId: state.problemChainDocument.headRevisionId", chain_branch)
        self.assertIn("changes, changeReason", chain_branch)
        self.assertIn("workbook: state.workbook", chain_branch)

    def test_editor_closes_only_after_committed_manual_revision(self) -> None:
        start = self.script.index("async function saveTypedEditor(")
        end = self.script.index("async function createTypedRevision(", start)
        body = self.script[start:end]
        self.assertIn("if (await createTypedRevision(", body)
        self.assertGreater(body.index('setHidden("pq2-editor", true)'), body.index("await createTypedRevision("))

    def test_ambiguous_history_and_repair_paths_cannot_bypass_manual_revision(self) -> None:
        update_start = self.script.index("function updatePQButtons(")
        update_end = self.script.index("function switchTab(", update_start)
        buttons = self.script[update_start:update_end]
        self.assertGreaterEqual(buttons.count("!state.problemChainHydrated || !problemChainHeadMatchesView()"), 3)
        repair_start = self.script.index("async function requestTypedRepair(")
        repair_end = self.script.index("function renderTypedRepair(", repair_start)
        repair = self.script[repair_start:repair_end]
        self.assertIn("if (state.problemChainSupported)", repair)
        self.assertIn("PQPC_REPAIR_PATCH_UNAVAILABLE", repair)
        self.assertNotIn('api("/api/pq/v2/problem-chains/revisions"', repair)

