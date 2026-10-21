from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from spikes.problem_chain_custom_xml.security.contract_validator import (  # noqa: E402
    canonical_json,
    decode_xml,
    encode_xml,
    validate_document,
)


OFFICEJS = Path(__file__).resolve().parent


def node_eval(source: str, *, stdin: str = "", timeout: int = 20) -> str:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=OFFICEJS,
        input=stdin.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise AssertionError((result.stderr or result.stdout).decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8").strip()


@unittest.skipUnless(shutil.which("node"), "Node.js is not available")
class OfficeJsPythonOracleTests(unittest.TestCase):
    def test_javascript_envelope_is_accepted_by_python_contract(self) -> None:
        xml = node_eval(
            "const c=require('./problem_chain_codec');"
            "(async()=>process.stdout.write((await c.buildXml(await c.makeRepresentativeDocument())).xml))()"
            ".catch(e=>{console.error(e);process.exit(1)})"
        )
        document = decode_xml(xml)
        self.assertEqual(document["samplePersistence"]["enabled"], False)
        self.assertEqual(document["sampleStore"], {})
        self.assertIn("tiếng Việt", document["revisions"][0]["problemPrompt"])

    def test_python_envelope_is_accepted_by_javascript_codec(self) -> None:
        raw = node_eval(
            "const c=require('./problem_chain_codec');"
            "(async()=>process.stdout.write(JSON.stringify(await c.makeRepresentativeDocument())))()"
            ".catch(e=>{console.error(e);process.exit(1)})"
        )
        document = validate_document(json.loads(raw))
        xml = encode_xml(document)
        parsed = node_eval(
            "const c=require('./problem_chain_codec');let x='';"
            "process.stdin.setEncoding('utf8');process.stdin.on('data',d=>x+=d);"
            "process.stdin.on('end',async()=>process.stdout.write(JSON.stringify((await c.parseXml(x)).document)));",
            stdin=xml,
        )
        self.assertEqual(canonical_json(json.loads(parsed)), canonical_json(document))

    def test_near_limit_javascript_document_passes_python_limits(self) -> None:
        started = time.perf_counter()
        raw = node_eval(
            "const c=require('./problem_chain_codec');"
            "(async()=>process.stdout.write(JSON.stringify(await c.makeNearLimitDocument())))()"
            ".catch(e=>{console.error(e);process.exit(1)})",
            timeout=30,
        )
        document = validate_document(json.loads(raw))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        size = len(canonical_json(document))
        self.assertGreaterEqual(size, 2 * 1024 * 1024 - 4098)
        self.assertLessEqual(size, 2 * 1024 * 1024)
        print(json.dumps({"crossOracleNearLimitBytes": size, "elapsedMs": elapsed_ms}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
