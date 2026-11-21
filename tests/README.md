# Test suite

One gate command answers "is the product still correct?":

```powershell
py tools/run_checks.py fast            # unit, contracts, integration, journeys, task pane, web
py tools/run_checks.py fast --quiet    # same selection, one dot per test (~25% faster)
py tools/run_checks.py runtime         # Excel/.NET, serial, needs Windows + Excel Desktop
py tools/run_checks.py all             # both, still excludes live Codex
$env:PQPC_LIVE_CODEX = "1"; py tools/run_checks.py codex
```

`--quiet` changes printing only. Selection, pass criteria and the final
`gate=... run=... failed=... elapsed=...` line are identical either way.

To see where gate time goes before optimising anything:

```powershell
py tools/check_timings.py fast --top 25            # slowest tests and modules
py tools/check_timings.py fast --by area
```

## Where a test belongs

| Directory | What it owns | Runs in |
|---|---|---|
| `unit/` | One module or function, no server, no Excel, no subprocess unless the unit is a subprocess boundary | `fast` |
| `contracts/` | Pinned wire formats, hashes, schema shapes, error codes, compatibility facades, import/toolchain rules | `fast` |
| `integration/` | Real HTTP server, real temp workbooks, several modules wired together | `fast` |
| `journeys/` | A user-visible path end to end (for example the whole problem-chain HTTP journey) | `fast` |
| `taskpane/` | Node scripts that load the real `excel_addin` JavaScript | `fast` |
| `runtime/` | Anything needing Excel Desktop or the .NET bridge | `runtime` |
| `live/` | Opt-in live harness; never part of either gate | none |
| `support/` | Shared fixtures, oracles and builders. Not a test area; nothing here is discovered | n/a |
| `fixtures/` | Committed synthetic inputs | n/a |

Rules that keep the suite readable:

- A module in `unit/` must not need what `integration/` needs. If it starts a
  server or writes a real `.xlsx`, it belongs in `integration/`.
- Two areas may test the same subject; their module names may not collide.
  Prefix with the area when the plain name would be ambiguous
  (`test_problem_chain_unit.py` in `unit/`, `test_problem_chain.py` in
  `journeys/`).
- No `.py` file in a test area may be named `test_*.py` unless it holds tests.
  Helpers live in `support/`.
- `tests/live/` is importable like every other area, but its modules are not
  named `test_*`, so discovery leaves them alone.

## The registry is a contract

`tests/required_cases.json` pins **1,240 fully-qualified case IDs**. The gate
fails if any id disappears, because deleting a test must never look like a
green run.

- Adding a test: it is discovered automatically; add its id to the registry only
  when it is required behaviour.
- Renaming or moving a test module: rewrite every affected id in the registry in
  the same change. The raw file is a plain JSON array, so a text replacement of
  the dotted prefix is the safe edit; re-serialising the whole file is not.
- Deleting a test: replace it with a case that still proves the behaviour, then
  update the registry.

## Debugging a failure

1. `py -m unittest <dotted.id> -v` — one case, full traceback.
2. `py tools/check_timings.py fast --top 5` — confirm it is not a slow-test
   timeout masquerading as a failure.
3. A failure only in a full run usually means shared state: a temp directory, a
   port, or a monkeypatch that was not restored. Every suite closes its server
   and temp workspace in `tearDown`.
