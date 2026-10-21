"""W-02 fixture contract tests; these do not test a future CSV importer."""

from __future__ import annotations

from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from examples.source_fixtures import EXPECTED, ORDER_HEADERS, build_fixtures, generate


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "source"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def csv_rows(path: Path, *, delimiter: str = ",", encoding: str = "utf-8") -> list[list[str]]:
    with path.open("r", encoding=encoding, newline="") as source:
        return list(csv.reader(source, delimiter=delimiter))


class SourceFixtureTests(unittest.TestCase):
    def test_header_matches_only_reference_header_and_is_not_source_data(self) -> None:
        # Committed synthetic header and independent provenance digest keep this
        # contract reproducible without a user's private local CSV.
        source = FIXTURE_DIR / "orders_synthetic.csv"
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            source_header = next(csv.reader([handle.readline()]))
        self.assertEqual(tuple(source_header), ORDER_HEADERS)
        manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["provenance"]["source_rows_used"], 0)
        self.assertTrue(manifest["provenance"]["synthetic_records"])
        self.assertEqual(
            manifest["provenance"]["header_sha256"],
            hashlib.sha256(",".join(ORDER_HEADERS).encode("utf-8")).hexdigest(),
        )
        self.assertTrue(all(row[0].startswith("SYN-") for row in csv_rows(FIXTURE_DIR / "orders_synthetic.csv")[1:]))

    def test_committed_artifacts_have_exact_manifest_hashes_and_expected_cases(self) -> None:
        manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), set(EXPECTED))
        self.assertEqual(
            {p.name for p in FIXTURE_DIR.iterdir()},
            {*EXPECTED, "manifest.json"},
        )
        for name, entry in manifest["files"].items():
            with self.subTest(name=name):
                payload = (FIXTURE_DIR / name).read_bytes()
                self.assertEqual(entry["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(entry["bytes"], len(payload))
                self.assertEqual(entry["expected"], EXPECTED[name])

    def test_generation_is_byte_for_byte_deterministic_and_matches_committed_set(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            generate(Path(first))
            generate(Path(second))
            for name in (*EXPECTED, "manifest.json"):
                with self.subTest(name=name):
                    first_bytes = (Path(first) / name).read_bytes()
                    self.assertEqual(first_bytes, (Path(second) / name).read_bytes())
                    self.assertEqual(first_bytes, (FIXTURE_DIR / name).read_bytes())
        self.assertEqual(set(build_fixtures()), set(EXPECTED))

    def test_order_totals_statuses_nulls_and_orphan_key(self) -> None:
        rows = csv_rows(FIXTURE_DIR / "orders_synthetic.csv")
        self.assertEqual(rows[0], list(ORDER_HEADERS))
        data = [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]
        expected = EXPECTED["orders_synthetic.csv"]
        self.assertEqual(len(data), expected["records"])
        self.assertEqual(dict(Counter(row["Status"] for row in data)), expected["statuses"])
        self.assertEqual(sum(int(row["Quantity"]) for row in data), expected["quantity_total"])
        self.assertEqual(sum((Decimal(row["Sales"]) for row in data), Decimal(0)), Decimal(expected["sales_total"]))
        self.assertEqual({name: sum(row[name] == "" for row in data) for name in expected["nulls"]}, expected["nulls"])
        products = {row[0] for row in csv_rows(FIXTURE_DIR / "products_synthetic.csv")[1:]}
        self.assertEqual(sorted({row["ProductID"] for row in data} - products), expected["orphan_product_ids"])
        self.assertEqual(len({row["CustomerID"] for row in data}), 4)
        self.assertEqual({row["Discount"] for row in data}, {"0", "5", "10", "30"})
        self.assertIn("03/09/2026", {row["OrderDate"] for row in data})

    def test_csv_encoding_delimiters_multiline_and_malformed_rows(self) -> None:
        bom = FIXTURE_DIR / "orders_utf8_bom.csv"
        self.assertTrue(bom.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(len(csv_rows(bom, encoding="utf-8-sig")) - 1, 6)
        semi = csv_rows(FIXTURE_DIR / "orders_semicolon.csv", delimiter=";")
        self.assertEqual(semi[0], list(ORDER_HEADERS))
        self.assertEqual(len(semi) - 1, 6)
        quoted_path = FIXTURE_DIR / "orders_quoted_multiline.csv"
        quoted = csv_rows(quoted_path)
        self.assertEqual(len(quoted) - 1, EXPECTED["orders_quoted_multiline.csv"]["records"])
        self.assertIn("\n", quoted[2][12])
        self.assertIn(",", quoted[1][12])
        self.assertEqual(len(quoted_path.read_text(encoding="utf-8").splitlines()), 4)
        for name, width in (("orders_short_row.csv", 16), ("orders_wide_row.csv", 18)):
            with self.subTest(name=name):
                rows = csv_rows(FIXTURE_DIR / name)
                self.assertEqual(len(rows[0]), 17)
                self.assertEqual(len(rows[1]), width)
                self.assertEqual(EXPECTED[name]["actual_columns"], width)
                self.assertEqual(EXPECTED[name]["result"], "row_error")
        with self.assertRaises(UnicodeDecodeError):
            (FIXTURE_DIR / "orders_invalid_utf8.csv").read_text(encoding="utf-8")

    def test_csv_schema_ambiguity_and_dimension_counts(self) -> None:
        drift = csv_rows(FIXTURE_DIR / "orders_schema_drift.csv")
        self.assertEqual(sorted(set(ORDER_HEADERS) - set(drift[0])), EXPECTED["orders_schema_drift.csv"]["missing"])
        self.assertEqual(sorted(set(drift[0]) - set(ORDER_HEADERS)), sorted(EXPECTED["orders_schema_drift.csv"]["added"]))
        duplicate = csv_rows(FIXTURE_DIR / "orders_duplicate_header.csv")[0]
        self.assertEqual([value for value, count in Counter(duplicate).items() if count > 1], ["Sales"])
        ambiguous = csv_rows(FIXTURE_DIR / "orders_ambiguous_discount.csv", delimiter=";")
        self.assertEqual([row[5] for row in ambiguous[1:]], EXPECTED["orders_ambiguous_discount.csv"]["values"])
        self.assertEqual(len(csv_rows(FIXTURE_DIR / "orders_header_only.csv")) - 1, 0)
        for table, expected_count in (("products_synthetic.csv", 3), ("customers_synthetic.csv", 4), ("calendar_synthetic.csv", 7)):
            with self.subTest(table=table):
                self.assertEqual(len(csv_rows(FIXTURE_DIR / table)) - 1, expected_count)

    def test_xlsx_is_well_formed_with_table_date_style_and_formula_cache_variants(self) -> None:
        for filename, expected_cache in (("orders_synthetic.xlsx", "180"), ("orders_formula_no_cache.xlsx", None)):
            with self.subTest(filename=filename), ZipFile(FIXTURE_DIR / filename) as archive:
                names = archive.namelist()
                self.assertIn("xl/tables/table1.xml", names)
                self.assertIn("xl/styles.xml", names)
                for name in names:
                    if name.endswith((".xml", ".rels")):
                        ET.fromstring(archive.read(name))
                self.assertTrue(all(info.date_time == (2026, 1, 1, 0, 0, 0) for info in archive.infolist()))
                table = ET.fromstring(archive.read("xl/tables/table1.xml"))
                self.assertEqual(table.attrib["name"], "OrdersTable")
                self.assertEqual(table.attrib["ref"], "A1:Q7")
                self.assertEqual(len(table.findall(f"{{{MAIN}}}tableColumns/{{{MAIN}}}tableColumn")), 17)
                styles = ET.fromstring(archive.read("xl/styles.xml"))
                self.assertEqual(styles.find(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt").attrib["formatCode"], "yyyy-mm-dd")
                sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                self.assertEqual(len(sheet.findall(f"{{{MAIN}}}sheetData/{{{MAIN}}}row")) - 1, 6)
                self.assertEqual(sheet.find(f".//{{{MAIN}}}c[@r='C2']").attrib["s"], "1")
                formula_cell = sheet.find(f".//{{{MAIN}}}c[@r='P2']")
                self.assertEqual(formula_cell.find(f"{{{MAIN}}}f").text, "E2*O2*(1-F2/100)")
                self.assertEqual(formula_cell.find(f"{{{MAIN}}}v").text, expected_cache)


if __name__ == "__main__":
    unittest.main()
