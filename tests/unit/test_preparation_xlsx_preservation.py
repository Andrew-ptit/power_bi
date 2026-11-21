"""Native normalization boundary; these tests do not qualify Excel semantics."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from pbip_assistant.errors import InputError
from tests.support.preparation import preparation_workbook


class NamespaceBoundaryTests(unittest.TestCase):
    def test_namespace_plan_covers_all_sheet_scopes_and_tables_without_rewriting_source(self):
        from pbip_assistant.sources.preparation.xlsx_preservation import namespace_plan
        source = preparation_workbook()
        plan = namespace_plan(source, {"Orders": "Orders_2", "Rates": "Rates_2"}, "abcdef1234567890")
        self.assertEqual(plan["sheets"], [{"sourceName": "Orders", "targetName": "Orders_2"}, {"sourceName": "Rates", "targetName": "Rates_2"}])
        self.assertEqual(plan["names"], [{"name": "TaxRate", "scope": "workbook", "targetName": "_dp_abcdef1234567890_n0"}, {"name": "LocalRate", "scope": "Rates", "targetName": "_dp_abcdef1234567890_n1"}])
        self.assertEqual(plan["tables"], [{"name": "OrdersTable", "targetName": "_dp_abcdef1234567890_t0"}])
        self.assertEqual(plan["sourceSha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(source, preparation_workbook())

    def test_partial_group_is_rejected_before_native_runner(self):
        from pbip_assistant.sources.preparation.xlsx_preservation import namespace_plan
        with self.assertRaises(InputError) as caught:
            namespace_plan(preparation_workbook(), {"Orders": "Orders_2"}, "abcdef1234567890")
        self.assertEqual(caught.exception.code, "DP_UNSUPPORTED_PRESERVATION")

    def test_normalizer_only_passes_temporary_copy_and_never_accepts_missing_output(self):
        from pbip_assistant.sources.preparation.xlsx_preservation import normalize_workbook
        source = preparation_workbook()
        class Runner:
            def apply(self, request):
                self.request = request
                self.assertion = Path(request["workbookPath"]).read_bytes() == source
                return {"ok": True}
        runner = Runner()
        with self.assertRaises(InputError) as caught:
            normalize_workbook(source, {"Orders": "Orders_2", "Rates": "Rates_2"}, runner=runner)
        self.assertTrue(runner.assertion)
        self.assertEqual(caught.exception.code, "DP_UNSUPPORTED_PRESERVATION")
        self.assertFalse(Path(runner.request["workbookPath"]).exists())
