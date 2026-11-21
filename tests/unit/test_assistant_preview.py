"""Kiểm dựng kết quả và XLSX tạm WL5; chỉ dùng nguồn synthetic đã nạp."""

from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_STORED

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import (
    MAX_SOURCE_EVIDENCE_BYTES, RESULT_COLUMNS, _verify_workbook, build_preview, build_workbook, preview_marker,
    result_digest, result_rows, temp_workspace,
)
from pbip_assistant.sources.assistant_spec import spec_fingerprint
from tests.support import assistant_fin, assistant_sales
from tests.unit.test_assistant_brief import inputs, make
from tests.unit.test_assistant_spec import model, create


def pipeline(scenario="tp-fin", *, data=None, overrides=None):
    data = data if data is not None else inputs(scenario)
    brief = make(data)
    _, decisions, pack = model(scenario, brief=brief, overrides=overrides)
    spec = create((brief, decisions, pack), scenario)
    result = result_rows(data[0]["tables"], spec, decisions, pack)
    return data, spec, decisions, pack, result


def marker(spec, sheet):
    return "LOCAL_DATA_COPILOT|" + sheet + "|spec=" + spec["fingerprint"] + "|labels=" + ",".join(spec["labels"])


def state(paths):
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}


def read_source_evidence(scenario):
    """Caller nạp original text trước stage engine; giữ nguyên newline/BOM UTF-8."""
    root = assistant_fin.ROOT / scenario / "source"
    return {path.relative_to(root).as_posix(): path.read_bytes().decode("utf-8")
            for path in sorted(root.rglob("*.csv"))}


class AssistantPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fin = pipeline()
        cls.sales = pipeline("tp-sales")
        cls.evidence = {scenario: read_source_evidence(scenario) for scenario in ("tp-fin", "tp-sales")}

    def test_fin_and_sales_result_dimensions_and_sort_order(self):
        for scenario, data, dimensions in (("tp-fin", self.fin, (23, 9)), ("tp-sales", self.sales, (4, 4))):
            result = data[-1]
            self.assertEqual(result["columns"], RESULT_COLUMNS[scenario])
            self.assertEqual((len(result["rows"]), len(result["columns"])), dimensions)
            self.assertTrue(all(len(row) == dimensions[1] for row in result["rows"]))
            key_columns = 4 if scenario == "tp-fin" else 1
            self.assertEqual(result["rows"], sorted(result["rows"], key=lambda row: row[:key_columns]))

    def test_fin_rows_match_independent_oracle_and_exact_control(self):
        _, oracle = assistant_fin.compute()
        self.assertEqual(self.fin[-1]["rows"], [list(row) for row in oracle["result"]])
        self.assertEqual(sum((row[4] for row in self.fin[-1]["rows"]), Decimal("0")), Decimal("14206900000"))
        for row in self.fin[-1]["rows"]:
            self.assertEqual(row[6], row[4] - row[5])

    def test_sales_rows_match_independent_oracle_keep_negative_returns(self):
        _, oracle = assistant_sales._metrics(assistant_sales._tables())
        expected = [[row["region"], Decimal(row["revenue"]), row["orders"], row["customers"]] for row in oracle]
        self.assertEqual(self.sales[-1]["rows"], expected)
        self.assertEqual(sum((row[1] for row in expected), Decimal("0")), Decimal("133942500"))

    def test_numeric_context_isolation_and_input_immutability(self):
        data, spec, decisions, pack, expected = self.fin
        before = deepcopy((data, spec, decisions, pack))
        with localcontext() as context:
            context.prec = 6
            actual = result_rows(data[0]["tables"], spec, decisions, pack)
        self.assertEqual(actual, expected)
        actual["rows"][0][0] = "changed"
        self.assertEqual((data, spec, decisions, pack), before)

    def test_result_digest_binds_values_and_distinguishes_text_from_numbers(self):
        first = self.fin[-1]
        changed = deepcopy(first)
        changed["rows"][0][4] += Decimal("1")
        self.assertNotEqual(result_digest(first), result_digest(changed))
        changed = deepcopy(first)
        changed["rows"][0][4] = str(changed["rows"][0][4])
        self.assertNotEqual(result_digest(first), result_digest(changed))
        self.assertEqual(result_digest({"columns": ["x"], "rows": [[Decimal("1.00")]]}),
                         result_digest({"columns": ["x"], "rows": [[1]]}))

    def test_preview_shape_dimensions_counts_and_runtime_source_fingerprint(self):
        for scenario, data, sheet in (("tp-fin", self.fin, "PnL_Preview"), ("tp-sales", self.sales, "Sales_Preview")):
            ingest, spec, _, _, result = data
            snapshot = ingest[1]
            actual = build_preview(result, spec, snapshot, sheet=sheet, marker=marker(spec, sheet))
            expected = json.loads((assistant_fin.ROOT / scenario / "wl5_preview.json").read_text(encoding="utf-8"))
            self.assertEqual(set(actual), set(expected))
            self.assertEqual(actual["sheets"], expected["sheets"])
            self.assertEqual(actual["counts"], expected["counts"])
            self.assertEqual(actual["target"]["sheet"], expected["target"]["sheet"])
            self.assertEqual(actual["target"]["mode"], "values_only")
            self.assertEqual(actual["specFingerprint"], spec["fingerprint"])
            digest = canonical_hash([source["hash"] for source in snapshot["sources"]])
            self.assertEqual(actual["source"], {"before": digest, "after": digest, "unchanged": True})

    def test_preview_golden_source_fingerprint_with_matching_legacy_snapshot_spec(self):
        for scenario, data, sheet in (("tp-fin", self.fin, "PnL_Preview"), ("tp-sales", self.sales, "Sales_Preview")):
            root = assistant_fin.ROOT / scenario
            snapshot = json.loads((root / "wl1_snapshot.json").read_text(encoding="utf-8"))
            brief = json.loads((root / "wl3_brief.json").read_text(encoding="utf-8"))
            contract = model(scenario, brief=brief)
            spec = create(contract, scenario)
            result = result_rows(data[0][0]["tables"], spec, contract[1], contract[2])
            actual = build_preview(result, spec, snapshot, sheet=sheet, marker=marker(spec, sheet),
                                   source_evidence=self.evidence[scenario])
            expected = json.loads((root / "wl5_preview.json").read_text(encoding="utf-8"))
            self.assertEqual(actual["source"], expected["source"])

    def test_original_source_evidence_verifies_runtime_csv_and_folder_hashes(self):
        for scenario, data, sheet in (("tp-fin", self.fin, "PnL_Preview"), ("tp-sales", self.sales, "Sales_Preview")):
            ingest, spec, _, _, result = data
            evidence = self.evidence[scenario]
            actual = build_preview(result, spec, ingest[1], sheet=sheet, marker=marker(spec, sheet), source_evidence=evidence)
            digest = (canonical_hash([{name: evidence[name]} for name in sorted(evidence)]) if scenario == "tp-sales"
                      else canonical_hash([source["hash"] for source in ingest[1]["sources"]]))
            self.assertEqual(actual["source"], {"before": digest, "after": digest, "unchanged": True})

    def test_source_evidence_mismatch_missing_extra_or_invalid_shape_is_rejected(self):
        data, spec, _, _, result = self.sales
        original = self.evidence["tp-sales"]
        first = next(iter(original))
        folder = next(key for key in original if "/" in key)
        mismatch = {**original, first: original[first] + "\n"}
        folder_mismatch = {**original, folder: original[folder] + "\n"}
        missing = {key: value for key, value in original.items() if key != first}
        missing_folder = {key: value for key, value in original.items() if key != folder}
        extra = {**original, "Extra.csv": "synthetic"}
        cases = [mismatch, folder_mismatch, missing, missing_folder, extra, {}, [],
                 {**original, "../escape.csv": "synthetic"}, {**original, "/absolute.csv": "synthetic"},
                 {**original, "nested\\file.csv": "synthetic"}, {**original, first: b"bytes"},
                 {str(index) + ".csv": "synthetic" for index in range(129)}]
        for index, evidence in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(InputError):
                build_preview(result, spec, data[1], sheet="Sales_Preview", marker=marker(spec, "Sales_Preview"), source_evidence=evidence)

    def test_source_evidence_byte_cap_is_checked_before_workbook_allocation(self):
        data, spec, _, _, result = self.sales
        evidence = dict(self.evidence["tp-sales"])
        evidence[next(iter(evidence))] = "x" * (MAX_SOURCE_EVIDENCE_BYTES + 1)
        with patch("pbip_assistant.sources.assistant_preview.build_workbook", side_effect=AssertionError("Không được dựng workbook trước evidence guard")):
            with self.assertRaises(InputError) as caught:
                build_preview(result, spec, data[1], sheet="Sales_Preview", marker=marker(spec, "Sales_Preview"), source_evidence=evidence)
        self.assertEqual(caught.exception.code, "AF_PREVIEW_INVALID")

    def test_preview_marker_binds_payload_without_hash_self_reference(self):
        data, spec, _, _, result = self.fin
        actual = build_preview(result, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        stamped = actual["target"]["marker"]
        self.assertEqual(stamped, preview_marker(result, spec, sheet="PnL_Preview"))
        self.assertIn("|spec=" + spec["fingerprint"], stamped)
        self.assertIn("|preview=" + result_digest(result), stamped)
        self.assertIn("|labels=" + ",".join(spec["labels"]), stamped)
        self.assertNotIn(actual["previewHash"], stamped)
        self.assertEqual(actual, build_preview(result, spec, data[1], sheet="PnL_Preview", marker=stamped))

    def test_preview_hash_and_workbook_are_deterministic_with_recompute(self):
        for data, sheet in ((self.fin, "PnL_Preview"), (self.sales, "Sales_Preview")):
            ingest, spec, _, _, result = data
            first = build_preview(result, spec, ingest[1], sheet=sheet, marker=marker(spec, sheet))
            repeated = build_preview(result, spec, ingest[1], sheet=sheet, marker=marker(spec, sheet))
            self.assertEqual(first, repeated)
            self.assertEqual(first["previewHash"], canonical_hash({key: first[key] for key in first["hashBasis"]}))
            self.assertEqual(build_workbook(**result, sheet=sheet, marker=first["target"]["marker"]),
                             build_workbook(**result, sheet=sheet, marker=repeated["target"]["marker"]))

    def test_payload_change_alone_changes_preview_hash_at_same_spec_and_dimensions(self):
        data, spec, _, _, result = self.fin
        changed = deepcopy(result)
        changed["rows"][0][4] += Decimal("1")
        first = build_preview(result, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        second = build_preview(changed, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        self.assertEqual(first["sheets"], second["sheets"])
        self.assertEqual(first["source"], second["source"])
        self.assertNotEqual(first["previewHash"], second["previewHash"])
        self.assertNotEqual(first["target"]["marker"], second["target"]["marker"])
        with self.assertRaises(InputError) as caught:
            build_preview(changed, spec, data[1], sheet="PnL_Preview", marker=first["target"]["marker"])
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_preview_rejects_snapshot_revision_or_content_changes(self):
        data, spec, _, _, result = self.fin
        for change in ("hash", "content"):
            snapshot = deepcopy(data[1])
            if change == "hash":
                snapshot["snapshotHash"] = canonical_hash("other")
            else:
                snapshot["tables"][0]["rowCount"] += 1
            with self.subTest(change=change), self.assertRaises(InputError) as caught:
                build_preview(result, spec, snapshot, sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
            self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_preview_rejects_wrong_sheet_schema_marker_and_forged_labels(self):
        data, spec, _, _, result = self.fin
        cases = [(result, "Other_Preview", marker(spec, "Other_Preview")),
                 (result, "PnL_Preview", "LOCAL_DATA_COPILOT|PnL_Preview|spec=bad|labels=verified"),
                 ({"columns": ["unknown"], "rows": [[1]]}, "PnL_Preview", marker(spec, "PnL_Preview")),
                 ({**result, "hiddenPolicy": "B"}, "PnL_Preview", marker(spec, "PnL_Preview"))]
        for candidate, sheet, stamp in cases:
            with self.subTest(sheet=sheet), self.assertRaises(InputError):
                build_preview(candidate, spec, data[1], sheet=sheet, marker=stamp)

    def test_preview_does_not_mutate_result_spec_or_snapshot(self):
        data, spec, _, _, result = self.fin
        before = deepcopy((result, spec, data[1]))
        first = build_preview(result, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        first["source"]["after"] = "changed"
        first["target"]["marker"] = "changed"
        self.assertEqual((result, spec, data[1]), before)

    def test_policy_b_is_rejected_instead_of_silently_running_a(self):
        for scenario in ("tp-fin", "tp-sales"):
            with self.subTest(scenario=scenario), self.assertRaises(InputError) as caught:
                pipeline(scenario, overrides={"SP-1": "B"})
            self.assertEqual(caught.exception.code, "AF_POLICY_UNSUPPORTED")

    def test_unsupported_grain_or_reordered_closed_plan_is_not_silently_ignored(self):
        data, spec, decisions, pack, _ = self.fin
        changed = deepcopy(spec)
        for step in changed["steps"]:
            if step["kind"] == "group":
                step["params"]["columns"] = ["pnlLine"]
            if step["params"]["operation"] == "join_budget":
                step["params"]["rightGrain"] = ["pnlLine"]
        changed["fingerprint"] = spec_fingerprint(changed)
        with self.assertRaises(InputError) as caught:
            result_rows(data[0]["tables"], changed, decisions, pack)
        self.assertEqual(caught.exception.code, "AF_POLICY_UNSUPPORTED")
        changed = deepcopy(spec)
        left, right = changed["steps"][1], changed["steps"][2]
        left["kind"], right["kind"] = right["kind"], left["kind"]
        left["params"], right["params"] = right["params"], left["params"]
        changed["fingerprint"] = spec_fingerprint(changed)
        with self.assertRaises(InputError) as caught:
            result_rows(data[0]["tables"], changed, decisions, pack)
        self.assertEqual(caught.exception.code, "AF_POLICY_UNSUPPORTED")

    def test_stale_or_tampered_spec_and_changed_decisions_are_rejected(self):
        data, spec, decisions, pack, _ = self.fin
        changed = deepcopy(spec)
        changed["steps"][0]["label"] += " changed"
        with self.assertRaises(InputError):
            result_rows(data[0]["tables"], changed, decisions, pack)
        changed = deepcopy(spec)
        changed["stale"] = True
        changed["fingerprint"] = spec_fingerprint(changed)
        with self.assertRaises(InputError) as caught:
            result_rows(data[0]["tables"], changed, decisions, pack)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        changed = deepcopy(decisions)
        changed["decisions"][0]["optionId"] = "B"
        with self.assertRaises(InputError):
            result_rows(data[0]["tables"], spec, changed, pack)

    def test_malformed_and_missing_required_sources_fail_closed(self):
        data, spec, decisions, pack, _ = self.fin
        for raw in (None, [], [None], [{"header": [], "rows": []}]):
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(InputError):
                result_rows(raw, spec, decisions, pack)
        raw = deepcopy(data[0]["tables"])
        raw = [table for table in raw if "RateType" not in table["header"]]
        with self.assertRaises(InputError) as caught:
            result_rows(raw, spec, decisions, pack)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")

    def test_missing_average_rate_used_raises_without_fabricating_values(self):
        data, spec, decisions, pack, _ = self.fin
        raw = deepcopy(data[0]["tables"])
        ledger = next(table for table in raw if "DebitCredit" in table["header"])
        ledger["rows"][0][ledger["header"].index("Currency")] = "EUR"
        with self.assertRaises(InputError) as caught:
            result_rows(raw, spec, decisions, pack)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")

    def test_rate_mutation_recomputes_actual_cells_without_static_values(self):
        data, spec, decisions, pack, before = self.fin
        raw = deepcopy(data[0]["tables"])
        rates = next(table for table in raw if "RateType" in table["header"])
        fields = rates["header"]
        target = next(row for row in rates["rows"] if row[fields.index("CurrencyCode")] == "USD"
                      and row[fields.index("Month")] == "2026-09" and row[fields.index("RateType")] == "average")
        target[fields.index("Rate")] = "24000"
        after = result_rows(raw, spec, decisions, pack)
        net = lambda result: sum((row[4] for row in result["rows"] if row[0] == "NetRevenue"), Decimal("0"))
        self.assertEqual(net(after) - net(before), Decimal("1450000") * Decimal("-300"))
        self.assertNotEqual(result_digest(before), result_digest(after))
        self.assertEqual(len(after["rows"]), 23)
        first = build_preview(before, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        second = build_preview(after, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        self.assertNotEqual(first["previewHash"], second["previewHash"])

    def test_workbook_is_byte_equal_with_fixed_entries_and_sheet_names(self):
        for scenario, data, sheet in (("tp-fin", self.fin, "PnL_Preview"), ("tp-sales", self.sales, "Sales_Preview")):
            with self.subTest(scenario=scenario):
                result = data[-1]
                stamped = marker(data[1], sheet)
                first = build_workbook(**result, sheet=sheet, marker=stamped)
                self.assertEqual(first, build_workbook(**result, sheet=sheet, marker=stamped))
                with ZipFile(io.BytesIO(first)) as archive:
                    self.assertTrue(all(entry.date_time == (2026, 1, 1, 0, 0, 0) for entry in archive.infolist()))
                    self.assertTrue(all(entry.compress_type == ZIP_STORED for entry in archive.infolist()))
                    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                    self.assertEqual(next(element for element in workbook.iter() if element.tag.endswith("}sheet")).get("name"), sheet)

    def test_workbook_has_no_formula_query_connection_and_marker_outside_result(self):
        result = self.fin[-1]
        stamped = marker(self.fin[1], "PnL_Preview")
        payload = build_workbook(**result, sheet="PnL_Preview", marker=stamped)
        with ZipFile(io.BytesIO(payload)) as archive:
            self.assertFalse(any("queryTables" in name or "externalLinks" in name or name == "xl/connections.xml" for name in archive.namelist()))
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            self.assertFalse(any(element.tag.endswith("}f") for element in sheet.iter()))
            rows = [element for element in sheet.iter() if element.tag.endswith("}row")]
            headers = [element.text for element in rows[0].iter() if element.tag.endswith("}t")]
            self.assertEqual(headers, result["columns"])
            self.assertEqual(rows[-1].get("r"), str(len(result["rows"]) + 3))
            self.assertIn(stamped, [element.text for element in rows[-1].iter()])

    def test_formula_looking_text_and_xml_metacharacters_stay_inert_inline_values(self):
        text = '=HYPERLINK("x")<f>not-a-formula</f>&'
        payload = build_workbook(["text"], [[text]], sheet="Preview", marker="LOCAL_DATA_COPILOT|Preview")
        with ZipFile(io.BytesIO(payload)) as archive:
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            self.assertFalse(any(element.tag.endswith("}f") for element in sheet.iter()))
            self.assertIn(text, [element.text for element in sheet.iter() if element.tag.endswith("}t")])

    def test_forbidden_workbook_members_and_formula_are_detected(self):
        for name, content in (("xl/connections.xml", "<connections/>"), ("xl/queryTables/query.xml", "<query/>"),
                              ("xl/externalLinks/link.xml", "<link/>"), ("xl/worksheets/sheet1.xml", "<worksheet><f>1+1</f></worksheet>")):
            stream = io.BytesIO()
            with ZipFile(stream, "w") as archive:
                archive.writestr(name, content)
            with self.subTest(name=name), self.assertRaises(InputError):
                _verify_workbook(stream.getvalue())

    def test_invalid_sheet_cells_width_and_limits_fail_before_output(self):
        cases = [(["x"], [[1.2]], "Preview"), (["x"], [[Decimal("NaN")]], "Preview"),
                 (["x"], [[True]], "Preview"), (["x"], [["\x00"]], "Preview"),
                 (["x"], [[1, 2]], "Preview"), (["x", "x"], [[1, 2]], "Preview"),
                 (["x"], [[1]], "bad/sheet"), (["x"], [[1]], "x" * 32),
                 (["x"], [[Decimal("1e1000")]], "Preview")]
        for columns, rows, sheet in cases:
            with self.subTest(sheet=sheet), self.assertRaises(InputError):
                build_workbook(columns, rows, sheet=sheet, marker="LOCAL_DATA_COPILOT|Preview")

    def test_workbook_byte_budget_is_checked_before_xml_and_zip_allocation(self):
        rows = [["&" * 32767] for _ in range(120)]
        with patch("pbip_assistant.sources.assistant_preview.ZipFile", side_effect=AssertionError("Không được dựng ZIP trước byte guard")):
            with self.assertRaises(InputError) as caught:
                build_workbook(["large"], rows, sheet="Preview", marker="LOCAL_DATA_COPILOT|Preview")
        self.assertEqual(caught.exception.code, "AF_PREVIEW_INVALID")

    def test_temp_workspace_is_outside_repo_and_cleans_on_success_and_exception(self):
        repository = Path(__file__).resolve().parents[2]
        for fail in (False, True):
            directory = None
            try:
                with temp_workspace() as directory:
                    self.assertFalse(directory.is_relative_to(repository))
                    (directory / "preview.xlsx").write_bytes(b"synthetic")
                    self.assertTrue(directory.is_dir())
                    if fail:
                        raise RuntimeError("synthetic cleanup")
            except RuntimeError:
                pass
            self.assertIsNotNone(directory)
            self.assertFalse(directory.exists())

    def test_source_sha_and_mtime_preserved_and_no_source_reopen_after_ingest(self):
        root = assistant_fin.ROOT
        paths = [path for scenario in ("tp-fin", "tp-sales") for path in (root / scenario / "source").rglob("*.csv")]
        paths += [root / scenario / "wl1_snapshot.json" for scenario in ("tp-fin", "tp-sales")]
        before = state(paths)
        opened = set(paths)
        original_open = Path.open
        def guarded(path, *args, **kwargs):
            if path in opened:
                raise AssertionError("Preview không được mở lại file nguồn")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            for data in (self.fin, self.sales):
                ingest, spec, decisions, pack, _ = data
                result = result_rows(ingest[0]["tables"], spec, decisions, pack)
                sheet = "PnL_Preview" if pack["id"] == "fin-pl-v1" else "Sales_Preview"
                scenario = "tp-fin" if pack["id"] == "fin-pl-v1" else "tp-sales"
                preview = build_preview(result, spec, ingest[1], sheet=sheet, marker=marker(spec, sheet),
                                        source_evidence=self.evidence[scenario])
                with temp_workspace() as directory:
                    (directory / "preview.xlsx").write_bytes(build_workbook(**result, sheet=sheet, marker=preview["target"]["marker"]))
        self.assertEqual(state(paths), before)


if __name__ == "__main__":
    unittest.main()
