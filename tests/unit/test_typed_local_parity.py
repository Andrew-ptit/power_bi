"""Parity wiring scaffold only; this file supplies no live Excel evidence.

The implemented Excel/M comparison lives in tests.runtime.test_typed_local_parity_runtime,
outside the fast gate. Having powershell.exe alone does not establish Excel or
parity availability; this retained case never supplies runtime authority.
"""

import shutil
import unittest

from pbip_assistant.powerquery.typed.compiler import compile_m
from pbip_assistant.powerquery.typed_local import execute_plan
from tests.unit.test_typed_local import all_operations_fixture


def run_m_in_excel(m_code, tables):
    raise unittest.SkipTest("Excel/M parity runs in tests.runtime.test_typed_local_parity_runtime, outside fast; no runtime authority is granted here")


class TypedLocalParityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("powershell.exe"), "PowerShell/Excel runtime unavailable")
    def test_python_executor_matches_excel_m_for_same_plan(self):
        plan, tables = all_operations_fixture()
        python_rows = execute_plan(plan, tables)["rows"]
        m_rows = run_m_in_excel(compile_m(plan), tables)
        self.assertEqual(m_rows, python_rows)
