# Implementation Plan: Baseline tin cậy nghiệp vụ và xác minh ghi Excel

**Feature context**: `001-business-assurance-baseline`  
**Git branch thực tế**: `main`, giữ nguyên workspace đang có thay đổi.  
**Date**: 2026-11-05 (Asia/Saigon)  
**Spec**: [spec.md](spec.md)  
**Status**: Plan để review/thi công; không phải triển khai hoặc nghiệm thu.

## Summary

Thực hiện B01–B09 theo hành trình người dùng. Trước ghi, người dùng giải quyết câu hỏi trọng yếu và duyệt policy đúng revision. Sau ghi, mức xác minh phải dựa trên full read-back có giới hạn; lỗi mơ hồ được giữ lại và chỉ kiểm lại bằng đọc. Không thay đổi ngữ nghĩa merge, không nới catalog, không sửa dữ liệu nguồn ngoài ngoại lệ Advanced M hiện hành.

Dùng owner/session/lock hiện có; bổ sung pure contract helpers và một owner attempt nhỏ cho Advanced M đang thiếu lifecycle đó. Spec/Record Assistant mới cùng tồn tại với v2, không chèn field vào hash cũ. Giữ approval binding hiện tại vì fingerprint mới bind review. Không thêm DB, dependency Python hoặc plugin runtime.

## Technical Context

- **Language/Version**: Python 3.13 (application standard library), JavaScript/Office.js, Windows PowerShell 5.1-compatible helpers. .NET 8 TMDL bridge không bị ảnh hưởng.
- **Primary Dependencies**: Office.js, Codex subprocess adapter và Excel isolated runner hiện có. Không cài thêm dependency. Spec Kit chỉ là developer tooling.
- **Storage**: session-memory trong owner stores; Custom XML giữ phạm vi hiện hành; không lưu expected raw result/attempt/runtimeSummary vào history hoặc localStorage.
- **Testing**: unittest; 12 taskpane JS scripts qua `tests/taskpane/test_taskpane_js.py`; synthetic live Excel harness; opt-in real Codex và M parity là evidence độc lập.
- **Target Platform**: Excel desktop Windows, local taskpane/coordinator. Không cam kết coauthoring/multi-window atomic workbook writes.
- **Project Type**: Excel add-in + local HTTP application + typed compiler/executor.
- **Performance Goals**: chunk ≤10.000 ô và ≤1 MiB JSON/request; không tải unbounded hoặc hiện % giả. Đo elapsed, peak memory và bytes trên fixture biên; chưa đặt SLA chưa có benchmark.
- **Constraints**: TTL 30 phút idle/8 giờ tuyệt đối, slot Codex/Excel fail-fast, approval một lần, CAS, exact HEAD/source binding, Text Decimal và privacy giữ nguyên.
- **Scale/Scope**: 9 stories, 27 scenario aliases; Assistant 20 steps/200 planning columns/256 output columns/400.000 write cells; Typed 50 steps. PQ result/diagnostic caps giữ nguyên; full verify không nâng product caps.

## Constitution Check

| Gate | Trước research | Sau design | Cách đáp ứng |
|---|---|---|---|
| Contract/ID ownership | PASS | PASS | Local B/S/US/T aliases; canonical FR/AC giữ owner; đồng bộ docs trước rollout |
| Source/exact approval | PASS | PASS | Exact reviewed policy/hash; no automatic retry; Advanced source consent riêng |
| Bounded privacy/runtime | PASS | PASS | Chunked read-back local; no raw log/history |
| Catalog/cancelled scope | PASS | PASS | Missing keys dùng operation hiện có; required-null history giữ nguyên |
| Verification/release truth | PASS | PASS | Product gates Not run; Advanced live Deferred; không đổi release metadata |

Đây là pass thiết kế, không phải runtime. Không có exception kiến trúc ngầm được phê duyệt. Schema artifact mới phải có canonical contract được review ở T002 trước khi sửa implementation.

## Project Structure

### Documentation của feature

```text
specs/001-business-assurance-baseline/
  spec.md
  plan.md
  research.md
  data-model.md
  contracts/business-review.md
  contracts/write-verification.md
  quickstart.md
  tasks.md
  acceptance-matrix.md
```

### Source boundaries dự kiến khi thi công

| Owner | Existing paths | Planned additions (chưa tạo source code) |
|---|---|---|
| Pure contracts | `pbip_assistant/core/` | `core/write_verification.py`, pure normalization/comparison |
| Assistant authority | `sources/assistant_session.py`, `assistant_approval.py`, `assistant_reconcile_v2.py` | `sources/assistant_review.py`, `assistant_freeze_v3.py`, `assistant_record_v3.py` |
| Planner boundary | `adapters/codex/{assistant_plan,typed,problem_chain}.py` | Không thêm planner framework |
| Typed/history | `powerquery/typed/store.py`, `powerquery/history/{store,document}.py` | Không thêm persisted history fields |
| Join policy | `powerquery/typed/{model,validation,compiler}.py` | `powerquery/typed/join_policy.py`, pure explicit plan transformation |
| Advanced state | `powerquery/advanced/runtime.py` | `powerquery/advanced/attempts.py`, session-local owner |
| HTTP | `coordinator/server.py`, `coordinator/endpoints/` | `coordinator/endpoints/business_assurance.py`, thin routes |
| Office/UI | `excel_addin/{taskpane.js,taskpane.html,assistant_custom_xml.js}` | `excel_addin/write_verification.js`, bounded reader |
| Verification | `tests/{unit,contracts,integration,taskpane,runtime,live,support}` | Exact paths trong tasks.md |

**Structure Decision**: không chuyển lock/state ra HTTP/helper; không sửa flat facades để triển khai behavior mới. Resource lookup mới dùng `core.resources`.

## Phase 0 — Research

Hoàn thành [research.md](research.md) từ code/doc và research agent chỉ đọc. Các lựa chọn kỹ thuật là lựa chọn thiết kế, không giả là quyết định cũ của người dùng. Không còn unknown kỹ thuật bắt buộc; scope defer được ghi rõ.

## Phase 1 — Design và contracts

### A. Review nghiệp vụ — US1/US4

BusinessReview bind compute snapshot, source profile/question set, plan/branch, câu trả lời resolved và policy có đơn vị/rationale. AI chỉ đề xuất. A/B có thể tính exploratory nhưng chưa mang nhãn passed theo policy user đã duyệt. Thay review phải recompute reconciliation; execution cache không cấp authority.

maxFanOut=1 chỉ là đề xuất thận trọng, không là consent. Không gán 0,01 cho mọi measure. R2 không áp dụng thì dùng missing-control acknowledgement riêng và unverified, không tolerance giả.

Critical categories: KPI basis, currency/unit, period, join/key, duplicate và missing values. Unknown planner question default blocking. Advisory có lý do và không được hạ deterministic critical category. Tái đo full source; thay tập vấn đề vô hiệu review dù schema giữ nguyên.

### B. Artifact compatibility

Assistant Spec/Decisions/Record 3.0 có review đóng và hash. V2 validators/read/display/export giữ nguyên; không sửa bytes/hash hay upgrade bằng default. New fingerprint bind decisionsHash→reviewHash cùng source/plan/preview/reconcile/result. Approval vẫn `{specFingerprint, previewHash}`, thêm binder v3 chứ không nới v1/v2 checks.

Khi rollout protocol mới, live freeze/approve/apply yêu cầu reviewed-v3 authority. Legacy/unreviewed request bị chặn bằng current error envelope với remedy review lại, không fallback viết bằng v2. Đây là siết precondition ghi có chủ đích; historical đọc vẫn tương thích. Test client/server mismatch; không terminate coordinator cũ. Phiên coordinator cũ không được xem là đã có baseline.

Typed history schema/hash không đổi. Join policy được biểu đạt bằng semantic steps/prompt/description trong revision mới qua CAS. Runtime review/attempt evidence không đi vào runtimeSummary, annotations hoặc sampleStore.

### C. Missing-key policy — US5

Keep-unmatched thêm fresh helper columns: missing bên trái=`left-missing`, bên phải=`right-missing`, đủ khóa=`present`. Merge trên nguyên khóa gốc cộng helper pair; remove helpers ở output cuối. Dùng typed if/compare/boolean/literal hiện có, không row index/raw M. Missing predicate theo kiểu, composite và null-safe.

Exclude dùng filter có counts; alternative key cần đúng cột được xác nhận; missing-group giữ semantics hiện có sau consent. Transformation là new visible plan/revision. Helpers tính vào step/column/M-length caps; quá cap fail closed. Metrics theo khóa chỉ chiếu counts/hashes/column refs, không đưa raw groups tới Codex/history.

### D. Write verification và recovery — US2/US3

Chuẩn `excel-values-v1`: Text Decimal chính xác, literal text, boolean, numeric PQ binary64 và null/empty theo transport. Expected PQ từ validated full package, không từ display sample. Chunk reader đọc đủ approved rectangle, actual marker khi có, no-formula và old-tail scope. All-null tail rows dùng explicit logical rectangle; không suy số hàng từ usedRange.

Evidence budget thiết kế: tối đa 5 outstanding attempts/64 MiB canonical encoded expected data mỗi session owner, reuse references thay vì nhân cache. Quá budget chặn trước mutation. Một active observation/attempt, mỗi chunk ≤1 MiB và ≤10.000 ô. Không nâng existing HTTP/product caps; chunk nhỏ hơn nếu current body cap thấp hơn.

Unknown latch đặt trước dispatch mutation; chỉ proof trước dispatch mới nói chưa ghi. Server checks chunk coverage/content/binding, không nhận boolean verified như evidence đủ. Recovery chỉ observation, không completion replay, không restore approval/cache/Record success. Historical receipt và current target state hiển thị riêng.

Advanced preview import cũng là write attempt; source Apply vẫn consent riêng và không reuse Typed approval. Owner mới đóng theo session. Recovery không runner/M/Save/XML write.

### E. Eligibility, checkout, presentation — US6–US9

Giữ caps và ghi scope/header rõ. Preflight trước tính khi biết, sau compute kiểm actual result eligibility trước freeze/approval. Không giả join output row count. Apply vẫn recheck.

Quay về consent cả HEAD và sheet bị thay. Đích đổi sau consent hoặc stale cache thì Preview mới; không ngầm restore. Giữ/xóa descendants riêng. View zero write. Năm trục trust độc lập; user Save chưa quan sát là unknown. Không scheduler/import JSON/auto-switch mode.

## Delivery Sequence

### Execution adjustment — 2026-11-10 (Asia/Saigon)

**Yêu cầu đã chọn**: giữ đủ baseline và T001–T060; gom việc liên quan thành cụm, test theo phạm vi, dùng chung fixture/oracle, review tại ranh giới và kiểm tra khả năng chạy live sớm. Đây là điều chỉnh cách thi công, không đổi product design, contracts, storage, dependencies hoặc tiêu chí nghiệm thu. Cập nhật tại chỗ bằng workflow Spec Kit plan/tasks; không sinh feature/plan cạnh tranh, không sửa các bản skill/template cài đặt.

**Các hướng đã cân nhắc**: tiếp tục một vòng điều hành/review cho từng checklist line tạo chi phí lặp; chia nhiều agent lúc này dễ tranh các owner/UI files; thu nhỏ MVP thay đổi mốc bàn giao. Người dùng chọn gom cụm và giữ nguyên phạm vi. Thực hiện inline theo dependencies; `[P]` không tự cấp phép spawn agents hoặc chạy Excel slots song song.

**Đơn vị thực thi** là cụm trong bảng ở [tasks.md](tasks.md#execution-batches). **Đơn vị truy vết** vẫn là từng T-ID và S01–S27. Một cụm có thể cần nhiều vòng test-first nhỏ; không viết toàn bộ code rồi mới kiểm thử. Cụm lớn được triển khai dần trong cùng context, không tạo thêm task IDs hoặc lặp lại thiết kế đã chốt.

Trước khi tiếp tục, đối chiếu source và evidence hiện hành để tìm task thật sự còn thiếu. Checkbox chưa checked không đồng nghĩa chưa có code; code tồn tại không đồng nghĩa đã pass. Chỉ đóng task khi toàn bộ tiêu chí của task có đúng lớp evidence. Ghi trạng thái thiếu bằng chứng, điểm tiếp tục và blockers vào phần execution checkpoint của acceptance-matrix.md khi thực thi; không thay CURRENT_STATUS.md bằng kết quả giả định.

**Test/review cadence**: contract checkpoint T002/T006 trước behavior implementation; focused regression/oracle trước và trong sửa code; affected success/recovery journey khi tích hợp cụm; review diff và contract/task/scenario coverage tại ranh giới cụm. Chỉ mở lại contract review nếu contract, authority hoặc compatibility đổi. Không dừng xin xác nhận sau từng checkbox khi đã được phép thực thi; material ambiguity/blocking concern vẫn theo AGENTS.md. T060 giữ rà độc lập cuối baseline.

**Chọn kiểm tra**: isolated helper dùng unit/contract tương ứng; owner/protocol dùng integration/state/replay; actual UI handler dùng retained taskpane scripts; nối nhiều owner/UI layers cần full regression và affected live journeys. Qualification giữ fast/full/runtime/real Codex/Office.js theo phạm vi. Không chạy full suite sau mọi chỉnh sửa nhỏ. Không xem focused hoặc fake Office pass là live evidence.

**Tái sử dụng**: hand-written expected trong tests/support/assurance_fixtures.py dùng chung cho unit/HTTP/fake host khi phù hợp; không dùng executor/compiler/actual output tạo oracle. Giữ các case khác authority, transport hoặc recovery layer. Một run có thể map nhiều T/S IDs nếu đủ scope; chỉ tái dùng khi relevant code/dependencies/fixtures/config/environment không đổi và provenance còn đối chiếu được. Changed code cần kiểm tra lại phần bị ảnh hưởng; release vẫn cần exact-current gates. Không xóa retained cases nếu thiếu behavioral replacement.

**Live readiness sớm**: đầu C00 kiểm Python/Node, harness/certs và khả năng dùng Excel/Office.js, Codex CLI/auth theo quickstart. Actual smoke chỉ dùng disposable marked synthetic fixture và đúng quyền/opt-in; không workbook người dùng, không dừng coordinator hay thay production catalog. Known blockers trong CURRENT_STATUS.md chỉ là lịch sử cho đến khi kiểm lại. Readiness không đóng T055/T057 hoặc chứng minh feature mới. Gate không sẵn sàng được ghi Blocked/Not run; tiếp tục phần độc lập và không thử lại cùng blocker liên tục nếu chưa có thay đổi liên quan. Advanced actual live vẫn Deferred.

**Phạm vi lượt điều chỉnh này**: chỉ sửa AGENTS.md, plan.md, tasks.md, quickstart.md và cung cấp prompts trong quickstart; không chạy product gates, sửa implementation, check task hoàn thành, commit/merge hoặc bump version. Spec, research, data model, contracts và acceptance evidence giữ nguyên vì không có product delta.

1. Setup/contracts/fixtures; canonical contract checkpoint trước implementation.
2. US1: review MVP nội bộ; chưa đủ release.
3. US2→US3: full verify rồi unknown/recovery, gồm Typed restore và Advanced automated paths.
4. US4→US5: mandatory Q&A rồi missing-key decisions, tích hợp review/full-source checks.
5. US6→US7→US8→US9: eligibility, checkout consent, reuse scope và labels.
6. Full regression + parity/live evidence + docs consistency. B01–B05 là safety increment bắt buộc; full baseline cần B01–B09. Advanced live Deferred làm qualification toàn bộ ba luồng chưa Complete.

## Verification Strategy

[quickstart.md](quickstart.md) và [acceptance-matrix.md](acceptance-matrix.md) định nghĩa command/oracle. Spec yêu cầu test tường minh theo “tiêu chí pass”. Mỗi task có pass riêng; không dùng số test xanh thay coverage.

Giữ 12 taskpane scripts/required-case guard, prior history/source fingerprints; real Codex riêng deterministic live Excel. Cross-cutting future implementation cần fast, full discovery, runtime và affected Office.js journeys; planner thay đổi cần real Codex opt-in. Chỉ lập docs lượt này: product gates Not run, Advanced live Deferred, no version bump.

## Complexity Tracking

Không có constitution violation được chấp thuận. Coexisting Assistant v3 bảo vệ hash cũ; Advanced attempt owner tránh state trong HTTP. Đã loại DB/history migration, raw-M shortcut và thử ghi lại để “xác minh”.
