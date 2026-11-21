# Tasks: Baseline tin cậy nghiệp vụ và xác minh ghi Excel

**Input**: `specs/001-business-assurance-baseline/` — spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md.  
**Date**: 2026-11-05. **Status**: To do — tất cả implementation/product verification tasks chưa chạy.  
**Git branch**: main được giữ nguyên khi lập tài liệu; đây không phải lệnh bắt đầu implementation.

## Format và quy tắc pass

Task IDs T001… là local checklist IDs, không phải BPMN IDs; US1…US9 map spec.md, S01…S27 map acceptance-matrix.md. `[P]` chỉ đánh dấu work có thể song song trong cùng phase nếu targets độc lập và prerequisites đã xong. Paths source mới là planned additions, chưa tồn tại vì lượt này chỉ tạo tài liệu.

Mỗi checklist line có tiêu chí pass riêng. Tests được spec yêu cầu tường minh; viết regression/oracle trước implementation và quan sát fail đúng nguyên nhân (không “module missing” thay behavioral red). Không đánh dấu checked chỉ vì file được tạo hoặc mock xanh; phải đúng lớp evidence. Existing canonical docs được cập nhật theo task, không sửa thay đổi người dùng ngoài scope. Không chạy install/add-in/Excel/workbook người dùng, commit hoặc deploy từ danh sách này một cách tự động.

## Phase 1 — Setup

**Goal**: Khóa scope và canonical contract trước code; không initialize lại repo hoặc cài dependency.

**Independent pass/checkpoint**: Reviewable baseline/owner map và contract delta đầy đủ; không có product check bị gọi là đã pass.

- [ ] T001 Ghi scope B01–B09, non-goals và implementation checkpoint trong specs/001-business-assurance-baseline/spec.md; pass: toàn bộ baseline attachment được ánh xạ, Advanced live Deferred và không coi approval planning là nghiệm thu.
- [ ] T002 Đưa delta được review vào docs/current/ASSISTANT_V2_BUILD_SPEC.md, docs/current/PQ_CODE_M_SPEC.md, docs/current/PROBLEM_CHAIN_SPEC.md và docs/current/TYPED_STEP_DIAGNOSTICS_SPEC.md; pass: giữ IDs/owners, nêu Spec/Record3 và legacy write precondition, no implicit history migration trước khi code.
- [ ] T003 [P] Lập evidence template và snapshot provenance trong specs/001-business-assurance-baseline/acceptance-matrix.md; pass: mỗi S01–S27 có oracle/layer/owner, runtime hiện Not run, Advanced live Deferred, không log raw/private data.

## Phase 2 — Foundational

**Goal**: Chốt shared contracts/fixtures và guard routing trước các story; không tạo framework mới.

**Independent pass/checkpoint**: Schema/value/state conventions được khóa bằng fixtures độc lập; giữ current guards và required-case discovery.

- [ ] T004 [P] Tạo synthetic oracles viết tay cho threshold, Q&A, null joins, row25/column201/tails/Decimal trong tests/support/assurance_fixtures.py; pass: không dùng executor/compiler để sinh expected và không đọc workbook người dùng.
- [ ] T005 [P] Thêm characterization tests closed v2 hash/Record, required-null Typed history và binding shape trong tests/contracts/test_business_assurance_contracts.py; pass: v2 fixture bytes/hashes không đổi và unknown fields fail closed.
- [ ] T006 Chốt structures/bounds/policy enums và planned endpoint shapes trong specs/001-business-assurance-baseline/contracts/business-review.md, specs/001-business-assurance-baseline/contracts/write-verification.md; pass: unit/rationale, coverage, state transitions, compatibility và no raw persistence không bỏ ngỏ.
- [ ] T007 Chuẩn bị capability negotiation/guarded dispatch cho contract mới trong pbip_assistant/coordinator/server.py, pbip_assistant/coordinator/endpoints/business_assurance.py và tests/fixtures/contracts/route_paths.json; pass: token/origin/slots/state guards giữ, old coordinator/client mismatch fail closed, không terminate process người dùng.

## Phase 3 — US1: Duyệt ngưỡng có hiểu biết (P1, MVP nội bộ)

**Goal**: B01; policy chỉ thành reviewed khi exact user action được bind.

**Independent pass/checkpoint**: S01–S03 pass độc lập; 100→200 không qua bằng AI tự nâng tolerance/fan-out; MVP này chưa đủ safety/full release.

- [ ] T008 [P] [US1] Viết unit tests trước implementation trong tests/unit/test_assistant_review.py; pass: missing unit/rationale/consent, nonfinite tolerance, stale policy và missing-control/hard-fail distinction đúng S01–S03.
- [ ] T009 [P] [US1] Viết endpoint/hash/replay negative tests trong tests/integration/test_business_assurance.py; pass: client-forged reviewed flag hoặc reviewHash không cấp quyền freeze/approve/apply.
- [ ] T010 [US1] Implement pure BusinessReview canonical validator/hash trong pbip_assistant/sources/assistant_review.py và bind locked lifecycle ở pbip_assistant/sources/assistant_session.py; pass: review source=user, đúng snapshot/plan/question set, thay policy invalidate downstream và đối soát lại.
- [ ] T011 [US1] Thêm coexisting Spec/Decisions/Record3 trong pbip_assistant/sources/assistant_freeze_v3.py, pbip_assistant/sources/assistant_record_v3.py; nối binder trong pbip_assistant/sources/assistant_approval.py; pass: transitive review binding, v2 historical validators giữ, old unreviewed write bị chặn không silently upgrade.
- [ ] T012 [US1] Đưa reviewed policy vào reconciliation/presentation qua pbip_assistant/sources/assistant_reconcile_v2.py, pbip_assistant/coordinator/endpoints/assistant_freeze.py và pbip_assistant/coordinator/endpoints/business_assurance.py; pass: không default 0,01 cho contract mới, policy edit giữ numeric cache nhưng không tái dùng pass cũ, shape/hash1.0 không bị reinterpret.
- [ ] T013 [US1] Thêm màn review thresholds/units/rationale và button guards trong pbip_assistant/excel_addin/taskpane.html, pbip_assistant/excel_addin/taskpane.js, tests/taskpane/taskpane_assistant_flow.js; pass: exploratory A/B tách reviewed pass, thiếu consent không freeze, missing-control ack riêng, stale exact revision không ghi.

## Phase 4 — US2: Xác minh toàn bộ sau ghi (P1)

**Goal**: B02; full verify khác sample, bao phủ Assistant/Typed/cache restore/Advanced.

**Independent pass/checkpoint**: S04–S06 bắt lỗi ngoài mẫu và đúng transport semantics; full claim cần đủ coverage, no formula và correct target/tails.

- [ ] T014 [P] [US2] Viết canonical vector tests trong tests/unit/test_write_verification.py; pass: hand-written expected cho Text Decimal, binary64, date epoch, boolean-vs-number, text-vs-number, null-tail và formula/error cases theo excel-values-v1.
- [ ] T015 [P] [US2] Mở rộng full-range fake-host faults trong tests/taskpane/taskpane_pq_write.js và tests/taskpane/taskpane_pq_source_apply.js; pass: row25 và cột200 sai không báo full, PQ output201 cột bị chặn theo cap; source ngoài scope/tails và Table collision bảo vệ đúng.
- [ ] T016 [US2] Implement pure expected representation/comparison trong pbip_assistant/core/write_verification.py; tích hợp expected từ validated package tại pbip_assistant/powerquery/advanced/runtime.py; pass: không dùng sample, bound cells/bytes và retain no unbounded actual data.
- [ ] T017 [US2] Implement bounded full reader trong pbip_assistant/excel_addin/write_verification.js, load từ pbip_assistant/excel_addin/taskpane.html và nối ba writers trong pbip_assistant/excel_addin/taskpane.js; thêm Assistant column201 case ở tests/taskpane/taskpane_assistant_flow.js; pass: ≤10000 cells/≤1MiB mỗi chunk, real identity/marker/formula/structure/tail checks; cột201 của Assistant được kiểm và không dùng expected dimensions giả measured.
- [ ] T018 [US2] Bind server coverage/verification ở pbip_assistant/powerquery/typed/store.py và pbip_assistant/sources/assistant_session.py, giữ cache authority; pass: metadata-only hoặc boolean verified không complete, matched full proof mới promote normal cache/Record, no cache promotion on mismatch.
- [ ] T019 [US2] Thêm session-local AdvancedAttemptStore trong pbip_assistant/powerquery/advanced/attempts.py và thin integration trong pbip_assistant/coordinator/endpoints/advanced.py, pbip_assistant/coordinator/server.py; pass: preview-sheet và source attempt tách, consent riêng, close/TTL/budget guards, no Typed approval reuse.
- [ ] T020 [US2] Nối begin/chunks/finish/complete guards trong pbip_assistant/coordinator/endpoints/business_assurance.py và tests/contracts/test_business_assurance_contracts.py; pass: nonce/gap/overlap/duplicate/oversize/forged proof bị chặn, all-null tails verified qua logical rectangle và normal full proof đúng attempt.

## Phase 5 — US3: Unknown write và kiểm lại chỉ đọc (P1)

**Goal**: B03; không phủ nhận write đã có thể bắt đầu, không ghi lặp để recover.

**Independent pass/checkpoint**: S07–S09 pass; response loss không cấp lại quyền hoặc mất cảnh báo, recovery zero write/Save/M/cache/Record promotion.

- [ ] T021 [P] [US3] Viết interruption/replay journey tests trong tests/integration/test_write_verification_journey.py; pass: trước dispatch, sau chunk/marker, trước và sau server completion đều có oracle states và write counts.
- [ ] T022 [US3] Đặt mutationPossible latch và giữ bound target warning qua refresh/switch trong pbip_assistant/excel_addin/taskpane.js; bổ sung tests/taskpane/taskpane_advanced_policy_crosscheck.js; pass: Advanced preview lỗi sau import không nói chưa ghi, same uncertain attempt không bấm ghi lại.
- [ ] T023 [US3] Thêm immutable attempt descriptors, stored completion receipts và observation state trong pbip_assistant/sources/assistant_session.py, pbip_assistant/powerquery/typed/store.py, pbip_assistant/powerquery/advanced/attempts.py; pass: duplicate completion trả same receipt không promote cache lần hai; ≤5/64MiB và TTL đóng đúng.
- [ ] T024 [US3] Implement inspect/recheck routes trong pbip_assistant/coordinator/endpoints/business_assurance.py; pass: same session/exact binding lookup được attempt khi lost response, không trả raw expected/approval, expired/missing expected trả insufficient không rerun.
- [ ] T025 [US3] Thêm UI Kiểm tra lại chỉ đọc và four outcomes trong pbip_assistant/excel_addin/taskpane.html, pbip_assistant/excel_addin/taskpane.js; pass: dùng full reader đúng original target, source overwrite kiểm new result/tails, historical success tách current mismatch và không tự Record.
- [ ] T026 [US3] Mở rộng response-loss/reopen cases trong tests/taskpane/taskpane_assistant_flow.js, tests/taskpane/taskpane_pq_typed.js và tests/taskpane/taskpane_pq_source_apply.js; pass: reopen metadata-only không expected/approval, workbook khác/renamed target/duplicate marker không bị kiểm nhầm.
- [ ] T027 [US3] Bổ sung contention/expiry/budget guard tests trong tests/integration/test_write_verification_journey.py; pass: second observation busy, nonce/identity đổi không full-match, absolute TTL không kéo dài, uncertain expected không bị evict để cấp write mới.

## Phase 6 — US4: Mandatory Q&A trên dữ liệu đầy đủ (P1)

**Goal**: B04; plan đúng kiểu chưa đồng nghĩa KPI/keys/null policy đã rõ.

**Independent pass/checkpoint**: S10–S12; gross/net chưa rõ có thể exploratory A/B nhưng không chốt; full-data issue đổi invalidate review cùng schema.

- [ ] T028 [P] [US4] Mở rộng oracle required/advisory/unresolved trong tests/unit/test_assistant_review.py; pass: blank/Chưa rõ/stale ID/unknown planner questions không resolve; critical category không bị AI downgrade.
- [ ] T029 [US4] Chuẩn hóa question/resolution inputs trong pbip_assistant/adapters/codex/assistant_plan.py và pbip_assistant/sources/assistant_review.py; pass: AI chỉ đề xuất, answer definitions explicit, bound question count/text/bytes và disclosure không nới.
- [ ] T030 [US4] Tái đo full-source question set và invalidate review ở pbip_assistant/sources/assistant_session.py; pass: discover→compute giữ schema nhưng issue mới vẫn chặn; no silent reuse answers dưới questionHash khác.
- [ ] T031 [US4] Đưa required/advisory và lý do chặn vào pbip_assistant/excel_addin/taskpane.js, pbip_assistant/excel_addin/taskpane.html; mở rộng tests/taskpane/taskpane_assistant_flow.js; pass: handler/backend cùng chặn, info collapse không coi resolved, presentation notes không chặn vô ích.
- [ ] T032 [US4] Kiểm tương thích clarification/HEAD path trong tests/integration/test_business_assurance.py và tests/taskpane/taskpane_problem_chain.js; pass: mandatory question không tạo candidate/XML revision/approval và current Typed protocol không bị thay thành Assistant shortcut.

## Phase 7 — US5: Policy khóa thiếu và evidence theo khóa (P1)

**Goal**: B05; user chọn missing-key behavior, không âm thầm đổi null join semantics.

**Independent pass/checkpoint**: S13–S15 đủ sáu join kinds với hand-written expected; keys/revisions/source preserved, helper caps enforced.

- [ ] T033 [P] [US5] Viết sáu-join/missing/composite oracle tests trong tests/unit/test_join_policy.py; pass: null/empty/whitespace/0/false/leading-zero, duplicate groups và unmatched rows đúng user policy; old raw merge null=null giữ.
- [ ] T034 [US5] Implement pure explicit transform/evidence ở pbip_assistant/powerquery/typed/join_policy.py; pass: fresh left/right helper discriminator, join original keys+helper, remove helpers, no raw-M/index/new op; helper cap failures controlled.
- [ ] T035 [US5] Tích hợp proposed transformations/review vào pbip_assistant/sources/assistant_session.py và pbip_assistant/sources/assistant_review.py; pass: new planHash/question/review bắt buộc, bounded aggregate metrics từ full sources không lộ raw keys cho Codex/Record.
- [ ] T036 [US5] Nối Typed proposal→new revision qua pbip_assistant/powerquery/typed/store.py và pbip_assistant/powerquery/history/store.py; pass: XML CAS/commit trước runtime, old revision hashes giữ, no annotation/runtimeSummary schema change.
- [ ] T037 [US5] Thêm lựa chọn key policy và per-key counts trong pbip_assistant/excel_addin/taskpane.js, pbip_assistant/excel_addin/taskpane.html; mở rộng tests/taskpane/taskpane_pq_typed.js, tests/taskpane/taskpane_problem_chain.js; pass: visible steps/rationale, global ratio không được mô tả one-to-one và source cells không đổi.
- [ ] T038 [US5] Mở rộng synthetic parity cases trong tests/runtime/test_typed_local_parity.py và tests/integration/test_business_assurance.py; pass: Python/M có cùng logical matched/unmatched multiplicity theo sáu-join oracle; unavailable runtime là Blocked/Not run, không sửa expected cho xanh.

## Phase 8 — US6: Giới hạn và write eligibility trước duyệt (P2)

**Goal**: B06; giữ caps và công khai action/scope/header, không hứa năng lực mới.

**Independent pass/checkpoint**: S16–S18; 100000×4 source không bị hiểu là output chắc ghi được; blockers xuất hiện trước user approval.

- [ ] T039 [P] [US6] Thêm boundary oracles trong tests/integration/test_business_assurance.py; pass: 2×60000 workbook rows, 200/201 planning cols, 75/76 diagnostics cols, steps/helpers và header-cell boundaries mỗi ngưỡng đúng.
- [ ] T040 [US6] Tính authoritative action eligibility trong pbip_assistant/sources/assistant_session.py, pbip_assistant/adapters/codex/assistant_plan.py và pbip_assistant/powerquery/typed/store.py; pass: actual result quá cap chặn freeze/approval trước consume, Apply vẫn recheck và no truncate.
- [ ] T041 [US6] Hiện per-action limits/eligibility trong pbip_assistant/excel_addin/taskpane.js, pbip_assistant/excel_addin/taskpane.html; cập nhật docs/current/TASKPANE_UI.md và tools/excel_addin/README.md; pass: cumulative workbook scope khác file/folder, 512 read/200 plan/256 output/75 diagnostic và header rõ.
- [ ] T042 [US6] Mở rộng eligibility regressions trong tests/taskpane/taskpane_assistant_flow.js và tests/integration/test_write_verification_journey.py; pass: known 400004-cell output không duyệt được, unsupported API/budget chặn trước mutation, không nâng product caps.

## Phase 9 — US7: Quay về có consent đúng tác động (P2)

**Goal**: B07; explicit checkout là quyết định ghi đúng target, View vẫn chỉ xem.

**Independent pass/checkpoint**: S19–S21 cache hit/stale/target-change/keep-delete cases không ghi hoặc xóa ngoài lựa chọn.

- [ ] T043 [P] [US7] Mở rộng cache restore/consent tests trong tests/taskpane/taskpane_problem_chain.js; pass: dialog có revision/sheet/impact, View zero writes, keep/delete là explicit và prior cache giữ khi fail.
- [ ] T044 [US7] Bind destination impact và confirmation trong pbip_assistant/excel_addin/taskpane.js; pass: đích resolved đổi sau consent không write; cache stale/miss chỉ Preview mới và chờ duyệt.
- [ ] T045 [US7] Áp full-verification attempt và current source/HEAD/CAS guards cho cache restore trong pbip_assistant/powerquery/typed/store.py, pbip_assistant/coordinator/endpoints/history.py; pass: old approval không restore, response loss/replay không ghi/cache promote hai lần.
- [ ] T046 [US7] Đối chiếu restore journey trong tests/integration/test_write_verification_journey.py và docs/current/PROBLEM_CHAIN_SPEC.md; pass: source/prior revisions byte-identical, current result đúng selected revision khi success và no implicit subtree deletion.

## Phase 10 — US8: Phạm vi tái sử dụng và báo cáo định kỳ (P2)

**Goal**: B08; giải thích đúng metadata/pipeline/values-only và backlog định kỳ.

**Independent pass/checkpoint**: S22–S24 không giả recover/re-run/Refresh khả năng chưa có; current pipeline reuse vẫn guarded.

- [ ] T047 [P] [US8] Ghi reuse matrix/backlog riêng trong docs/current/TASKPANE_UI.md và tools/excel_addin/README.md; pass: Assistant metadata/JSON audit khác Typed reusable pipeline, Advanced không query persistence; no scheduler/import/auto-write claim.
- [ ] T048 [US8] Thêm copy metadata-only/reuse limits vào pbip_assistant/excel_addin/taskpane.html và pbip_assistant/excel_addin/taskpane.js; pass: không expose nút re-run/import/Refresh chưa hỗ trợ, giữ Decimal Text disclosure.
- [ ] T049 [US8] Mở rộng reopen/new-period cases trong tests/taskpane/taskpane_assistant_custom_xml.js và tests/taskpane/taskpane_problem_chain.js; pass: không restore old approvals/results, Typed kỳ mới cần fingerprint/Preview/approval, XML không raw expected.

## Phase 11 — US9: Năm trục tin cậy và copy có bằng chứng (P2)

**Goal**: B09; reconciliation/quality/parity/write/save được đọc độc lập.

**Independent pass/checkpoint**: S25–S27; total pass không xóa warning, sample không full, add-in no Save không đồng nghĩa user chưa Save.

- [ ] T050 [P] [US9] Định nghĩa presentation oracle trong tests/taskpane/taskpane_assistant_flow.js và tests/taskpane/taskpane_pq_typed.js; pass: date→null+total pass, parity none, sample/full/unknown và Save unknown có nhãn riêng.
- [ ] T051 [US9] Projection trust axes/quality counts ở pbip_assistant/sources/assistant_session.py, pbip_assistant/sources/assistant_record_v3.py và pbip_assistant/excel_addin/taskpane.js; pass: unavailable không 0, full Record/current observation không ghi đè nhau và old Record không mutate.
- [ ] T052 [US9] Đối chiếu copy ở pbip_assistant/excel_addin/taskpane.html, docs/current/ASSISTANT_V2_BUILD_SPEC.md, docs/current/PQ_CODE_M_SPEC.md và tools/excel_addin/README.md; pass: no false Save/Verified claim, Advanced exception/risk/deferral, Text Decimal/knownDifferences giữ.
- [ ] T053 [US9] Khóa unsupported-request behavior trong tests/integration/test_business_assurance.py và tests/taskpane/taskpane_advanced_policy.js; pass: tách cột/bỏ dấu ngoài catalog báo thiếu, không tự chuyển Advanced, no hidden function/catalog expansion.

## Phase 12 — Qualification và consistency

**Goal**: Đóng acceptance đúng lớp và report phạm vi còn Deferred; không bump metadata để tạo cảm giác release.

**Independent pass/checkpoint**: Tất cả task/scenario được ánh xạ, automated/external evidence đúng revision; missing live gates không bị ghi Complete.

- [ ] T054 Đăng ký retained behavioral cases mới trong tests/required_cases.json và bảo toàn 12-script discovery ở tests/taskpane/test_taskpane_js.py; pass: no missing/duplicate/removed-without-replacement case, full gate chạy đúng suite.
- [ ] T055 Mở rộng synthetic Assistant/Typed Office.js drivers trong tests/live/assistant_v2_gate_driver.js, tests/live/taskpane_gate_driver.js, tests/live/server_support.py; pass: actual handlers/load/HEAD/Preview/Confirm/cache/reopen/source checks và fault recovery có write/Save/runner evidence; Advanced include flag vẫn false.
- [ ] T056 Chạy focused→fast→full regression bằng tools/run_checks.py và unittest commands ở specs/001-business-assurance-baseline/quickstart.md, ghi specs/001-business-assurance-baseline/acceptance-matrix.md; pass: exact-current results/errors/skips, full 12 scripts, test oracles độc lập; không chạy product tests ở lượt planning.
- [ ] T057 Thực hiện parity/real Codex/real Office.js qualification trên synthetic fixtures qua tests/runtime/test_typed_local_parity.py, tools/live_excel_gate.py và tests/live/README.md; pass: records đúng từng layer, source/prior revision preserved, TTL/slots/auth giữ; unavailable=Blocked/Not run; Advanced live vẫn Deferred và không tự bật.
- [ ] T058 Đo caps và verification overhead ở fixture biên qua tests/support/assurance_fixtures.py, tests/integration/test_write_verification_journey.py; ghi specs/001-business-assurance-baseline/acceptance-matrix.md; pass: max bytes/peak memory/time/chunk coverage được đo, 5/6 entries/64MiB/body caps không vượt và no fake progress.
- [ ] T059 Reconcile docs/current/ASSISTANT_V2_BUILD_SPEC.md, docs/current/TASKPANE_UI.md, docs/current/CURRENT_STATUS.md, docs/current/ASSISTANT_TRACEABILITY.md và specs/001-business-assurance-baseline/acceptance-matrix.md; pass: P10 stale status sửa theo actual evidence, canonical IDs không drift, scope Advanced Deferred rõ, không tuyên bố full-three-mode Complete hoặc đổi app/npm/HTTP/manifest khi còn gate chưa đạt.
- [ ] T060 Rà độc lập spec→contract→task→evidence tại specs/001-business-assurance-baseline/acceptance-matrix.md và specs/001-business-assurance-baseline/tasks.md; pass: S01–S27 không orphan, tất cả negative paths/compatibility/privacy có oracle; closed artifact/hash/version decisions được review trước merge, không commit/merge tự động.

## Dependencies & Execution Order

Setup T001–T003 → Foundation T004–T007 → user stories. Không start behavior implementation trước contract checkpoint T002/T006.

```text
Foundation → US1 → US4 → US5 → US6
Foundation → US2 → US3
US2 + US3 + US6 → US7
Foundation → US8
US1 + US2 + US3 + US4 + US6 + US8 → US9
US1…US9 → Qualification
```

Trong story: test oracle/negative trước → pure/domain contracts → owner/state → thin endpoint → actual UI handler integration → independent pass. US1 có envelope/schema cơ bản; US4 bổ sung semantic classification/full-data lifecycle, không cho US1 release như đã đủ tất cả safety requirements. US5 helper generation không chạy ngầm ở hydration/compiler.

Stories có thể validate riêng bằng fixtures của mình, nhưng acceptance toàn safety increment cần US1–US5 tích hợp. US6 phụ thuộc US5 để tính helpers vào eligibility; US7 phụ thuộc full verification/unknown/eligibility. Không lấy story MVP làm cớ bỏ acceptance P1 khác.

## Execution batches

Điều chỉnh điều hành ngày 2026-11-10 theo yêu cầu người dùng, không thay T001–T060, pass criteria, story dependencies hoặc Definition of Done. Các C-label chỉ là nhóm thực thi, không là task/requirement IDs mới. Thứ tự dưới đây là thứ tự inline mặc định, giữ các prerequisites hiện có. Không cần sinh lại spec/plan hay một review vòng đầy đủ cho mỗi checklist line.

| Cụm | Task IDs | Prerequisites | Kết quả tại ranh giới / phạm vi kiểm tra |
|---|---|---|---|
| C00 — Contracts và nền tảng | T001–T007 | Đối chiếu workspace và evidence hiện có | T002/T006 được review trước behavior code; fixtures độc lập, v2 characterization và routing guards đúng contract; readiness live được ghi riêng |
| C01 — Review ngưỡng | T008–T013 | C00 | S01–S03; unit review + endpoint/hash/replay + Assistant taskpane; review exact consent, invalidation và v2 compatibility |
| C02 — Full verification | T014–T020 | C00; inline sau C01 | S04–S06; canonical vectors + full reader/fake writer faults + owner/protocol integration; review coverage, transport, cache authority |
| C03 — Unknown và read-only recovery | T021–T027 | C02 | S07–S09; interruption/replay/expiry/contention và affected Assistant/Typed/source-apply taskpane journeys; review zero-write recovery |
| C04 — Mandatory Q&A | T028–T032 | C01 | S10–S12; review unit + business assurance integration + Assistant/Problem Chain taskpane; review full-source invalidation |
| C05 — Missing-key policy | T033–T038 | C04 | S13–S15; join-policy oracles + Assistant/Typed integration + runtime parity đúng scope; review six joins và helper caps |
| C06 — Eligibility | T039–T042 | C05 | S16–S18; boundary fixtures + write journey + Assistant taskpane; review before-approval limits và Apply recheck |
| C07 — Restore consent | T043–T046 | C02, C03, C06 | S19–S21; Problem Chain consent + restore success/recovery journey; review source/history/cache preservation |
| C08 — Reuse scope | T047–T049 | C00; inline sau C07 | S22–S24; docs/UI copy + XML/reopen/new-period scenarios; review no restored authority và unsupported reuse claims |
| C09 — Trust presentation | T050–T053 | C01, C02, C03, C04, C06, C08 | S25–S27; presentation oracles + Assistant/Typed/Advanced policy simulation + unsupported-request integration |
| C10 — Qualification | T054–T058 | C01–C09 đã tích hợp; live gates sẵn sàng cho phần cần live | Required-case/12-script coverage, harness extension, full regression, real runtime/Codex/Office.js và measured bounds; review exact-current evidence; gate thiếu không đóng task |
| C11 — Consistency và rà cuối | T059–T060 | Evidence từ C10, kể cả blockers/deferred | Đồng bộ status/traceability trung thực; rà độc lập spec→contract→task→evidence, không coi baseline Complete khi còn gate bắt buộc thiếu |

### Quy tắc thực thi và tiếp tục

- Đọc checkpoint/evidence rồi kiểm code liên quan trước khi chọn cụm đầu tiên chưa đủ tiêu chí. Không tự check task từ việc có file; cũng không viết lại phần đã đủ evidence. Baseline lúc chỉnh lịch vẫn 60 unchecked; đây không phải kết luận audit đầy đủ implementation.
- Trong C00: scope/evidence mapping → T002/T006 contract checkpoint → behavioral characterization/fixtures trước phần implementation tương ứng → T007 guarded dispatch. Readiness chạy sớm theo quickstart, không là task sản phẩm mới hay thay qualification.
- Trong mỗi cụm: oracle/negative tests trước code liên quan → domain/owner → endpoint/UI → affected success/recovery journey → review cụm. Tái dùng tests/support và evidence đủ scope, không gộp mất các case khác rủi ro/layer. Phát hiện regression sau review thì sửa và rerun phần bị ảnh hưởng, không khởi động lại toàn bộ quy trình.
- Focused checks khi đang sửa cục bộ; thay đổi xuyên owner/protocol/UI và release qualification vẫn full regression cùng affected live gates. All 12 retained JS scripts và required-case registry phải giữ trong automated gate. C10 tập hợp bằng chứng cuối, không phải lý do hoãn mọi integration/live checks đến cuối.
- Một run map được nhiều T/S IDs khi thực sự chứng minh từng tiêu chí. Thay relevant code, dependencies, fixtures hoặc environment thì evidence bị ảnh hưởng phải chạy lại; evidence cũ chỉ còn historical. Không cần chạy lại cùng command trên cùng trạng thái chỉ để check thêm task.
- Review contract tại T002/T006 và khi có contract delta; review working diff/coverage tại ranh giới cụm; T060 vẫn rà độc lập. Không mặc định spawn reviewer/implementer sau mỗi T-ID. Không tự commit/merge hoặc hỏi duyệt lại từng edit nhỏ.
- Khi thực thi, ghi `Execution checkpoint` ngắn trong acceptance-matrix.md: snapshot, cụm/task còn dở, command/layer/result/time, T/S coverage, evidence invalidated, blocker và bước tiếp theo. Không thêm plan khác. Live thiếu thì Blocked/Not run, Advanced live Deferred; tiếp tục các task độc lập nhưng không đóng sai task phụ thuộc/live-required.

## Parallel opportunities và examples

| Story | Có thể chia độc lập sau prerequisites | Phải tuần tự/không tranh file |
|---|---|---|
| US1 | unit test_assistant_review.py và integration test_business_assurance.py | Session/review→v3/binder→routes→taskpane |
| US2 | unit comparison vectors và fake PQ writer/source faults | pure expected→reader→owner→Advanced→protocol |
| US3 | fault test design và UI copy review chỉ đọc | latch/state→routes→recheck UI→expiry cases |
| US4 | question fixture bổ sung độc lập ở test file | Adapter/review→session→UI; không viết cùng files với US1 |
| US5 | six-join oracle và review semantics research | transform→Assistant→Typed→UI→parity |
| US6 | boundary oracle độc lập | domain eligibility→UI/docs→journey; không đồng thời chỉnh US5 session |
| US7 | consent fake-host scenarios độc lập | dialog→restore owner→full journey |
| US8 | reuse docs và XML test scenario ở files khác | taskpane edits serialize với US7/US9 |
| US9 | label test scenarios trước projection | projection→copy→unsupported-request regression |

Ví dụ US1: hai người có thể viết unit và integration tests ở hai file riêng; không đồng thời sửa assistant_session.py hoặc taskpane.js. Ví dụ US2: Python canonical vectors và PQ fake-host faults có thể song song; server wire contract phải thống nhất trước tích hợp reader. `[P]` không là chỉ dẫn spawn agents hoặc chạy parallel tests/Excel slots lúc này.

## Implementation strategy và release checkpoints

- **MVP nội bộ**: Setup+Foundation+US1, chứng minh exact policy consent. Chưa release và chưa tuyên bố baseline đạt.
- **Safety increment**: tích hợp US1–US5; không bỏ live-required evidence hoặc recovery/privacy/compatibility checks.
- **Full baseline**: thêm US6–US9, exact-current automated/runtime/real Codex/Office.js journeys liên quan. Live Advanced vẫn Deferred theo user instruction; full-three-mode qualification không Complete khi còn deferred.
- Giữ all test boxes unchecked cho tới implementation/verification evidence thực. Không yêu cầu người dùng tự thực hiện implementer verification.
- Không version bump ở lượt này; khi có yêu cầu release sau này vẫn phải đáp ứng all required gates và manifest sync rule nếu manifest thay.

## Task statistics

Tổng **60 tasks**. Setup: 3; Foundation: 4; Qualification: 7.

| Story | Tasks | Count |
|---|---|---:|
| US1 | T008–T013 | 6 |
| US2 | T014–T020 | 7 |
| US3 | T021–T027 | 7 |
| US4 | T028–T032 | 5 |
| US5 | T033–T038 | 6 |
| US6 | T039–T042 | 4 |
| US7 | T043–T046 | 4 |
| US8 | T047–T049 | 3 |
| US9 | T050–T053 | 4 |

## Definition of Done

Mỗi scenario trong acceptance-matrix.md có task/test/evidence; unit, HTTP, fake Office, real M, real Codex, actual Office.js được phân biệt. Product status thay đổi chỉ theo evidence mới; evidence không raw cells/paths/credentials. Prior sources/revisions/CAS/approval/TTL/slots/cancelled fields không regression. Unknown recovery không có write, Save, runner, authority hoặc cache/Record side effect. Advanced live deferral là qualification limitation tường minh, không hidden skip.
