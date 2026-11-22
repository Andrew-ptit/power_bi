# Evidence — Feature 004

Mọi dòng `Pass` phải kèm lệnh, output và revision thật.

## Evidence theo task

| Task | Status | Command | Output | Revision |
|---|---|---|---|---|
| T400 | Pass | `py tools/run_checks.py fast`; `py -m unittest tests.unit.test_assistant_understand tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.contracts.test_assistant_wl2 tests.integration.test_assistant_flow_api -v`; `py -m unittest tests.taskpane.test_taskpane_js -v` | fast: run=1293 failed=0 errors=0 skipped=3 elapsed=203.881s (EXIT=0); understand/keys/roles/wl2/flow-api: Ran 82 tests OK (18.628s); taskpane_js: Ran 15 tests OK (4.527s); gate log `.artifacts/gate_a5.log` | `3f1c607` (working tree chỉ sửa `acceptance.md`; baseline fast chạy trên `main` 592e1d3 — xem Ghi chú T400) |

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
| HS01–HS13 | | |
| H01–H18 | | |
| HC01–HC08 | | |

## Thay đổi được duyệt trong lúc làm

Ghi mỗi thay đổi contract, mở rộng allowlist hoặc đổi yêu cầu thành một dòng `Approved … <ngày>` kèm người duyệt. Không sửa lặng lẽ.