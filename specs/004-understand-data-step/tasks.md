# Tasks — feature 004 (bước Hiểu dữ liệu và sơ đồ quan hệ)

Input: [spec.md](spec.md), [plan.md](plan.md), [contracts/model-view.md](contracts/model-view.md), [data-model.md](data-model.md).
ID `T400–T408` thuộc feature 004. Mỗi task là một đơn vị bàn giao cho **một agent**, có test đỏ trước, commit riêng mang ID task.

## Trạng thái (cập nhật 2026-11-22)

| Task | Trạng thái | Ghi chú |
|---|---|---|
| T400 | Chưa làm | **Chặn mọi task khác.** Chỉ bắt đầu sau khi giai đoạn A của [HANDOFF.md](HANDOFF.md) xong (nhánh tích hợp 003 đã vào `main`, gate fast xanh) |
| T401–T408 | Chưa làm | — |

## Quy ước chung cho mọi agent

- Đọc `AGENTS.md` ở root trước. Quy tắc ở đó thắng file này.
- Script task pane là classic script có thứ tự nạp cố định. Mỗi file JS/HTML mới phải được thêm vào `taskpane.html` (đúng vị trí), bảng asset của `coordinator/server.py`, và hai test `tests/contracts/test_taskpane_asset_order.py`, `tests/contracts/test_taskpane_asset_routes.py` trong cùng task; ba chỗ này nằm trong allowlist của T404, T405, T406.
- Chỉ sửa file trong mục **Files** của task (sau khi đã ánh xạ theo T400). Cần ra ngoài → dừng, báo lý do, không tự mở rộng.
- TDD: viết test → chạy thấy đỏ **đúng lý do** → implement tối thiểu → xanh → chạy lại lệnh của task.
- Không thêm dependency; không đổi manifest/version; không `git reset/stash/checkout` toàn repo; không merge/rebase branch khác.
- Không sửa `understand`, `_HASH_BASIS`, id câu hỏi hiện có, Domain Pack, Brief/Spec/Record, Typed, Problem Chain, Advanced, backend preparation.
- Không gọi Codex/AI trong code mới. Không log tên sheet/cột, giá trị ô, đường dẫn.
- Chuỗi UI mới: tiếng Việt, `textContent`, có `aria-live` cho tiến độ.
- Không sửa golden/hash ghim, không gỡ hay nới test để gate xanh. Gặp → dừng, báo.
- Không triển khai mục mang thẻ `[HOÃN-K]` hoặc mục "Ngoài phạm vi" của spec §3.
- Xong task: thêm một dòng vào [acceptance.md](acceptance.md) theo đúng định dạng ở cuối file này.

## Điều kiện dừng (áp dụng cho mọi task)

1. Hành vi hiện có trái với giả định ghi trong spec §1 hoặc plan §0.
2. Cần sửa file ngoài allowlist, hoặc cần đổi contract.
3. Một test hiện có fail vì lý do không thuộc task.
4. Không chắc một thao tác có ghi vào workbook người dùng hay không.

Khi dừng: ghi `Blocked (§<số>)` vào acceptance kèm lệnh và output, không đánh dấu pass.

## Phụ thuộc

```
T400 ── T401 ──┬── T402 ── T403 ──┐
               └── T405 ──────────┼── T404 ── T406 ── T407 ── T408
```

T402 ∥ T405. T404 → T406 cùng một agent (chung `taskpane.html`, CSS, bảng asset).

---

## T400 — Đối chiếu nền và chụp baseline (không viết code sản phẩm)

**Mục tiêu**: xác nhận nền đúng giả định, lập bảng ánh xạ đường dẫn, có số liệu baseline để so sánh.

**Files**: chỉ `specs/004-understand-data-step/acceptance.md`.

**Việc phải làm**
1. Ghi `git rev-parse HEAD`, branch, số path chưa commit. Không thay đổi trạng thái Git.
2. Xác nhận nền có feature 003: `taskpane.html` chỉ có `assistant-step-source` và `assistant-step-problem`, có `assistant_browser.js`, không còn bước `clean`; `git merge-base --is-ancestor codex/source-import-003 HEAD` thành công. Thiếu → dừng (§1).
3. Lập bảng ánh xạ cho từng dòng của plan §4: trách nhiệm → đường dẫn thực tế hiện tại. Mốc đối chiếu ngày 2026-11-22 trên nhánh tích hợp: `flowUnderstand`, `flowPlanDraft`, `preparationBusinessHandoff`, `renderFlowQuestions`, `state.flow.answers` ở `taskpane_flow.js`; mount hành trình ở `taskpane.js`; `businessSourcesFromScan` ở `preparation_bridge.js`; bảng asset ở `coordinator/server.py`. Ghi lại nếu khác.
4. Xác nhận các sự kiện ở spec §1 (P1–P6) còn đúng; sai điểm nào ghi rõ.
5. Chạy và ghi kết quả baseline (run/fail/error/skip/thời gian):
   ```
   py tools/run_checks.py fast          # mốc kỳ vọng: run=1293 failed=0 errors=0 skipped=3
   py -m unittest tests.unit.test_assistant_understand tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.contracts.test_assistant_wl2 tests.integration.test_assistant_flow_api -v
   py -m unittest tests.taskpane.test_taskpane_js -v
   ```
6. Xác nhận bằng test hiện có hoặc một phép thử Node tạm (không commit) rằng `flowWorkbookCell` đổi ô số có numberFormat `yyyy-mm-dd` thành chuỗi ngày ISO, tức cột ngày do 003 nhập tới `raw_tables` ở dạng chuỗi ISO. Kết quả khác → dừng (§1).
7. Xác nhận `preparationBusinessHandoff` hiện nạp `discover` và store nhận `compute` ở lần nạp đầu (không có `expectedPlanningHash`). Ghi lại; đây là tiền đề của H19.
8. Ghi `understandHash` và danh sách `id` câu hỏi của TP-FIN, TP-SALES, TP-UNKNOWN (chỉ hash/id, không nội dung ô) để T403 so sánh.

**Done**: acceptance có bảng ánh xạ, baseline, hash; hoặc `Blocked` kèm lý do. Không file sản phẩm nào đổi.

---

## T401 — Contract đóng + owner docs

**Mục tiêu**: chốt hình dạng `modelView`, câu hỏi `grain` và giao thức hộp thoại trước khi viết engine/UI; ghi thay đổi hành vi vào tài liệu sở hữu.

**Files**
- `pbip_assistant/schemas/assistant_model_view.schema.json` (mới)
- `tests/contracts/test_assistant_model_view_contract.py` (mới)
- `tests/fixtures/assistant/model_view/` (mới: 2–3 ví dụ `modelView` viết tay hợp lệ, 1 file các ví dụ sai)
- `docs/current/TASKPANE_UI.md`, `docs/current/ASSISTANT_FLOW_SPEC.md`, `docs/current/ASSISTANT_WL2.md`
- `specs/003-source-import-redesign/spec.md` (chỉ thêm ghi chú supersession có ngày ở §9/§5, không sửa nội dung cũ)

**Không sửa**: `CURRENT_STATUS.md` (chỉ T407), `AGENTS.md`, code runtime/UI.

**Việc phải làm**
1. Schema đóng (`additionalProperties: false` ở mọi object) đúng contract §2–§3; enum cho `mode`, `structural`, `grainKind`, `cardinality`, `wireState`, `role`.
2. Test: `test_valid_examples_pass`, `test_unknown_key_rejected_at_every_level`, `test_enums_closed`, `test_no_sample_or_evidence_keys_allowed`, `test_columns_capped_at_200`, `test_schema_resolved_via_core_resources`. Dùng `tests/support/json_schema_oracle.py` hiện có nếu phù hợp; không thêm thư viện.
3. Ví dụ viết tay gồm: mô hình sao 8 bảng (1 fan-out, 1 orphan, 1 snapshot), `per_sheet` 2 bảng, bảng đơn.
4. Docs: hành trình ba bước; bước Hiểu là bước có cổng; vị trí câu hỏi xác nhận; `modelView` là khung nhìn dẫn xuất ngoài hash; chế độ từng sheet; `grainKind` và câu hỏi `grain`; hộp thoại là view thuần. Ghi rõ feature này không thêm lời gọi AI.

**Kiểm chứng**
```
py -m unittest tests.contracts.test_assistant_model_view_contract -v
py -m unittest tests.unit.test_import_smoke -v
```

**Done**: hai lệnh xanh; schema khớp contract từng trường; docs không tuyên bố capability chưa làm.

---

## T402 — Engine: `grainKind` và `build_model_view`

**Mục tiêu**: một module thuần, tất định, không I/O, biến dữ liệu đã có thành `modelView`.

**Files**
- `pbip_assistant/sources/assistant_model_view.py` (mới)
- `tests/support/model_view_oracle.py` (mới — oracle viết tay, không import module đang test)
- `tests/unit/test_assistant_model_view.py` (mới)

**API bắt buộc**
```python
def grain_kind(raw_table: dict, candidate_keys: list[dict]) -> tuple[str, dict | None]:
    """→ ("event" | "snapshot" | "unknown", grainEvidence | None) theo spec §6."""

def build_model_view(raw_tables, snapshot, understand, questions) -> dict:
    """→ modelView theo contracts/model-view.md, kèm modelViewHash."""

def model_view_hash(model_view: dict) -> str: ...
```

**Luật**: spec §6 và contract §3. Dùng lại `key_report`/`column_roles`/phép thử ngày hiện có bằng cách import; không sao chép logic, không sửa các module đó. Không tính lại tổ hợp khóa. Không mutate đầu vào. Hằng số ngưỡng có tên.

**Test bắt buộc**
- `test_star_model_tables_keys_roles_match_oracle` (TP-SALES)
- `test_finance_model_matches_oracle` (TP-FIN)
- `test_per_sheet_mode_when_roles_empty` (TP-UNKNOWN hoặc bảng đơn)
- `test_snapshot_detected_entity_by_date` / `test_event_when_date_not_in_key` / `test_unknown_without_date_column` / `test_empty_table_unknown`
- `test_snapshot_thresholds_at_boundary` (đúng 3 ngày; 2 ngày; đúng 50%; dưới 50%; cột ngày đúng 95% và dưới 95%)
- `test_snapshot_picks_smallest_key_then_name_order`
- `test_wire_state_fanout_beats_orphan`
- `test_question_ids_linked_for_relationship_role_grain_warning`
- `test_relationships_identical_set_and_order_to_understand`
- `test_columns_capped_and_column_count_true`
- `test_is_key_and_is_link_flags`
- `test_no_cell_values_except_date_range` (fixture có sentinel trong ô)
- `test_inputs_not_mutated` / `test_deterministic_twice_identical_hash`
- `test_output_validates_against_schema`
- `test_measured_on_full_vs_sample_and_measured_rows` (cùng một bảng 500 dòng nạp `compute`, rồi nạp `discover` 20 dòng)
- `test_relationship_orphans_on_full_rows_match_oracle` (bảng > 20 dòng; oracle tính trên toàn bộ dòng)

**Kiểm chứng**
```
py -m unittest tests.unit.test_assistant_model_view -v
py -m unittest tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.unit.test_assistant_understand -v
```

**Done**: mọi test xanh; module không import coordinator/Office/adapter Codex; ba suite WL2 cũ không đổi kết quả.

---

## T403 — Store/API: trả `modelView`, câu hỏi `grain`

**Mục tiêu**: `understand` và `state` trả `modelView`; câu hỏi `grain` xuất hiện; không hash nào khác đổi ngoài dự kiến.

**Files**
- `pbip_assistant/sources/assistant_session.py`
- `pbip_assistant/coordinator/endpoints/assistant.py` (chỉ thêm `AF_UNDERSTAND_LIMIT` vào `_ASSISTANT_STATUS`)
- `tests/integration/test_assistant_model_view_api.py` (mới)
- `tests/contracts/test_assistant_model_view_contract.py` (bổ sung case API)

**Việc phải làm**
1. `_questions`: thêm topic `grain` đúng contract §5, dùng hàm `add` hiện có. Cần `grainKind` nên nhận thêm dữ liệu đầu vào; không đổi nội dung câu hỏi khác.
2. `understand()`: sau khi có `model` và `questions`, dựng `modelView` dưới cùng lock; lỗi dựng → `AF_UNDERSTAND_INVALID`, không để lại trạng thái nửa vời. Áp dụng cho cả nhánh `roles: []`.
3. `state()`: trả `modelView` (deepcopy) hoặc `null`.
4. Mọi nơi đặt `_understand = None` phải xóa `modelView` cùng lúc (reset, ingest lại, bind lại, đóng).
5. `understand()`: `ValueError` giới hạn của WL2 ("exceeds the bounded …") → `AF_UNDERSTAND_LIMIT`; mọi `ValueError` khác giữ nguyên xử lý hiện có. Nhận diện bằng một tập thông báo/hằng đặt ở một chỗ, không so chuỗi rải rác; không sửa `assistant_keys.py` trừ khi chỉ để xuất hằng đó.
6. Không thêm route, không đổi request.
7. Đo và ghi thời gian `understand` với fixture tổng hợp lớn (ví dụ 3 bảng, tổng khoảng 300.000 ô, nạp `compute`). Chỉ ghi số đo vào acceptance; không đặt ngưỡng fail theo thời gian.

**Test bắt buộc**
- `test_understand_returns_model_view_bound_to_understand_hash`
- `test_state_returns_same_model_view_then_null_after_reset_and_reingest`
- `test_understand_hash_unchanged_for_all_fixtures` (so với giá trị T400 ghi, lấy bằng cách tính trước/sau trong test, không ghim chuỗi)
- `test_existing_question_ids_unchanged_and_grain_added_only_for_snapshot`
- `test_grain_answer_reaches_plan_request` (planner giả ghi lại payload; không gọi Codex)
- `test_no_fact_graph_returns_per_sheet_without_error`
- `test_model_view_absent_from_plan_request_payload` (payload planner không chứa `dateRange`, `modelView`)
- `test_http_understand_and_state_shapes` (qua coordinator test server hiện có)
- `test_compute_first_ingest_then_understand_measures_all_rows`
- `test_wl2_limit_maps_to_af_understand_limit_409_and_leaves_no_partial_state`
- `test_other_value_errors_still_af_understand_invalid`
- `test_plan_request_still_has_at_most_20_sample_rows_after_compute_ingest`

**Kiểm chứng**
```
py -m unittest tests.integration.test_assistant_model_view_api tests.contracts.test_assistant_model_view_contract -v
py -m unittest tests.integration.test_assistant_flow_api tests.integration.test_assistant_v2_journey tests.integration.test_assistant_adversarial_transitions tests.contracts.test_assistant_e2e tests.contracts.test_coordinator_dispatch -v
py -m unittest tests.integration.test_assistant_smoke_script -v
```

**Done**: ba lệnh xanh. Nếu test cũ fail vì `requestHash`/`planningHash` đổi do câu hỏi `grain` → dừng (§3), báo tên test và lý do; không sửa golden.

---

## T405 — Sơ đồ: layout thuần + render (làm song song với T402)

**Mục tiêu**: module JS vẽ sơ đồ nối dây từ một `modelView`, không phụ thuộc task pane.

**Files**
- `pbip_assistant/excel_addin/assistant_model_diagram.js` (mới)
- `tests/taskpane/taskpane_model_diagram.js` (mới)
- `tests/taskpane/test_taskpane_js.py`, `tests/required_cases.json` (đăng ký)
- `pbip_assistant/coordinator/server.py` (chỉ thêm một dòng asset), `pbip_assistant/excel_addin/taskpane.html` (chỉ thêm một thẻ script, trước `assistant_entry.js`)
- `tests/contracts/test_taskpane_asset_order.py`, `tests/contracts/test_taskpane_asset_routes.py`

**API bắt buộc** (UMD như các module `assistant_*.js` hiện có)
```js
layout(modelView, {mode: "focus" | "full", centerTableId, width}) → DiagramLayout   // thuần, không DOM
render(container, layout, {onSelectWire, onSelectTable})                            // DOM API, textContent
neighbours(modelView, tableId) → [tableId]
describeWire(modelView, relationshipId) → {text, marks}                             // câu giải thích tiếng Việt từ số đo
```

**Luật**: data-model `DiagramLayout`; spec H11, H12, H14, H15, H17. Dây nhiều cột: một dây mỗi cặp cột. Bảng cùng cột dọc: dây vòng ra cùng một phía. Không dùng `innerHTML` với dữ liệu.

**Test bắt buộc** (Node, DOM giả như các script hiện có)
- `layout focus: đúng hàng xóm, hàng xóm chỉ hiện khóa + cột nối, hiddenColumns đúng`
- `layout full: mọi bảng, không chồng node, tọa độ trong khung`
- `wire endpoints nằm đúng dòng cột from/to`
- `marks theo cardinality (N:1, 1:N, 1:1, N:N)`
- `wireState → lớp safe/fanout/orphan và nhãn chữ`
- `measuredOn sample → mọi dây và câu describeWire có nhãn "đo trên mẫu"`
- `layout tất định: hai lần gọi cho JSON giống nhau`
- `bảng > 12 cột gộp phần còn lại; cột nối luôn được hiện`
- `describeWire nêu orphan / rowsBefore→rowsAfter đúng số`
- `render không tạo HTML từ tên cột chứa <script>`
- `bàn phím: Tab tới dây/bảng, Enter chọn, Escape bỏ chọn; aria-label có trạng thái`
- `modelView per_sheet không có quan hệ: vẽ một bảng, không lỗi`

**Kiểm chứng**
```
node tests/taskpane/taskpane_model_diagram.js
py -m unittest tests.taskpane.test_taskpane_js -v
```

**Done**: hai lệnh xanh; module không tham chiếu `Office`, `fetch`, biến toàn cục của task pane.

---

## T404 — UI: hành trình ba bước và bước Hiểu dữ liệu

**Mục tiêu**: người dùng đi `Nguồn → Hiểu dữ liệu → Đề bài`; bước Hiểu hiện tổng quan, sheet, quan hệ, cảnh báo và cho trả lời tại chỗ.

**Files** (theo ánh xạ T400)
- `pbip_assistant/excel_addin/assistant_entry.js`
- `pbip_assistant/excel_addin/assistant_understand.js` (mới)
- `pbip_assistant/excel_addin/taskpane.html`, `taskpane.css`
- `pbip_assistant/excel_addin/taskpane_flow.js` (`flowUnderstand`, `flowPlanDraft`, `preparationBusinessHandoff`, `renderFlowQuestions`, `renderFlow`), `pbip_assistant/excel_addin/taskpane.js` (mount hành trình)
- `tests/contracts/test_taskpane_asset_order.py`, `tests/contracts/test_taskpane_asset_routes.py`
- `pbip_assistant/coordinator/server.py` (chỉ dòng asset)
- `tests/taskpane/taskpane_assistant_understand.js` (mới), `taskpane_assistant_journey.js`, `taskpane_assistant_entry.js`, `taskpane_assistant_flow.js` (cập nhật)
- `tests/taskpane/test_taskpane_js.py`, `tests/required_cases.json`

**Việc phải làm**
1. Hành trình: ba nút bước; `understand` chỉ bật khi nguồn đã xác minh; `problem` chỉ bật khi bước Hiểu `ready` (spec H08).
2. Khi nguồn xác minh: chạy `preparationBusinessHandoff` ở chế độ `compute` rồi gọi understand; hiện tiến độ. `AF_UNDERSTAND_LIMIT` hoặc `REQUEST_LIMIT` → chạy lại handoff đúng một lần ở `discover` rồi understand; khi `modelView.measuredOn = sample` hiện cảnh báo cố định và truyền cờ mẫu cho sơ đồ (spec H20). Lỗi khác → trạng thái lỗi với `Đo lại` và `Về Nguồn`, không sang Đề bài.
   Bước tính nhánh: nếu `flow.mode` đã là `compute` thì không yêu cầu đọc lại toàn bộ; đường đọc lại hiện có cho trường hợp `sample` giữ nguyên (spec H21).
3. `assistant_understand.js`: `mount({document, getState, setAnswer, onContinue, diagram})`; render từ `modelView` + `questions` + `answers`. Khối: tổng quan (đếm), sheet (vai trò, số dòng, câu khóa theo HS02, `grainKind`), quan hệ (Danh sách | Sơ đồ — sơ đồ gọi module T405 ở chế độ focus), cảnh báo, chân trang.
4. Mục có `*QuestionId` chưa trả lời: nền "cần xác nhận" + nút là đúng các `options` của câu hỏi đó. Bấm → `setAnswer(questionId, option)` vào trạng thái câu trả lời hiện có.
5. `mode = per_sheet`: thông báo giải thích, không coi là lỗi (HS13).
6. Bước Đề bài: bỏ yêu cầu bấm nút để đo cấu trúc khi kết quả hiểu còn hiệu lực; danh sách câu hỏi hiện có giữ nguyên và phản ánh câu đã trả lời (H10). Nút cũ chỉ còn vai trò đo lại khi kết quả mất hiệu lực.
7. Mất hiệu lực (nguồn đổi, thêm nguồn, workbook đổi, phiên mới): xóa hiển thị bước Hiểu, về bước phù hợp (H09). Dùng cơ chế vô hiệu hóa hiện có, không viết cơ chế mới.
8. Thẻ `flow-understand-section` cũ: không còn hiện sau thẻ đề bài; nội dung chuyển vào bước Hiểu. Không xóa handler mà test khác còn phụ thuộc nếu chưa có thay thế.

**Test bắt buộc**
- `journey: nguồn xác minh → tự ingest + understand → bước Hiểu; ô đề bài rỗng; không request plan-draft`
- `journey: handoff nạp compute; request ingest có mode compute và đủ số dòng`
- `journey: AF_UNDERSTAND_LIMIT → nạp lại discover đúng một lần → cảnh báo "đo trên mẫu" hiện; lỗi giới hạn lần hai → trạng thái lỗi, không lặp`
- `journey: mode compute → bước tính nhánh không đọc lại toàn bộ`
- `journey: understand lỗi → không bật Đề bài; Đo lại gọi lại đúng một lần`
- `journey: nguồn đổi ở bước Hiểu/Đề bài → về Nguồn, modelView cũ không hiện`
- `understand: đếm tổng quan khớp modelView`
- `understand: câu khóa theo cột khóa; không khóa → "Chưa tìm thấy khóa duy nhất"`
- `understand: bấm lựa chọn trên quan hệ fan-out → setAnswer đúng questionId và chuỗi option`
- `understand: câu đã trả lời hiện trạng thái đã trả lời và sửa được`
- `understand: per_sheet hiện thông báo, Tiếp tục vẫn bật`
- `understand: tên sheet/cột chứa HTML được hiện dạng chữ`
- `flow: sang Đề bài thấy câu trả lời đã điền; đổi câu trả lời sau khi có kế hoạch → kế hoạch mất hiệu lực`
- `a11y: aria-current trên bước; aria-live tiến độ; mọi nút ≥ 32px (kiểm lớp CSS); không phần tử rộng cố định > 360px`

**Kiểm chứng**
```
node tests/taskpane/taskpane_assistant_understand.js
node tests/taskpane/taskpane_assistant_journey.js
node tests/taskpane/taskpane_assistant_entry.js
node tests/taskpane/taskpane_assistant_flow.js
py -m unittest tests.taskpane.test_taskpane_js -v
```

**Done**: năm lệnh xanh; không script task-pane cũ nào bị gỡ khỏi gate.

---

## T406 — Cửa sổ mở rộng 1 : 3

**Mục tiêu**: `Mở rộng` mở hộp thoại hiện sơ đồ đầy đủ, đồng bộ với task pane, không có quyền riêng.

**Files**
- `pbip_assistant/excel_addin/model_dialog.html`, `model_dialog.js` (mới)
- `pbip_assistant/excel_addin/assistant_understand.js`, `taskpane.css`
- `pbip_assistant/coordinator/server.py` (chỉ dòng asset), `tests/contracts/test_taskpane_asset_routes.py`
- `tests/taskpane/taskpane_model_dialog.js` (mới); `tests/taskpane/test_taskpane_js.py`, `tests/required_cases.json`
- `tests/integration/` — một case xác nhận asset hộp thoại được phục vụ và không cần/không lộ token

**Bước 0 — phép thử khả năng (làm trước, ghi vào acceptance)**
- Nếu có Excel + synthetic harness: kiểm `Office.context.requirements.isSetSupported("DialogApi", "1.2")`, mở trang trống cùng origin, đo message lớn nhất gửi được qua `messageChild`. Không dùng workbook người dùng.
- Không có Excel: ghi `Not run`, vẫn làm phần còn lại với Office giả; US4 không được ghi pass ở mức live.
- Nếu cần sửa manifest để mở hộp thoại: dừng (§2), hỏi người dùng.

**Việc phải làm**
1. Nút `Mở rộng` chỉ hiện khi `DialogApi 1.2` được hỗ trợ.
2. Giao thức đúng contract §7: `ready` → `model` → `answer`/`close`; `stale` khi mất hiệu lực. Mọi message được kiểm kiểu, key đóng, giới hạn kích thước.
3. `model_dialog`: bố cục lưới `1fr 3fr`; cột trái liệt kê sheet và quan hệ; phải là sơ đồ `mode: "full"` từ module T405. Chọn ở một bên làm nổi phần tương ứng bên kia.
4. Trả lời trong hộp thoại gửi `answer` kèm `modelViewHash`; task pane kiểm hash và `options` rồi mới `setAnswer`; sau đó gửi lại `model` để hộp thoại cập nhật.
5. Hộp thoại không có `fetch`, không dùng API workbook, không đọc token. URL không có query dữ liệu.
6. Đóng hộp thoại (người dùng đóng cửa sổ, lỗi, phiên hết hạn): task pane dọn handler, không rò rỉ trạng thái.

**Test bắt buộc**
- `không hỗ trợ DialogApi 1.2 → nút ẩn, không gọi displayDialogAsync`
- `mở: URL cùng origin, không query; chờ ready rồi mới gửi model`
- `chọn quan hệ ở cột trái → dây tương ứng được đánh dấu, và ngược lại`
- `answer hợp lệ → setAnswer; answer sai hash / sai option / message lạ → bị bỏ qua`
- `stale → mọi nút trả lời trong hộp thoại bị khóa`
- `payload vượt giới hạn → không gửi, task pane hiện thông báo`
- `mã nguồn model_dialog.js không chứa fetch/XMLHttpRequest/Excel.run`
- `đóng hộp thoại → handler được gỡ; mở lại hoạt động`

**Kiểm chứng**
```
node tests/taskpane/taskpane_model_dialog.js
py -m unittest tests.taskpane.test_taskpane_js -v
```

**Done**: hai lệnh xanh; kết quả phép thử khả năng ghi rõ `Pass`/`Blocked`/`Not run`.

---

## T407 — Hồi quy, acceptance matrix, owner status

**Files**: `specs/004-understand-data-step/acceptance.md`, `docs/current/CURRENT_STATUS.md`, `tests/required_cases.json` (chỉ để khớp discovery).

**Việc phải làm**
1. Chạy:
   ```
   py tools/run_checks.py fast
   py tools/run_checks.py runtime
   py -m unittest discover -s tests -v
   ```
   So với baseline T400; phân biệt lỗi mới và lỗi có sẵn.
2. Điền ma trận HS01–HS13, H01–H18, HC01–HC08: test nào chứng minh, kết quả.
3. Required-case registry bằng discovery, không ID thiếu/thừa/trùng.
4. `CURRENT_STATUS.md`: thêm mục feature 004 với lệnh, số liệu, revision, và phần chưa kiểm chứng (live Excel, hộp thoại nếu `Blocked`). Không đổi version.

**Done**: fast xanh; không lỗi mới ở runtime/discovery; ma trận không có ô trống; live ghi trung thực.

---

## T408 — Live synthetic (chỉ khi có Excel)

Dùng synthetic harness hiện có, workbook tổng hợp. Hành trình: nhập fixture → bước Hiểu hiện đúng số bảng/quan hệ → trả lời một quan hệ → mở rộng → trả lời trong hộp thoại → sang Đề bài thấy câu trả lời. Ghi lệnh, revision, thời gian, kích thước, mã lỗi, fingerprint nguồn trước/sau. Không có Excel/harness: `Not run`. Không giao phần kiểm chứng này cho người dùng.

---

## Định dạng báo cáo cuối mỗi task

Một dòng trong `acceptance.md`:

```
| T4xx | Pass / Blocked (§n) / Not run | <lệnh đã chạy> | <số test, thời gian, exit code; điểm chính> | <commit hoặc revision + mô tả working tree> |
```

Kèm trong báo cáo cho người dùng: file đã đổi, thay đổi hành vi, điều chưa kiểm chứng.

## Definition of Done (toàn feature)

- [ ] Hành trình `1. Nguồn → 2. Hiểu dữ liệu → 3. Đề bài`; bước Hiểu hiện ra khi ô đề bài còn rỗng.
- [ ] `understandHash` mọi fixture không đổi; `modelView` khớp oracle và schema.
- [ ] Xác nhận tại bước Hiểu đi vào request lập kế hoạch với đúng `questionId`.
- [ ] Sơ đồ nối đúng cặp cột, ba trạng thái dây, tất định, dùng được bằng bàn phím ở 360px.
- [ ] Cửa sổ 1 : 3 hoạt động với Office giả; kết quả khả năng trên host thật được ghi trung thực.
- [ ] Chế độ từng sheet đi tiếp được.
- [ ] Số đo dựa trên toàn bộ dòng; đường lui sang mẫu chỉ khi vượt giới hạn và luôn có cảnh báo.
- [ ] Không lời gọi AI mới; không dữ liệu rời máy; không log tên sheet/cột/giá trị.
- [ ] Gate fast xanh; không lỗi mới ở runtime/discovery; mọi script task-pane cũ còn trong gate.
- [ ] `acceptance.md` có evidence từng task và `Not run`/`Blocked` trung thực.
