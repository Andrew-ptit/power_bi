# Local Data Copilot ? Excel v? Power BI Project

Tr? l? local cho CSV/XLSX/PBIP v? Excel task pane. Code ?ang ???c t?i c?u tr?c cho release **1.2.0**; tr?ng th?i ph?t h?nh v? b?ng ch?ng ki?m ch?ng n?m trong [h? s? release](docs/releases/1.2.0.md). Kh?ng xem k?t qu? gi? l?p/static l? b?ng ch?ng Excel ho?c Power BI Desktop runtime.

## Ch?y ?ng d?ng

Python 3.13; product Python ch? d?ng standard library. Node d?ng cho JS test. Excel runtime c?n Windows/Excel Desktop; TMDL c?n .NET 8 v? bridge ?? build.

```powershell
py -m pbip_assistant --pbip .\tests\fixtures\pbip\Retail --excel .\tests\fixtures\source\orders_synthetic.xlsx --csv .\tests\fixtures\source\orders_synthetic.csv
py -m pbip_assistant.webapp --port 8765 --open
py -m pbip_assistant.excel_addin_server
```

Web UI ch? x? l? ngu?n local, kh?ng c? AI/PBIP/apply. Task pane c? nh?nh Codex g?i prompt v? m?u workbook gi?i h?n sau thao t?c Analyze; kh?ng g?i to?n workbook ho?c ???ng d?n local. [Runbook task pane](tools/excel_addin/README.md) m? t? HTTPS/catalog.

```powershell
dotnet restore .\tools\tmdl_bridge\TmdlBridge.csproj --locked-mode
dotnet build .\tools\tmdl_bridge\TmdlBridge.csproj -c Release --no-restore
```

Restore ch? l? b??c setup. Bridge runtime ch?y offline; kh?ng xo? binary ?ang d?ng ?? ch? l?m s?ch th? m?c.

## Ki?m ch?ng

```powershell
py tools/run_checks.py fast
py tools/run_checks.py runtime
$env:PQPC_LIVE_CODEX = "1"
py tools/run_checks.py codex
Remove-Item Env:PQPC_LIVE_CODEX
py -m unittest discover -s tests -v
```

`fast` g?m unit/contracts/HTTP/Office.js gi? l?p v? 12 script JS; `runtime` ch?y Excel/.NET tu?n t?. L?nh discovery ??y ?? v?n g?m c?c test runtime, c?n live Codex c?n opt-in. Sideload Office.js th?t l? c?ng ri?ng v? ph?i ???c ghi b?ng ch?ng.

## C?u tr?c v? h?p ??ng

- [Ki?n tr?c v? nguy?n t?c refactor](docs/current/ARCHITECTURE.md).
- [Danh m?c t?i li?u hi?n h?nh](docs/current/README.md); ID y?u c?u v? h?p ??ng h?nh vi ???c gi? khi chuy?n t?i li?u.
- [B?ng ch?ng v? ?nh x? test](docs/evidence/README.md); l?ch s? c? kh?ng ch?ng minh revision m?i ?? pass.
- `pbip_assistant/` chia theo core, sources, powerbi, coordinator, excel, powerquery v? adapters. C?c ???ng import/module CLI c? v?n t??ng th?ch.
- `tests/` chia theo support, fixtures, unit, contracts, integration, journeys, taskpane v? runtime; d? li?u fixture nh? v? t?ng h?p.

Ngu?n Excel/PBIP m?c ??nh ch? ??c. Ri?ng Advanced M c? Preview r?i Apply values-only v?o ??ng Table/usedRange ?? duy?t; kh?ng Save ho?c h?a rollback. Typed history d?ng Custom XML/CAS; AI kh?ng c?p approval. Name/note editing, semantic/runtime diff v? persisted runtime summary ?? b? lo?i kh?i roadmap.

Baseline kh?i ph?c c? fixture byte-exact: tag `baseline/pre-1.2.0-byte-exact` t?i commit `4bdc2de`; m?c code ??u ti?n l? `baseline/pre-1.2.0` (`d9b6038`). Kh?ng c? push t? ??ng. Workbook/CSV/?nh c? nh?n v? certificate kh?ng thu?c baseline ngu?n v? kh?ng n?m trong danh s?ch d?n xo?.
