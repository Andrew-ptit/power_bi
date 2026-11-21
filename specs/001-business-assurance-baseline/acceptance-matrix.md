# Acceptance matrix — Baseline tin cậy nghiệp vụ

**Date**: 2026-11-05. **Status**: chưa triển khai/kiểm thử sản phẩm baseline.  
B/US/S/T là alias cục bộ, không cấp canonical FR/AC/BPMN IDs. Task ranges tham chiếu tasks.md; qualify bằng T054–T060. Source baseline là 9 mục người dùng đính kèm; không thay canonical current contracts chỉ bằng việc lập bảng này.

## Scenario → task → oracle/evidence

Mọi row hiện **Not run**. Cột Layer là evidence phải thu trong implementation; các phần Advanced M actual live luôn **Deferred**, dù automated/shared writer cases về sau có thể pass.

| Scenario | Story | Baseline | Oracle/tiêu chí pass | Tasks | Test/evidence targets (planned tests ghi trong tasks.md) | Layer cần có |
|---|---|---|---|---|---|---|
| S01 | US1 | B01 | 100→200, policy chưa duyệt: exploratory không freeze/pass | T008–T013 | tests/unit/test_assistant_review.py; tests/integration/test_business_assurance.py; tests/taskpane/taskpane_assistant_flow.js | Unit + HTTP + fake Office; real Codex/Office.js khi tích hợp |
| S02 | US1 | B01 | Sửa tolerance/unit/rationale/source/answer làm review stale | T008–T013 | tests/unit/test_assistant_review.py; tests/integration/test_business_assurance.py | Unit + HTTP + real Office.js freshness |
| S03 | US1 | B01 | Missing R2 cần ack/unverified; hard fail không override | T008–T013 | tests/unit/test_assistant_review.py; tests/taskpane/taskpane_assistant_flow.js | Unit + handler + Office.js |
| S04 | US2 | B02 | Full range/type/identity/marker/structural matches, không giả dimensions | T014–T020 | tests/unit/test_write_verification.py; tests/taskpane/taskpane_pq_write.js; tests/taskpane/taskpane_pq_source_apply.js | Unit + HTTP + actual Office.js; Advanced live Deferred |
| S05 | US2 | B02 | Row25, Assistant col201/PQ col200, formula/marker/tail sai: mismatch, no cache/Record promotion; PQ201 bị cap block | T014–T020 | tests/taskpane/taskpane_assistant_flow.js; tests/taskpane/taskpane_pq_write.js; tests/taskpane/taskpane_pq_source_apply.js; tests/integration/test_write_verification_journey.py | Fake faults + actual Office.js; Advanced live Deferred |
| S06 | US2 | B02 | Null tails/Decimal digits/literal =/dates/booleans đúng transport | T014–T020 | tests/unit/test_write_verification.py; tests/taskpane/taskpane_assistant_flow.js; tests/runtime/test_typed_local_parity.py | Unit + runtime M + Office.js |
| S07 | US3 | B03 | Dispatch boundaries: chỉ proof pre-dispatch mới nói chưa ghi | T021–T027 | tests/integration/test_write_verification_journey.py; tests/taskpane/taskpane_advanced_policy_crosscheck.js | HTTP + fake Office faults + actual Office.js; Advanced live Deferred |
| S08 | US3 | B03 | Read-only recovery matches/mismatch/incomplete/insufficient; zero mutation | T021–T027 | tests/integration/test_write_verification_journey.py; tests/taskpane/taskpane_assistant_flow.js; tests/taskpane/taskpane_pq_typed.js | HTTP + fake Office + actual Office.js |
| S09 | US3 | B03 | TTL/reopen/missing expected/wrong workbook → insufficient, no rerun | T021–T027 | tests/integration/test_write_verification_journey.py; tests/taskpane/taskpane_assistant_custom_xml.js | HTTP + fake host + actual reopen |
| S10 | US4 | B04 | Gross/net unresolved/Chưa rõ chặn freeze, không chặn exploratory | T028–T032 | tests/unit/test_assistant_review.py; tests/taskpane/taskpane_assistant_flow.js | Unit + HTTP + real Codex/Office.js |
| S11 | US4 | B04 | Full source issue đổi cùng schema làm question/review stale | T028–T032 | tests/integration/test_business_assurance.py; tests/taskpane/taskpane_assistant_flow.js | HTTP + actual Office.js source read |
| S12 | US4 | B04 | Advisory không chặn; critical không AI downgrade; no candidate question-only | T028–T032 | tests/unit/test_assistant_review.py; tests/taskpane/taskpane_problem_chain.js | Unit + fake host + real Codex clarification |
| S13 | US5 | B05 | Missing-key explicit modes và 0/false/blank/composite behavior | T033–T038 | tests/unit/test_join_policy.py; tests/integration/test_business_assurance.py | Unit + HTTP + six-join M parity |
| S14 | US5 | B05 | Visible fresh helpers/revision; original keys/history preserved; cap fail | T033–T038 | tests/unit/test_join_policy.py; tests/taskpane/taskpane_pq_typed.js; tests/taskpane/taskpane_problem_chain.js | Unit + fake host + real Office.js CAS/HEAD |
| S15 | US5 | B05 | Per-key duplication bị che bởi total ratio vẫn hiện exact counts/max | T033–T038 | tests/unit/test_join_policy.py; tests/integration/test_business_assurance.py | Unit + HTTP; no raw keys projection |
| S16 | US6 | B06 | 2×60000 workbook rows block cumulative; file scope không bị đổi ngầm | T039–T042 | tests/integration/test_business_assurance.py; tests/taskpane/taskpane_assistant_flow.js | Unit/HTTP boundaries + host read |
| S17 | US6 | B06 | 400004 cells gồm header chặn trước freeze/approval; Apply recheck | T039–T042 | tests/integration/test_business_assurance.py; tests/integration/test_write_verification_journey.py | HTTP + handler + no-consume assertions |
| S18 | US6 | B06 | 512/200/256/75 columns,20/50 steps và samples/caps tách rõ | T039–T042 | tests/integration/test_business_assurance.py; tests/taskpane/taskpane_assistant_flow.js | Boundary + UI contract + doc review |
| S19 | US7 | B07 | Quay về dialog nêu đúng revision/sheet/write impact | T043–T046 | tests/taskpane/taskpane_problem_chain.js | Fake handler + actual cache-hit Office.js |
| S20 | US7 | B07 | Stale/miss/changed target chỉ Preview mới; View zero write | T043–T046 | tests/integration/test_write_verification_journey.py; tests/taskpane/taskpane_problem_chain.js | HTTP + actual cache hit/miss/recovery |
| S21 | US7 | B07 | Keep/delete explicit, CAS và surviving revision bytes giữ | T043–T046 | tests/taskpane/taskpane_problem_chain.js; tests/integration/test_write_verification_journey.py | HTTP + actual XML/head/reopen |
| S22 | US8 | B08 | Assistant reopen metadata-only, no import/re-run/approval promise | T047–T049 | tests/taskpane/taskpane_assistant_custom_xml.js | Fake XML + actual Office.js reopen |
| S23 | US8 | B08 | Typed nguồn kỳ mới cần fresh fingerprint/Preview/approval | T047–T049 | tests/taskpane/taskpane_problem_chain.js | Fake + actual source-change journey |
| S24 | US8 | B08 | Advanced values-only không query/connection/Refresh/scheduler | T047–T049 | tests/taskpane/taskpane_pq_source_apply.js; tools/excel_addin/README.md | Automated package/copy + doc review; Advanced live Deferred |
| S25 | US9 | B09 | Total pass không xóa date→null quality warning/parity none | T050–T053 | tests/taskpane/taskpane_assistant_flow.js; tests/integration/test_business_assurance.py | Unit + HTTP + UI + real Office.js labels |
| S26 | US9 | B09 | No Save call ≠ user chưa Save; unknown khi không quan sát | T050–T053 | tests/taskpane/taskpane_assistant_flow.js; tests/taskpane/taskpane_pq_typed.js | Fake Save state + actual user-Save observation boundary |
| S27 | US9 | B09 | Unsupported catalog không auto Advanced; giữ Text/parity/knownDifferences | T050–T053 | tests/integration/test_business_assurance.py; tests/taskpane/taskpane_advanced_policy.js | Contract + fake host + real Codex bounded refusal |

## Status theo lớp

| Layer | Current status | Điều kiện đóng |
|---|---|---|
| Document consistency | PASS — static validation 2026-11-05; không phải product pass | 9 B / 9 US / 27 S / 60 T; local links/fences/task format checked, all 60 unchecked |
| Unit/domain/schema/HTTP | Not run | Hand-written positive/negative oracles, no authority bypass, exact guards |
| 12 retained JS fake Office scripts | Not run | Actual handlers; write/Save/runner counts; không thay Office.js live |
| Runtime M parity | Not run cho baseline | Six join helper policies và transport cases; timeout/absence=Blocked/Not run |
| Real Codex | Not run cho baseline | Bounded synthetic prompts, schema preflight, plan/Q&A behavior; deterministic planner không thay real call |
| Assistant real Office.js | Not run cho baseline | Full reviewed journey, unknown recovery, Record/reopen, source preservation |
| Typed real Office.js | Not run cho baseline | HEAD/staging/Confirm/cache/checkout/recovery/reopen và prior history preservation |
| Advanced actual live | Deferred | Chỉ mở khi có chỉ dẫn mới; không chạy mặc định, không đóng bằng Typed/shared writer evidence |
| Full-three-mode release | Incomplete / not qualified | All in-scope external gates có exact-current evidence; Advanced defer là giới hạn phải nêu |

## Traceability theo baseline và audit

| Baseline | Audit | Story | Deliverable rõ nhất |
|---|---|---|---|
| B01 | P1 | US1 | Exact user-reviewed threshold/unit/rationale; transitive approval binding |
| B02 | P2 | US2 | Full vs sample transport verification across writer scopes |
| B03 | P3 + P8 | US3 | Mutation latch, unknown warning, bounded read-only observation |
| B04 | P4 | US4 | Mandatory semantic definitions + full-source issue invalidation |
| B05 | P5 | US5 | Explicit missing-key policy + per-key metrics + visible catalog helpers |
| B06 | P6 | US6 | Scoped limits/header và actual write eligibility trước duyệt |
| B07 | P7 | US7 | Destination-aware cache restore consent, View zero write |
| B08 | P9 | US8 | Audit/pipeline/values-only reuse boundary; recurrence backlog |
| B09 | P10 + giả thuyết 2/3/6/10 | US9 | Five independent trust axes; current status/capability honesty |

## Evidence record template

- Revision/working-tree snapshot, run ID và exact command.
- Layer và scenario aliases; status Pass/Fail/Skip/Blocked/Not run/Deferred.
- Elapsed time, peak memory, max canonical/chunk bytes; dimensions.
- Error codes và expected/actual state transitions, consumed authority và completion idempotency counts.
- Revision/HEAD/step changes, source before/after fingerprints và surviving history hashes.
- Write/Save/runner/approval/cache promotion counts; recovery bắt buộc zero mutations.
- No raw cells/key groups/prompt, credentials, private paths hoặc workbook binaries trong report. Synthetic artifacts trong ignored .artifacts, không committed.
- Reviewer đối chiếu oracle với business example, không chỉ compiler/executor output.

## Pass/fail rules

Product tasks không checked vì tài liệu được tạo. Full matched không được xuất phát từ sample-only/expected-as-observed/boolean-only receipt. Bất cứ wrong target, stale review, unresolved mandatory question, deterministic blocker, missing coverage hoặc hidden retry đều fail story.

Recovery matches chỉ nói nội dung hiện tại khớp expected còn đáng tin; không tự tạo historical applied state, Record hoặc cache. Nếu old receipt thành công nhưng target đã đổi, hiển thị historical success và current mismatch riêng.

Safety MVP US1 không là release. Safety increment US1–US5 và full baseline US1–US9 có checkpoints riêng; Advanced live Deferred khiến không được tuyên bố qualification hoàn tất toàn bộ ba luồng. Không sửa version/release status để bù evidence thiếu.

## Execution checkpoint — 2026-11-10: vị trí implementation

- Implementation đang ở linked worktree `.artifacts/business-assurance-worktree`, branch `codex/business-assurance-baseline`, HEAD `efe9afef4d57d3ac81a0c264620a23bb3b8cc303` cùng thay đổi chưa commit. Bản tasks/code trong thư mục gốc `main` không phản ánh tiến độ worktree; không suy phải làm lại C00 từ checkbox ở đây.
- Worktree tasks và ledger `.superpowers/sdd/plan/progress.md` ghi **T001–T017 đã qua review**; C02 còn dở, **tiếp tục T018–T020**. T016 có 128/128 focused checks; đối chiếu lại 5 source/test hashes trong lượt resume vẫn khớp. Không chạy lại T001–T016 chỉ để đóng checkbox.
- Tiếp tục đọc acceptance-matrix.md và tasks.md **trong worktree trên**, đối chiếu code/snapshot/evidence rồi nối T018–T020; T017 đã đóng ở lớp client với giới hạn owner/routes ghi rõ. Giữ lịch C00–C11 ở Execution batches (đã đưa vào worktree); không tạo branch/worktree mới, reset/stash/commit/merge hay chép đè bản main.
- Final T017: 32/32 taskpane + HTTP tests pass trong **26.856s**; independent re-review **PASS / Approved** sau sửa hai lỗi unknown-write. Final fast: **1250 tests, 0 failures, 0 errors, 3 skips, 176.233s**. Source/test/runner snapshot **315b7d621f3b36100e5ce247d67e2193e116e48f7630ef395669ad4230b4daa3**; logs/review/manifest trong worktree `.superpowers/sdd/plan/`. Đây là client simulation + local HTTP/deterministic regression, không là live qualification.
- Real Codex chưa opt-in; Office.js live chưa chạy; runtime fixture-save blockers trước đó chưa được đóng. Advanced actual live **Deferred**. Baseline/release chưa Complete, không bump version.


## Continuation pointer ? 2026-11-11

Implementation continues in `.artifacts/business-assurance-worktree` on the existing `codex/business-assurance-baseline` branch, not this main tree. Last completed reviewed milestone is still T017; T018 now has partial internal full-proof owner integration and prepare-time expected admission, with scoped independent fixes reviewed. T018 remains unchecked; C02 and qualification are incomplete. Read the newest execution checkpoint in that worktree's `specs/001-business-assurance-baseline/acceptance-matrix.md` and `.superpowers/sdd/plan/t018-working-report.md` for exact snapshot/test results and remaining producer/preflight/restore/lifecycle work. Preserve all60 task IDs, required regression/live gates and Advanced actual live Deferred. Do not restart from stale main checkboxes or overwrite the worktree.

Continuation final evidence: worktree T018 internal increment scoped reviews addressed; exact-current fast1296/0failures/0errors/3skips322.477s,375file snapshot0a837bd753ed65814bbf2237e1d6fdbd1741bd160a9fc0de7b7e08fca5bf9f63. Detailed final evidence and next unfinished producer/preflight work are in the worktree checkpoint above. T018 remains unchecked;T001-T017 retained;Advancedactual liveDeferred.

Autonomous continuation2026-11-11: actualworktree now has internal pre-consumption wholebinding/expiry capture and committedHEADaccessor, independentlyreviewed noCritical/Important in scope. Exact-currentfast1305/0failures/0errors/3skips288.022s,375file snapshot424a5d64365a3e7911e1d229c8a22ef6222b6e3c5177f119278433f57f5e11dd. LastcompletedmilestoneT017; T018stillpartial, nextactualcoordinatorproducer/publicprepare/lifecycle. Use the linkedworktree latestacceptancecheckpoint, preserveAdvancedactual liveDeferred and mandatoryexternalgates.
