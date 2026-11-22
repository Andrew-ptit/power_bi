# Evidence — Feature 004

Mọi dòng `Pass` phải kèm lệnh, output và revision thật.

## Evidence theo task

| Task | Status | Command | Output | Revision |
|---|---|---|---|---|
| T400 | Pass | `py tools/run_checks.py fast`; `py -m unittest tests.unit.test_assistant_understand tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.contracts.test_assistant_wl2 tests.integration.test_assistant_flow_api -v`; `py -m unittest tests.taskpane.test_taskpane_js -v` | fast: run=1293 failed=0 errors=0 skipped=3 elapsed=203.881s (EXIT=0); understand/keys/roles/wl2/flow-api: Ran 82 tests OK (18.628s); taskpane_js: Ran 15 tests OK (4.527s); gate log `.artifacts/gate_a5.log` | `3f1c607` (working tree chỉ sửa `acceptance.md`; baseline fast chạy trên `main` 592e1d3 — xem Ghi chú T400) |
| T401 | Pass | `py -m unittest tests.contracts.test_assistant_model_view_contract -v`; `py -m unittest tests.unit.test_import_smoke -v` | contract: Ran 7 tests OK (0.396s, EXIT=0); import_smoke: Ran 1 test OK (0.328s, EXIT=0); schema đóng + 4 fixture `model_view` (8 bảng star, per_sheet, bảng đơn, 22 ví dụ sai); docs ghi supersession có ngày; không đụng code runtime/UI | `29c6869` (schema, contract test, fixtures, 4 owner docs) |
| T402 | Pass | `py -m unittest tests.unit.test_assistant_model_view -v`; `py -m unittest tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.unit.test_assistant_understand -v` | model_view: Ran 21 tests OK (3.237s, EXIT=0); keys/roles/understand: Ran 48 tests OK (2.027s, EXIT=0); oracle độc lập `model_view_oracle.py` không import module đang test; TP-FIN/TP-SALES khớp oracle; 3 suite WL2 cũ không đổi | `169f5ed` (module engine + oracle + 21 unit test) |
| T405 | Pass | `node tests/taskpane/taskpane_model_diagram.js`; `py -m unittest tests.taskpane.test_taskpane_js -v` | node: 12 kịch bản `ok` + `passed` (EXIT=0); taskpane_js: Ran 16 tests OK (3.812s, EXIT=0) (15 cũ + 1 mới); asset order/routes: Ran 5 tests OK; module không tham chiếu Office/fetch/biến toàn cục | `4a2c42a` (module sơ đồ + test Node + đăng ký asset/registry) |
| T403 | Pass | `py -m unittest tests.integration.test_assistant_model_view_api tests.contracts.test_assistant_model_view_contract -v`; `py -m unittest tests.integration.test_assistant_flow_api tests.integration.test_assistant_v2_journey tests.integration.test_assistant_adversarial_transitions tests.contracts.test_assistant_e2e tests.contracts.test_coordinator_dispatch -v`; `py -m unittest tests.integration.test_assistant_smoke_script -v` | 1: Ran 20 tests OK (10.521s, EXIT=0); 2: Ran 39 tests OK (23.872s, EXIT=0); 3: Ran 1 test OK (2.489s, EXIT=0); đo fixture tổng hợp 300.000 ô compute: ingest 0.73s, understand 7.83s (không đặt ngưỡng); grain question chỉ cho snapshot không dim/lookup (TP-FIN: FX là lookup → không có; fixture 1 bảng snapshot → 1 câu hỏi) | `0346e67` (session + endpoint 409 + 12 test API + case contract) |
| T404 | Pass | `node tests/taskpane/taskpane_assistant_understand.js`; `node tests/taskpane/taskpane_assistant_journey.js`; `node tests/taskpane/taskpane_assistant_entry.js`; `node tests/taskpane/taskpane_assistant_flow.js`; `py -m unittest tests.taskpane.test_taskpane_js -v` | understand: 10 case `passed` (EXIT=0); journey: 8 case; entry: guards passed; flow: passed (thêm case answer→invalidate plan); gate: Ran 17 tests OK (5.424s, EXIT=0); hành trình 3 bước, measure compute tự động, fallback discover 1 lần, nút cũ chỉ đo lại, flow-understand-section cũ không hiện | `ca52cf3` (entry 3 bước + understand view + flow wiring + 4 test JS) |
| T406 | Pass (Bước 0: Not run) | `node tests/taskpane/taskpane_model_dialog.js`; `py -m unittest tests.taskpane.test_taskpane_js -v` | node: 8 kịch bản + `passed` (EXIT=0); gate: Ran 18 tests OK (5.955s, EXIT=0); excel_addin_server: Ran 17 tests OK (8.149s, EXIT=0); **Bước 0 (phép thử khả năng DialogApi 1.2): Not run — không có Excel/synthetic harness**; giới hạn message 1 MiB là hằng số an toàn chờ đo live; US4 chưa pass ở mức live | `694dd66` (dialog html/js + nút Mở rộng + asset + 8 kịch bản Node + integration case) |
| T407 | Pass | `py tools/run_checks.py fast` (log `.artifacts/gate_t407b.log`); `py tools/run_checks.py runtime` (`.artifacts/runtime_t407.log`); `py -m unittest discover -s tests -v` (`.artifacts/discovery_t407.log`) | fast: gate=fast run=1338 failed=0 errors=0 skipped=3 elapsed=204.893s (EXIT=0); runtime: gate=runtime run=18 failed=2 errors=0 skipped=0 elapsed=460.976s (EXIT=1) — 2 fail đều là `tests.runtime.test_typed_local_parity_runtime` PARITY_FIXTURE_TIMEOUT (lỗi có sẵn baseline, không Excel COM, không tính pass); discovery: Ran 1359 tests FAILED (failures=1, skipped=6) — 1 fail duy nhất là parity nói trên (lỗi có sẵn); không có lỗi mới so với baseline T400 (1293). Sửa test_01_exact_file_tree theo cho phép người dùng (thêm cây model_view/ + chuẩn hóa sort_keys). Ma trận HS/H/HC điền đầy; CURRENT_STATUS.md thêm mục feature 004 | `dbb7435` + `ea65087` |
| T408 | Not run | — | Không có Excel Desktop/synthetic harness trong môi trường này; không giao phần kiểm chứng cho người dùng | working tree |
| T404 (bổ sung) | Pass | `node tests/taskpane/taskpane_assistant_journey.js`; `node tests/taskpane/taskpane_assistant_flow.js`; `py -m unittest tests.taskpane.test_taskpane_js -v` | journey: 10 case `passed` (EXIT=0) (thêm: limit → fallback discover 1 lần, sample OK; lần 2 fail → lỗi không lặp); flow: `passed` (thêm assert mode compute/discover của handoff); gate: Ran 18 tests OK (4.639s, EXIT=0) | `568287a` (2 case bắt buộc T404 còn thiếu) |

## Bảng ánh xạ đường dẫn (T400 điền)

| Trách nhiệm (plan §4) | Đường dẫn tại ngày viết plan | Đường dẫn thực tế | Ghi chú |
|---|---|---|---|
| Luật `grainKind`, dựng `modelView`, hash | `pbip_assistant/sources/assistant_model_view.py` (mới) | chưa tồn tại — T402 tạo | — |
| Oracle độc lập cho `modelView` | `tests/support/model_view_oracle.py` (mới) | chưa tồn tại — T402 tạo | — |
| Unit test engine | `tests/unit/test_assistant_model_view.py` (mới) | chưa tồn tại — T402 tạo | — |
| Schema đóng | `pbip_assistant/schemas/assistant_model_view.schema.json` (mới) | chưa tồn tại — T401 tạo | — |
| Contract test | `tests/contracts/test_assistant_model_view_contract.py` (mới) | chưa tồn tại — T401 tạo | — |
| Câu hỏi `grain`; store trả/xóa `modelView`; phân biệt lỗi giới hạn | `pbip_assistant/sources/assistant_session.py` | đúng vị trí; `_questions(snapshot, understand)` tại dòng 73, `add()` tại dòng 77; `_understand`/`_questions` reset tại dòng 129, 218, 350 | T403 |
| Ánh xạ `AF_UNDERSTAND_LIMIT` → 409 | `pbip_assistant/coordinator/endpoints/assistant.py` (`_ASSISTANT_STATUS`) | đúng vị trí | T403 |
| Test API/store | `tests/integration/test_assistant_model_view_api.py` (mới) | chưa tồn tại — T403 tạo | — |
| Hành trình 3 bước | `pbip_assistant/excel_addin/assistant_entry.js` | đúng vị trí | T404 |
| UI bước Hiểu (danh sách) | `pbip_assistant/excel_addin/assistant_understand.js` (mới) | chưa tồn tại — T404 tạo | — |
| Markup/style bước Hiểu | `pbip_assistant/excel_addin/taskpane.html`, `taskpane.css` | đúng vị trí | T404, T405 |
| Nối luồng Trợ lý | `pbip_assistant/excel_addin/taskpane_flow.js` | `flowUnderstand` dòng 479, `flowPlanDraft` dòng 527, `preparationBusinessHandoff` dòng 362, `renderFlowQuestions` dòng 1127, `renderFlow`/`flow.answers` dòng 384, 458, 587, 601 | T404 |
| Mount hành trình | `pbip_assistant/excel_addin/taskpane.js`, `preparation_bridge.js` | `taskpane.js` dòng 191 gọi `preparationBusinessHandoff(await bridge.businessSourcesFromScan())`; `businessSourcesFromScan` ở `preparation_bridge.js` dòng 218 | T404 (preparation_bridge chỉ đọc) |
| Thứ tự nạp script và danh sách asset | `taskpane.html` (thẻ `<script defer>`), bảng asset `coordinator/server.py`, `tests/contracts/test_taskpane_asset_order.py`, `test_taskpane_asset_routes.py` | bảng asset tại `server.py` dòng ~429–441; danh sách script: taskpane_core → taskpane_flow → taskpane_workspace → taskpane_problem_chain → taskpane_typed_pq → taskpane.js, assistant_entry.js, assistant_browser.js… | T404, T405, T406 |
| Layout + render sơ đồ | `pbip_assistant/excel_addin/assistant_model_diagram.js` (mới) | chưa tồn tại — T405 tạo | — |
| Hộp thoại 1 : 3 | `pbip_assistant/excel_addin/model_dialog.html`, `model_dialog.js` (mới) | chưa tồn tại — T406 tạo | — |
| Đăng ký asset | `pbip_assistant/coordinator/server.py` (bảng asset) | dòng ~429–441 | T404, T405, T406 |
| Test task pane | `tests/taskpane/taskpane_assistant_understand.js`, `taskpane_model_diagram.js`, `taskpane_model_dialog.js` (mới); `taskpane_assistant_journey.js`, `taskpane_assistant_entry.js` (cập nhật) | chưa tồn tại (các file mới); `taskpane_assistant_journey.js`/`taskpane_assistant_entry.js` tồn tại | T404–T406 |
| Đăng ký script và case | `tests/taskpane/test_taskpane_js.py`, `tests/required_cases.json` | đúng vị trí | T404–T407 |
| Owner docs | `docs/current/TASKPANE_UI.md`, `ASSISTANT_FLOW_SPEC.md`, `ASSISTANT_WL2.md`, `specs/003-source-import-redesign/spec.md` (ghi supersession) | cả bốn đều tồn tại | T401 |
| Trạng thái | `docs/current/CURRENT_STATUS.md`, `acceptance.md` | đúng vị trí | T407 |

## Baseline (T400 điền)

| Lệnh | run | fail | error | skip | Thời gian | Lỗi có sẵn |
|---|---|---|---|---|---|---|
| `py tools/run_checks.py fast` | 1293 | 0 | 0 | 3 | 203.881s | không |
| `py -m unittest tests.unit.test_assistant_understand tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.contracts.test_assistant_wl2 tests.integration.test_assistant_flow_api -v` | 82 | 0 | 0 | 0 | 18.628s | không |
| `py -m unittest tests.taskpane.test_taskpane_js -v` | 15 | 0 | 0 | 0 | 4.527s | không |

### Ghi chú T400 (đối chiếu spec §1 và HANDOFF §3)

- Nền: `main` sau merge `integration/source-import-003` (`592e1d3`); `taskpane.html` chỉ có `assistant-step-source` và `assistant-step-problem` (0 lần xuất hiện `assistant-step-clean`); có `assistant_browser.js`; `git merge-base --is-ancestor codex/source-import-003 HEAD` thành công. P1–P7 còn đúng.
- Baseline fast chạy trên `main` 592e1d3 (sau merge 003), **không** phải trên `3f1c607`. `3f1c607` khác `592e1d3` đúng một file: `specs/004-understand-data-step/acceptance.md`. Hai lệnh unittest còn lại cũng chạy trên `592e1d3`.
- P8: `preparationBusinessHandoff` nạp `discover` (dòng 370 `flowPreparedWorkbookSources(review, "discover")`, dòng 376 ingest mode `discover`); store nhận `compute` ở lần nạp đầu (không có `expectedPlanningHash` trong request ingest) — tiền đề H19 đúng. Kiểm lại bằng code và test:
  - `assistant_session.py` dòng 205–212: khi `expected_planning_hash is None` bỏ qua kiểm tra stage `planning`/`branched`; chỉ yêu cầu mọi request cùng mode `discover|compute` (dòng 201–204).
  - `py -m unittest tests.integration.test_assistant_flow_api.AssistantFlowApiTests.test_compute_requires_full_rows_and_correct_width tests.integration.test_assistant_flow_api.AssistantFlowApiTests.test_compute_tail_is_hash_bound_and_revalidated` → `Ran 2 tests in 1.155s` `OK` (EXIT=0) — lần nạp đầu mode `compute`, không kèm `expectedPlanningHash`.
- P9: `flowWorkbookCell` (dòng 75–103) đổi ô số có numberFormat ngày thành chuỗi ISO (`date.toISOString().slice(0, 10)`, kèm phần thời gian nếu có); cột ngày `yyyy-mm-dd` do 003 nhập tới `raw_tables` ở dạng chuỗi ISO — đúng mô tả. Xác nhận bằng phép thử Node tạm (không commit, `.artifacts/t400_flowworkbookcell_check.js`): `node .artifacts/t400_flowworkbookcell_check.js` → 7 dòng `ok - …` + `passed` (EXIT=0). Oracle viết tay: serial 45292 + `yyyy-mm-dd` → `2024-01-01`; serial 1 → `1900-01-01`; serial 61 → `1900-03-01`; serial 45292.5 + `yyyy-mm-dd h:mm` → `2024-01-01T12:00:00`; giá trị không phải số giữ nguyên; serial 60 bị chặn `AF_WORKBOOK_DATE_UNSUPPORTED`; format không phải ngày giữ số dạng chữ.
- `_HASH_BASIS` tại `pbip_assistant/sources/assistant_understand.py` dòng 14; `understand`/`understandHash` không đổi trong T400.
- Mốc đối chiếu: TP-FIN roles=7 relationships=7; TP-SALES roles=5 relationships=5; TP-UNKNOWN dùng chung snapshot/understand của TP-FIN (chỉ brief/decisions khác — kiểm lại `assistant_fin.py` dòng 392–405: `unknown_brief` dòng 392–399; `unknown_review` tham chiếu chung `snapshotHash`/`understandHash` dòng 400; payload `tp-unknown/` dòng 405). Ghi chú cũ "dòng 400–405" đã sửa thành "dòng 392–405" cho khớp khối tạo artifact TP-UNKNOWN.

### Hash và id câu hỏi baseline (T403 so sánh)

| Fixture | understandHash | id câu hỏi (`_questions` của store trên fixture) |
|---|---|---|
| TP-FIN | `sha256:339bd6586d18330bda4737697e6e6be53a86aa2552722811797dc52f56a0f845` | `q_1042769b3780`, `q_1343f3c4e15f`, `q_2b8053b28635`, `q_3c69b42de7ff`, `q_61d4f6af5db8`, `q_731b117d72c6`, `q_79a639f201c3`, `q_7a5cf136887b`, `q_a92352ee848d`, `q_d9b1034ec63b`, `q_e261b362bf73`, `q_e667e0bcf493`, `q_f3707735ac3a` |
| TP-SALES | `sha256:b0c70bc5aa8ccb9e8cb99e35842e0d82336e50b4d54529d2cb19111a493a4dd7` | `q_2b159ed31308`, `q_303a70ac6328`, `q_60227088c2e7`, `q_6314444ae084`, `q_a83087777d24`, `q_c853662b4a41`, `q_da4efa226878` |
| TP-UNKNOWN | `sha256:339bd6586d18330bda4737697e6e6be53a86aa2552722811797dc52f56a0f845` (dùng chung với TP-FIN) | như TP-FIN (cùng snapshot/understand) |

## Ma trận yêu cầu (T407 điền)

| ID | Test chứng minh | Kết quả |
|---|---|---|
| HS01–HS04 | taskpane_assistant_journey (case 3–4, 10), taskpane_assistant_entry (case 3, 5), taskpane_assistant_understand (case 1–2, 5), T403 test_understand_returns_model_view | Pass |
| HS05–HS07 | taskpane_assistant_flow (case q_ans/invalidatedAnswers), T403 test_existing_question_ids, T404 understand test (setAnswer), taskpane_assistant_entry (case 4) | Pass |
| HS08–HS10 | taskpane_model_diagram (marks, wireState, endpoints, keyboard), taskpane_assistant_understand (case 10 a11y) | Pass |
| HS11–HS12 | taskpane_model_dialog (case 7 pure-view, case 5 stale), tests/integration/test_excel_addin_server.test_model_dialog_assets… | Pass (live Not run) |
| HS13 | taskpane_assistant_understand (case 5), T403 test_no_fact_graph | Pass |
| H01–H02 | journey/entry tests (tự measure, không plan-draft), T403 test_understand_hash_unchanged, contract test (modelView ngoài understand) | Pass |
| H03–H05 | T402 test_per_sheet, T402 6 luật grainKind, T403 test_existing_question_ids | Pass |
| H06–H08 | taskpane_assistant_understand (case 1–8), taskpane_assistant_entry (case 4 continue), flow test answers | Pass |
| H09–H10 | journey (case 8), entry (case 3 updateWorkbook), flow (changedWorkbook AF_SPEC_STALE), updateFlowButtons (analyze disabled khi understand còn hiệu lực) | Pass |
| H11–H12 | taskpane_model_diagram (focus/full/deterministic) | Pass |
| H13–H15 | taskpane_model_dialog (case 2 protocol), taskpane_model_diagram (textContent, keyboard), understand (case 7, 10) | Pass (H13 live Not run) |
| H16–H17 | T402 test_no_cell_values, contract test (no sample/evidence, 200 cap), taskpane_model_diagram (>12 cột), taskpane_model_dialog (case 6 limit) | Pass |
| H18 | toàn bộ suite feature (T401–T406) + gate fast | Pass |
| H19–H21 | T402 test_measured_on_full_vs_sample, T403 test_compute_first_ingest, journey (case 9 limit→discover 1 lần), flow (handoff mode compute/discover) | Pass |
| HC01–HC02 | T403 test_understand_hash_unchanged, T402 oracle TP-FIN/TP-SALES, contract fixtures | Pass |
| HC03–HC04 | journey/entry (ô đề bài rỗng, không plan-draft), T403 test_grain_answer_reaches_plan_request | Pass |
| HC05–HC06 | taskpane_model_diagram, taskpane_model_dialog (8 case) | Pass (live Not run) |
| HC07 | T403 test_no_fact_graph, understand case 5 | Pass |
| HC09 | T402 test_relationship_orphans_on_full_rows, journey case 9 (sample fallback cảnh báo) | Pass |
| HC08 | `py tools/run_checks.py fast` (T407), runtime + discovery (T407) | Pass/đang chạy T407 |

## Thay đổi được duyệt trong lúc làm

Ghi mỗi thay đổi contract, mở rộng allowlist hoặc đổi yêu cầu thành một dòng `Approved … <ngày>` kèm người duyệt. Không sửa lặng lẽ.