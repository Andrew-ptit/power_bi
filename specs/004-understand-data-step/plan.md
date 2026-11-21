# Implementation plan — bước Hiểu dữ liệu và sơ đồ quan hệ

**Spec**: [spec.md](spec.md). **Contract**: [contracts/model-view.md](contracts/model-view.md). **Data**: [data-model.md](data-model.md).
**Goal**: chèn bước `2. Hiểu dữ liệu` giữa `Nguồn` và `Đề bài`; trả ra khung nhìn `modelView` đủ để vẽ sheet/cột/khóa/quan hệ; cho xác nhận tại chỗ bằng cơ chế câu hỏi hiện có; vẽ sơ đồ nối dây trong task pane và trong cửa sổ mở rộng 1 : 3.
**Ngày**: 2026-11-21. **Không** đổi release metadata, manifest, dependency.

## 0. Trạng thái nền (đọc trước khi làm bất cứ việc gì)

Cập nhật 2026-11-22, kiểm bằng lệnh chỉ đọc và một lần chạy gate:

- `main` ở `4a20bb4`, đi trước `origin/main` 7 commit, chưa push; còn 37 file sửa chưa commit và 3 file test bị xóa chưa commit.
- Nhánh `integration/source-import-003` (worktree `.artifacts/worktrees/integration-source-import-003`, HEAD `3e84b17`) chứa `main` + toàn bộ feature 003 trên cấu trúc đã tách; gate fast tại đó: 1.293 run, 0 fail, 0 error, 3 skip. **Chưa merge vào `main`.**
- Plan này **giả định nền là `main` sau khi đã merge nhánh tích hợp**: hành trình hai bước, `assistant_browser.js`, không còn bước Làm sạch. Các bước đưa nền về trạng thái đó nằm ở [HANDOFF.md](HANDOFF.md) giai đoạn A.
- Script task pane đã tách thành các classic script có thứ tự nạp cố định: `taskpane_core.js` → `taskpane_flow.js` → `taskpane_workspace.js` → `taskpane_problem_chain.js` → `taskpane_typed_pq.js` → `taskpane.js`. Thứ tự và danh sách asset được khóa bởi `tests/contracts/test_taskpane_asset_order.py` và `tests/contracts/test_taskpane_asset_routes.py`.

Đường dẫn ở §4 đã được đối chiếu với nhánh tích hợp ngày 2026-11-22. T400 vẫn bắt buộc: xác nhận lại trên nền thực tế lúc bắt đầu.

## 1. Global constraints

- Python 3.13 stdlib; JS thuần cho task pane; không thêm dependency, không build step.
- Không lời gọi Codex mới; không dữ liệu nào rời máy do feature này.
- `understand`, `understandHash`, `_HASH_BASIS`, id câu hỏi hiện có: không đổi.
- Implementation ở module canonical (`sources`, `coordinator`, `excel_addin`); đường dẫn resource/schema qua `core.resources`; không sửa facade phẳng trừ khi cần re-export.
- Giữ thứ tự guard host/origin → session → slot → state lock; `modelView` được tạo và xóa dưới cùng lock với `_understand`.
- Không log tên sheet/cột, giá trị ô, đường dẫn. UI render bằng `textContent`; SVG bằng DOM API.
- Giữ mọi script task-pane đang có trong gate; thêm script mới vào `tests/taskpane/test_taskpane_js.py` và `tests/required_cases.json`.
- Fixture tổng hợp; expected value từ oracle viết tay, không import module đang test.
- Mô phỏng unit/HTTP/Office.js không phải bằng chứng live Excel.

## 2. Kiến trúc thay đổi

```
Python
├── sources/assistant_model_view.py (mới)   ── build_model_view(), grain_kind(), model_view_hash()   [thuần, không I/O]
├── sources/assistant_session.py            ── _questions(): thêm topic "grain"
│                                              understand()/state(): kèm modelView; xóa cùng _understand
├── schemas/assistant_model_view.schema.json (mới) ── contract đóng cho test
└── coordinator/server.py                   ── đăng ký asset mới (JS/HTML hộp thoại)

Task pane
├── assistant_entry.js        ── hành trình 3 bước: source → understand → problem
├── assistant_understand.js (mới)  ── render tổng quan / sheet / quan hệ (danh sách) / cảnh báo; nút trả lời → answers
├── assistant_model_diagram.js (mới) ── layout thuần (focus/full) + render SVG + chọn dây/bảng + bàn phím
├── model_dialog.html / model_dialog.js (mới) ── cửa sổ 1 : 3; chỉ nhận/gửi message
└── script luồng Trợ lý (taskpane.js hoặc file đã tách) ── nối handoff nguồn → ingest → understand; bỏ phụ thuộc "đo cấu trúc" vào nút ở thẻ đề bài
```

Luồng dữ liệu:

```
nguồn xác minh ─► ingest (hiện có) ─► POST /understand ─► {understand, questions, modelView}
                                                              │
                 flow.answers ◄── nút trả lời tại bước Hiểu ◄─┤
                       │                                      └─► messageChild ─► hộp thoại
                       └─► POST /plan-draft (hiện có, khi người dùng lập kế hoạch)
```

## 3. Quyết định thiết kế

| # | Quyết định | Thay thế bị loại |
|---|---|---|
| M1 | `modelView` là khóa cấp trên, dẫn xuất, ngoài mọi hash hiện có | Thêm trường vào `understand` (phá `_HASH_BASIS`, đổi `understandHash`, kéo theo Spec/Record) |
| M2 | Không thêm route; đi kèm phản hồi `understand` và `state` | Route mới (thêm bề mặt auth, sửa route fixture và STATE_PATHS) |
| M3 | Xác nhận = câu trả lời cho câu hỏi đo được hiện có | Kho "override" mới (phải nối vào planner, hash, stale; rủi ro cao) |
| M4 | Phân loại snapshot dựa trên khóa ứng viên đã tính | Tự dò tổ hợp cột mới (vượt giới hạn tính toán WL2) |
| M5 | Tên nghiệp vụ của dòng không được đoán; chỉ nêu cột khóa | "1 dòng = 1 đơn hàng" suy từ tên cột (vi phạm nguyên tắc không đoán) |
| M6 | Layout sơ đồ là hàm thuần JS, tách khỏi render | Tính tọa độ từ DOM (không test được bằng Node, không tất định) |
| M7 | Task pane vẽ chế độ focus; toàn cảnh chỉ ở hộp thoại | Vẽ 8 bảng trong 360px (không đọc được) |
| M8 | Hộp thoại là view thuần, nhận dữ liệu qua message | Hộp thoại tự gọi coordinator (phải chia sẻ token, thêm bề mặt tấn công) |
| M9 | Không hỗ trợ `DialogApi 1.2` thì ẩn nút, ghi `Blocked` | Giả lập cửa sổ bằng overlay trong 360px (không đạt mục tiêu) |
| M10 | Người dùng tự thêm/sửa quan hệ: không làm ở 004 | Làm ngay (cần đường đo mới và đổi request planner) |
| M11 | Bước Hiểu đo trên toàn bộ dòng (`compute`); vượt giới hạn thì lùi về mẫu có cảnh báo (chờ duyệt, HANDOFF Q8) | Giữ `discover` 20 dòng (quan hệ giữa bảng lớn đo ra thiếu/sai, sơ đồ gây hiểu nhầm); nâng giới hạn WL2 (chưa có số đo hiệu năng) |

## 4. Cấu trúc file

| Trách nhiệm | Đường dẫn tại ngày viết | Task |
|---|---|---|
| Luật `grainKind`, dựng `modelView`, hash | `pbip_assistant/sources/assistant_model_view.py` (mới) | T402 |
| Oracle độc lập cho `modelView` | `tests/support/model_view_oracle.py` (mới) | T402 |
| Unit test engine | `tests/unit/test_assistant_model_view.py` (mới) | T402 |
| Schema đóng | `pbip_assistant/schemas/assistant_model_view.schema.json` (mới) | T401 |
| Contract test | `tests/contracts/test_assistant_model_view_contract.py` (mới) | T401, T403 |
| Câu hỏi `grain`; store trả/xóa `modelView`; phân biệt lỗi giới hạn | `pbip_assistant/sources/assistant_session.py` | T403 |
| Ánh xạ `AF_UNDERSTAND_LIMIT` → 409 | `pbip_assistant/coordinator/endpoints/assistant.py` (`_ASSISTANT_STATUS`) | T403 |
| Test API/store | `tests/integration/test_assistant_model_view_api.py` (mới) | T403 |
| Hành trình 3 bước | `pbip_assistant/excel_addin/assistant_entry.js` | T404 |
| UI bước Hiểu (danh sách) | `pbip_assistant/excel_addin/assistant_understand.js` (mới) | T404 |
| Markup/style bước Hiểu | `pbip_assistant/excel_addin/taskpane.html`, `taskpane.css` | T404, T405 |
| Nối luồng Trợ lý: `preparationBusinessHandoff`, `flowUnderstand`, `flowPlanDraft`, `renderFlowQuestions`, `renderFlow`, `state.flow.answers` | `pbip_assistant/excel_addin/taskpane_flow.js` | T404 |
| Mount hành trình (`showProblem`, `onStepChange`, `businessSourcesFromScan`) | `pbip_assistant/excel_addin/taskpane.js`, `preparation_bridge.js` (chỉ đọc nếu không cần sửa) | T404 |
| Thứ tự nạp script và danh sách asset | `taskpane.html` (thẻ `<script defer>`), bảng asset trong `coordinator/server.py`, `tests/contracts/test_taskpane_asset_order.py`, `tests/contracts/test_taskpane_asset_routes.py` | T404, T405, T406 |
| Layout + render sơ đồ | `pbip_assistant/excel_addin/assistant_model_diagram.js` (mới) | T405 |
| Hộp thoại 1 : 3 | `pbip_assistant/excel_addin/model_dialog.html`, `model_dialog.js` (mới) | T406 |
| Đăng ký asset | `pbip_assistant/coordinator/server.py` (bảng asset) | T404, T405, T406 |
| Test task pane | `tests/taskpane/taskpane_assistant_understand.js`, `taskpane_model_diagram.js`, `taskpane_model_dialog.js` (mới); `taskpane_assistant_journey.js`, `taskpane_assistant_entry.js` (cập nhật) | T404–T406 |
| Đăng ký script và case | `tests/taskpane/test_taskpane_js.py`, `tests/required_cases.json` | T404–T407 |
| Owner docs | `docs/current/TASKPANE_UI.md`, `ASSISTANT_FLOW_SPEC.md`, `ASSISTANT_WL2.md`, `specs/003-source-import-redesign/spec.md` (ghi supersession) | T401 |
| Trạng thái | `docs/current/CURRENT_STATUS.md`, [acceptance.md](acceptance.md) | T407 |

## 5. Thứ tự và song song

```
T400 ── T401 ──┬── T402 ── T403 ──┐
               └── T405 ──────────┼── T404 ── T406 ── T407 ── T408
```

- T402 (Python) và T405 (JS thuần, dùng fixture `modelView` từ contract) song song được.
- T404, T405 (phần markup), T406 cùng chạm `taskpane.html`/CSS và bảng asset: **một agent, tuần tự**.
- T406 bắt đầu bằng phép thử khả năng hộp thoại; kết quả `Blocked` không chặn T407.

## 6. Rủi ro và cách xử lý

| Rủi ro | Dấu hiệu | Xử lý |
|---|---|---|
| Nền khác giả định | T400 không tìm thấy hành trình 003 hoặc file đã tách | Dừng ở T400, báo bảng ánh xạ; không tự merge |
| Câu hỏi `grain` làm đổi hash ghim trong test | Test fixture/smoke fail sau T403 | Dừng, báo test và hash; không sửa golden khi chưa được duyệt |
| Phát hiện snapshot sai | Oracle lệch trên fixture | Sửa luật theo spec §6, không nới test; ngưỡng đổi phải ghi "Approved requirement change" |
| Vượt giới hạn tính toán WL2 | `ValueError` giới hạn | Giữ lỗi rõ hiện có; `modelView` không tự tính thêm tổ hợp |
| Hộp thoại không dùng được | `isSetSupported("DialogApi", 1.2)` false, hoặc message bị cắt | Ẩn nút; US4 `Blocked`; không giả lập |
| Script mới sai thứ tự nạp hoặc thiếu trong allowlist | `test_taskpane_asset_order` / `test_taskpane_asset_routes` fail, hoặc `ASSET_MISSING` | Thêm thẻ script, dòng asset và cập nhật hai test đó trong cùng task; module mới phải nạp trước file dùng nó |
| File bị đổi ngoài task trong lúc làm | `git status` có thay đổi không thuộc task | Mỗi task commit riêng; trước mỗi task kiểm lại file sẽ sửa |

## 7. Kiểm chứng

Focused theo task (xem tasks.md). Ở T407:

```
py tools/run_checks.py fast
py tools/run_checks.py runtime
py -m unittest discover -s tests -v
```

So với baseline ghi ở T400. Lỗi có sẵn ở baseline (ví dụ `tests.runtime.test_typed_local_parity` `PARITY_FIXTURE_TIMEOUT`) ghi là có sẵn, không tính pass. Live Excel: T408, chỉ khi có Excel và synthetic harness; nếu không thì `Not run`.

## 8. Feature kế tiếp (chưa lập spec)

Theo bản thiết kế mục 9.1: Đ2 (quyền đọc giá trị, chuẩn hóa hai tầng, sheet quy đổi) và Đ3 (cơ chế gợi ý đề bài). Hai phần này phụ thuộc contract `modelView` và cấu trúc UI của feature 004, nên spec/plan/tasks của chúng được lập sau khi T407 pass. Danh mục bài toán vẫn `[HOÃN-K]`.
