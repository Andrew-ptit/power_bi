# Data Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nhập folder, làm sạch có hỏi/rà soát và undo/redo trong phiên; chưa làm KPI/domain business.
**Architecture:** Preparation store thuần trong sources; coordinator sở hữu transport auth, recovery lifecycle/slots/temp; Excel IO và UI tách controller nhỏ. Server-owned bounded journal không hồi sinh approval khi pane reopen. Reuse parser/export và synthetic harness, không biến Typed/Advanced thành patcher.
**Tech Stack:** Python 3.13 stdlib, JavaScript/Office.js, helper PowerShell hiện có, unittest và Node taskpane scripts. Không dependency runtime mới.
**Spec:** [spec.md](spec.md), [thiết kế](../../docs/superpowers/specs/2026-11-13-supply-chain-assistant-design.md).
**Date:** 2026-11-14. **Branch:** main, không checkout/stash công việc hiện có. **Plan owner:** feature này, không tạo bản sao cạnh tranh ở docs/superpowers/plans.

## Global Constraints

- TTL 1.800/28.800 giây; independent fail-fast Codex/Excel slots, locks, exact hashes/CAS/source/approval.
- File nguồn và sheet cá nhân read-only; chỉ imported-sheet ownership trong phiên cho clean tại chỗ.
- Không Save, cloud hoặc AI cho preparation; không log raw cells, binaries hay private paths.
- Backup verified trước ghi; full affected-scope read-back; partial/unknown không auto retry.
- Giữ Typed 15-operation/10-expression catalog, cancelled-null fields, Advanced exception/deferral, compatibility facades/schema aliases.
- Giữ baseline 001 và release metadata; chủ sở hữu hợp đồng/current status không chuyển sang feature docs.

## Review Focus

1. Cross-sheet/defined-name/Table collisions: preserve meaning, không chỉ formula text — T002/T007.
2. Reopen/unsaved books/clone marker: không cấp nhầm imported ownership hay restore authority — T004/T010.
3. CSV formula injection, locale và mã 0 đầu — T006/T008.
4. Quota/expiry giữa write/restore, cursor chỉ commit sau read-back — T003/T009.
5. Personal copy giữ nguyên nguồn, manual edits trước Apply/Undo gây conflict — T005/T009/T010.

## Technical Context

Target Windows Excel Desktop; native import yêu cầu ExcelApi 1.13 được kiểm runtime, không sửa manifest để giả support. Office export lấy workbook compressed, nhưng chưa có whole-workbook in-place restore đã được chứng minh. Vì vậy native preservation/recovery là feasibility gate trước implementation ghi. Phạm vi Office supported-feature matrix quyết định bật/tắt; không hứa mọi XLSX.

Storage: marked temp, RAM metadata nhỏ; không DB. Parser caps hiện có 64 MiB/file, 128 MiB/ingest session giữ nguyên; quotas journal riêng trong contract. Không đặt latency SLA chưa đo.

## Constitution Check

Pre/post-design PASS ở mức tài liệu: đúng canonical module, explicit target, local bounded data, frozen Typed/Advanced, synthetic/live separation. Ngoại lệ user-approved là preparation imported-sheet clean in-place; T001 cập nhật owner docs trước code. Live capability còn Not run, T002 không được bỏ qua. Không cần thay constitution.

## Project Structure

| Planned path | Responsibility |
| --- | --- |
| `pbip_assistant/sources/preparation/{model,inventory,cleaning,store,journal}.py` | Models, bounded inventory, pure cleaning, workflow and restore authority |
| `pbip_assistant/coordinator/endpoints/preparation.py` | Guarded HTTP transport, no authority |
| `pbip_assistant/coordinator/{runtime,server}.py` | Session vs recovery lifetime, slots/temp and composition |
| `pbip_assistant/excel_addin/preparation_runtime.js` | Native Excel import/copy/write/read-back/restore adapter |
| `pbip_assistant/excel_addin/preparation_controller.js` | Question navigation, reviewed state, toolbar |
| `pbip_assistant/excel_addin/taskpane.{html,css,js}` | Asset wiring, responsive/accessibility integration |
| `tests/support/preparation.py` | Independent fixtures/oracles, failure injection |
| `tests/{unit,contracts,integration,taskpane,live}/…preparation…` | Scoped tests and isolated runtime evidence |

Public signatures, fields and bounds: [contracts/preparation.md](contracts/preparation.md). Lifecycle entities: [data-model.md](data-model.md). Decisions and alternatives: [research.md](research.md).

## Implementation Batches

Each task: RED behavioral test → run and observe intended failure → minimal implementation → focused GREEN plus success/recovery → scope-only commit. Reuse unchanged test evidence across IDs only when scope covers every criterion. Exact checkbox task list in [tasks.md](tasks.md).

### A. Contracts and host feasibility — T001–T002

Reconcile canonical source/write boundaries and baseline overlap before enabling new paths. Build synthetic preservation fixture covering cross-sheet formula, collisions/names, styles, dates, tables, external links and protected structures. Use existing isolated harness to prove native import, personal copy and affected-scope restore, not just export.

**Gate:** if preservation/recovery cannot be proved for baseline supported structures, mark writes Blocked. Continue pure inventory/wizard independently; do not downgrade or silently switch to broad COM attachment. A changed technical architecture requires design review. Plan is actionable, but write implementation depends on runtime evidence still Not run.

### B. Journal and safe reattachment — T003–T004

Server journal owns bounded verified before/after snapshots and immutable receipts. Separate logical preparation session from disposable transport sessions. Preserve `/api/session/close` retirement and clearing of existing stores; add an isolated recovery owner that may retain committed journal only until original TTL, never old approval/caches.

Reopen bootstraps fresh authenticated transport, verifies marker + source/target semantic fingerprints, then explicitly reattaches/forks before restoring. Marker/path/name alone insufficient; ambiguous clone cannot gain in-place ownership automatically. A preparation-only detach retires transport while retaining committed journal; explicit close still clears attached recovery. Persist committed recovery eagerly, not during pagehide. Live feasibility must prove unsaved-book reopening behavior.

### C. Inventory and import — T005–T007

Immediate sorted CSV/XLSX folder inventory, bounded read/hash/stale checks, root/path guards, metadata mapping review. Keep legacy CSV append connector unchanged. CSV literal import; XLSX dependency-complete native group insertion, no free-form OOXML formula rewriting. Commit imported sheet IDs/ownership only after read-back. Partial attempts retain precise receipts and prevent replay.

### D. Scan and wizard — T008

Deterministic whitespace/number/date findings; unknown format asks questions. Metadata/questions/source selection local, no Codex required. Group Source→Formats→Exceptions→Review; omit irrelevant groups. One question visible; answer index and Back/Next distinct from ↶/↷. CAS answer revision invalidates downstream preview/approval; keep independent answers.

### E. Apply and restore — T009–T010

Apply exact approved diff after verified backup and source recheck. Import-owned targets in place; existing personal sheets native-copy to unique result. Copy formulas keep native dependency behavior; disclose references back to source, do not retarget guessed text. Verify original source unchanged and full affected region. Undo/Redo checks fingerprint and fresh approval, restores in place when sheet identity matters; no delete/reinsert shortcut without semantic proof. Cursor changes only after read-back. New edit after Undo clears Redo.

### F. Qualification — T011–T012

Reconcile baseline 001 US2 write verification and US8 clarification without duplicate frameworks/tests. Run focused journeys, all existing taskpane gates, fast/runtime/full regression and applicable isolated live success/recovery. No live Codex required for this local feature; Advanced remains Deferred. Evidence in [acceptance.md](acceptance.md); no release bump from plan generation.

## Execution Handoff

Exact commands in [quickstart.md](quickstart.md). All runtime acceptance starts Not run. Recommend native execution in one session because journal/session/IO interfaces are tightly coupled; choose execution method after reviewing plan. Use isolation workflow before implementation; never reset/stash or include unrelated dirty changes. This plan does not implement or verify any production capability.
