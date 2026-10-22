"""Run a disposable developer gate server without editing any active manifest.

This launches no Excel/UI process. Sideload only the generated unique manifest
into a synthetic workbook marked Gate_Run_Id. Deterministic planner evidence
must never be presented as live Codex evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import sys
import uuid

REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from pbip_assistant.coordinator.server import _runtime_manifest_text, _tls_context
from tests.live.server_support import create_gate_server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--parameters", type=Path)
    parser.add_argument("--certfile", type=Path, default=REPOSITORY / "tools/excel_addin/.certs/localhost.pem")
    parser.add_argument("--keyfile", type=Path, default=REPOSITORY / "tools/excel_addin/.certs/localhost.key")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", args.run_id):
        parser.error("--run-id must contain 8-80 ASCII letters, digits, '_' or '-'")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "config.json").exists():
        parser.error("Choose a fresh --out directory; a gate configuration already exists")
    parameters = json.loads(args.parameters.read_text(encoding="utf-8")) if args.parameters else {}
    config = {
        "runId": args.run_id, "gateKey": secrets.token_hex(32), "channel": secrets.token_hex(12),
        "appId": str(uuid.uuid4()), "displayName": "Excel Gate " + args.run_id[:24],
        "markerName": "Gate_Run_Id", "planner": "deterministic",
        "driverPath": str(REPOSITORY / "tests/live/taskpane_gate_driver.js"),
        "outputPath": str(output), "manifestPath": str(output / "manifest.xml"),
        "driverParameters": parameters,
    }
    context = _tls_context(args.certfile, args.keyfile)
    server = None
    for port in ((args.port,) if args.port is not None else range(3078, 3071, -1)):
        try:
            server = create_gate_server(output, config, port=port, ssl_context=context)
            break
        except OSError as exc:
            if args.port is not None or (getattr(exc, "winerror", None) != 10048 and getattr(exc, "errno", None) not in {48, 98, 10048}):
                raise
    if server is None:
        raise OSError("No free isolated gate port available")
    try:
        template = (REPOSITORY / "tools/excel_addin/manifest.xml").read_text(encoding="utf-8-sig")
        manifest = _runtime_manifest_text(template, server.server_port, config["channel"])
        manifest = re.sub(r"<Id>[^<]+</Id>", "<Id>" + config["appId"] + "</Id>", manifest, count=1)
        manifest = re.sub(r'<DisplayName DefaultValue="[^"]+"', '<DisplayName DefaultValue="' + config["displayName"] + '"', manifest, count=1)
        manifest = re.sub(r'(<bt:String id="Group.Label" DefaultValue=")[^"]+', r'\g<1>' + config["displayName"], manifest)
        manifest = manifest.replace("?channel=" + config["channel"], "?channel=" + config["channel"] + "&amp;gateKey=" + config["gateKey"])
        from xml.etree import ElementTree
        ElementTree.fromstring(manifest)
        (output / "manifest.xml").write_text(manifest, encoding="utf-8")
        (output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ready", "runId": args.run_id, "baseUrl": config["baseUrl"],
                          "appId": config["appId"], "manifestPath": str(output / "manifest.xml"), "planner": "deterministic"}), flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
