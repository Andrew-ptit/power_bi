from __future__ import annotations

from io import BytesIO
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from pbip_assistant.workbook_fingerprint import MAIN, workbook_data_fingerprint
from tests.support.excel_plan import FIXTURE_ROOT


def repack(payload: bytes, *, change_cell: bool = False) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(payload)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if change_cell and item.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(data)
                cell = next(node for node in root.iter(f"{{{MAIN}}}c") if node.find(f"{{{MAIN}}}v") is not None)
                value = cell.find(f"{{{MAIN}}}v")
                value.text = "999999" if value.text != "999999" else "888888"
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item.filename, data)
    return output.getvalue()


