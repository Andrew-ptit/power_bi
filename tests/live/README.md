# Isolated Excel task-pane gate

## Preparation feasibility scenario (feature 002)

Use `py -m tests.live.create_fixture <ignored-fixture-dir> <run-id> --scenario preparation` and `py tools/live_excel_gate.py --run-id <run-id> --out <fresh-ignored-out> --scenario preparation`. The driver reads only an exact marked synthetic target and receives invented source packages. It probes group import with sheet/name/Table collisions, formulas, date format/font/fill, personal-source copy and native captured-image restore. It does not run preparation production writes or establish its session journal.

A final `partial/native-feasibility-only` event is deliberately not qualification. Redo, external links, protected structure, partial writes and merge geometry still require additional cases. A blocked event or missing actual Office.js execution keeps production write capability disabled. The default gate scenario/driver remain unchanged.

This developer harness runs the unchanged product task-pane scripts in real
Excel/Office.js. Only the root/continuation planners are deterministic; their
output is not evidence of a live Codex call. Power Query uses the real isolated
Excel runner. The driver clicks actual DOM controls and reads back workbook
values, history and coordinator state. It refuses any workbook without the
exact `Gate_Run_Id` marker. It never targets a user's existing workbook.

From the repository root, choose a fresh run ID and output directory:

```powershell
py -m tests.live.create_fixture .artifacts/gate-<run-id>/fixture <run-id>
py tools/live_excel_gate.py --run-id <run-id> --out .artifacts/gate-<run-id>
```

The second command stays running and prints the isolated port/manifest path.
Sideload that unique manifest only into the generated fixture. If a shared
catalog is needed, add a uniquely named temporary manifest, refresh Office
Add-ins, and remove only that temporary file afterwards. Do not replace the
production manifest or certificate. Open the uniquely named gate ribbon entry.

Evidence is in `events.jsonl`. Private configuration contains an ephemeral gate
secret and stays under ignored `.artifacts`; never copy it into a report. The
two workbook exports are synthetic debugging artifacts; reports retain hashes,
counts and boolean assertions only. The final `complete/pass` record proves the
configured sequence finished; intermediate successful stages alone do not.

Default sequence: root/child commit, real Preview and explicit Confirm, complete
cache restore without another runtime call, source-change rejection with one
automatic staging Preview, cancel preserving the prior result/cache, explicit
recovery, real session-expiry handling, and completion-failure recovery.
Advanced M is **deferred by user instruction** and does not run by default.

Expiry advances only the test server's injected clock by 1,801 seconds; product
idle/absolute limits remain 1,800/28,800 seconds and normal authentication runs.
Completion failure is a one-shot fault inside the real guarded completion
method, after actual Office.js write/read-back and before cache promotion. It
tests unknown-state UX and explicit recovery; it does not simulate a physical
Excel read failure. Neither failed action is automatically replayed.

Close only the disposable workbook and stop only this gate server after use.
Keep live Codex verification separate from this deterministic planner gate.
