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

class ProblemChainExcelJourney(ProblemChainHttpHarness):
    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows Excel runtime unavailable")
    def test_left_merge_branch_uses_real_isolated_excel_runtime(self) -> None:
        """Same HTTP mutation/approval journey, with Excel COM instead of FakePQRunner."""
        class RecordingRunner:
            def __init__(self) -> None:
                script = Path(__file__).resolve().parents[2] / "tools" / "excel_connector" / "Invoke-PQCodeM.ps1"
                self.delegate = PowerShellExcelRunner(script, timeout_seconds=90)
                self.requests: list[dict] = []
                self.results: list[dict] = []

            def apply(self, request: dict) -> dict:
                self.requests.append(request)
                result = self.delegate.apply(request)
                self.results.append(result)
                return result

        runner = RecordingRunner()
        self.http_timeout_seconds = 120
        self.pq_runner = runner
        self.server.app.pq_previews.runner = runner
        self._exercise_left_merge_branch_journey()
        self.assertEqual(len(runner.results), 1)
        result = runner.results[0]
        self.assertEqual(result["resultRows"], 4)
        self.assertIn("CommissionRate", result["columns"])
        self.assertEqual(result["resultColumns"], len(result["columns"]))

