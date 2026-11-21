"""Create only a synthetic, marked workbook for the isolated live UI driver."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from examples.excel_mcp_fixtures import generate


def create_fixture(output: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", run_id):
        raise ValueError("Invalid isolated run ID")
    target = output / "excel_mcp_sales_input.xlsx"
    if target.exists():
        raise FileExistsError(target)
    generate(output)
    with ZipFile(target) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    workbook = ET.fromstring(members["xl/workbook.xml"])
    names = ET.Element(ns + "definedNames")
    ET.SubElement(names, ns + "definedName", name="Gate_Run_Id").text = '"' + run_id + '"'
    # OOXML definedNames precedes calcPr; do not rely on Excel repair.
    workbook.insert(list(workbook).index(workbook.find(ns + "calcPr")), names)
    members["xl/workbook.xml"] = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("--scenario", choices=("default", "preparation"), default="default")
    args = parser.parse_args()
    if args.scenario == "preparation":
        from tests.support.preparation import create_preparation_fixture
        print(create_preparation_fixture(args.output, args.run_id))
    else:
        print(create_fixture(args.output, args.run_id))
