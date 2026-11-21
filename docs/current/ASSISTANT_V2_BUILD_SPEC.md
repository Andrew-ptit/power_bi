# ASSISTANT_V2_BUILD_SPEC — Thi công luồng Trợ lý v2 (mọi workbook, Codex sinh kế hoạch)

| Trường | Giá trị |
|---|---|
| Phiên bản | 1.1 — 30/10/2026 (Asia/Saigon) |
| Changelog | 1.0: bản thi công đầu. **1.1: chốt quyết định G — executor Python thuần (không chạy M qua Excel); thêm §6.5 bốn tầng quản rủi ro lệch ngữ nghĩa** |
| Status | **Spec thi công**; chưa có dòng code nào |
| Đối tượng | Codex / engineer implement. Đây là tài liệu **duy nhất** quyết định phải làm gì, theo thứ tự nào |
| Mục tiêu | Từ 17 module engine rời rạc → một sản phẩm chạy được: mọi workbook → hiểu → hỏi → Codex sinh kế hoạch → xem cả A/B → chốt → thi hành → ghi có nhãn |
| Tài liệu liên quan | `ASSISTANT_INTEGRATION_SPEC.md` (v1.x — **chỉ đọc để tham chiếu chi tiết**, xem §1.3) |
| Ngoài phạm vi | LY, PBIP patch, DAX/TMDL, Advanced M |

---

## 0. Đọc trước khi viết dòng code đầu tiên

### 0.1 Quyết định đã chốt (không hỏi lại)

| # | Chốt | Nghĩa là |
|---|---|---|
| **A** | Codex **đề xuất kế hoạch thao tác có kiểu**; engine validate + thi hành | Codex không sinh số. Mọi con số do engine tính trên dữ liệu thật |
| **B** | Đọc **20 dòng** để hiểu, đọc **toàn bộ** để tính | Hai chế độ ingest tách biệt, artifact ghi rõ chế độ. Mẫu **không bao giờ** dùng để tính số cuối |
| **C** | Mẫu **20 dòng ngẫu nhiên có seed tất định** | Cùng file → cùng 20 dòng. `sampleOrdinals` ghi vào artifact |
| **D** | Preview **cả A và B** trước khi chốt | Hai kế hoạch, hai preview, người dùng chọn rồi mới freeze |
| **E** | File khác qua **đường dẫn đĩa (đã Save)** | Không có "nhiều workbook đang mở" — Office.js không làm được |
| **F** | Decision Record lưu **Custom XML** trong workbook | Theo pattern Problem Chain; bền qua đóng/mở pane |
| **G** | Thi hành bằng **executor Python thuần** (`powerquery/typed_local/`), **không** chạy M qua Excel COM | Xem §6 — đã chốt. Đánh đổi: tốc độ + test không cần Excel, nhưng **tự chịu trách nhiệm khớp ngữ nghĩa** với Power Query |

### 0.2 Ba điều **KHÔNG** được làm

1. **Không xây tầng recipe của v1.x.** `_FIN`, `_SALES`, `RESULT_COLUMNS`, `_supported_recipe`, `assistant_apply.apply_result` — **không** dùng cho v2. Chúng gắn với 2 báo cáo cố định và sẽ bị thay (xem §3).
2. **Không để AI sinh số.** Codex chỉ trả về *kế hoạch* (thao tác + biểu thức). Nếu codex định trả về giá trị đã tính → sai, từ chối.
3. **Không dùng payload mẫu để tính số cuối.** Chốt B. Mọi đường dẫn tới số cuối phải đi qua `mode:"compute"`.

### 0.3 Thứ tự thi công và điều kiện dừng

Mỗi pha dưới đây **tự đứng được** và **chỉ chứa phần sẽ sống tới sản phẩm cuối** (yêu cầu "hiệu quả": không làm rồi bỏ).

```text
P0  Mở khoá            sửa 2 lỗi chặn, gate xanh
P1  Hiểu dữ liệu       WL1 + WL2 + UI card 01/02/04   → bấm thấy "điểm chưa rõ"
P2  Codex sinh plan    WL3 + validate plan             → thấy kế hoạch 2 nhánh
P3  Tính số            đọc full + executor + preview   → thấy bảng A và B có số
P4  Chốt + thi hành    WL4 freeze + approval + apply    → sheet kết quả trong workbook
P5  Ghi có nhãn        WL7 record + Custom XML          → mở lại vẫn còn, hash khớp
P6  Hoàn thiện UI      đủ 8 card + 14 test JS           → runbook chạy hết
P7  Codex nhãn (tuỳ)   nghĩa cột, định nghĩa            → tăng độ chính xác
```

**Không làm gì ngoài pha hiện tại.** Không "chuẩn bị trước" cho pha sau.

---

## 1. Kiến trúc đích

### 1.1 Một hình

```text
┌─ Excel task pane ──────────────────────────────────────────────┐
│ 01 Kết nối workbook (giữ nguyên)                               │
│ 02 Nguồn: chọn sheet/bảng/file + 20 dòng mẫu   ──┐             │
│ 04 Cách hiểu + ĐIỂM CHƯA RÕ (câu hỏi)           ──┤             │
│ 03 Đề bài + trả lời câu hỏi                      │             │
│ 05 Kế hoạch A/B (bảng preview CÓ SỐ cả hai)      │             │
│ 06 Chốt nhánh → Execution Spec                   │             │
│ 07 Duyệt → ghi sheet kết quả                     │             │
│ 08 Kết quả + Decision Record + delta             │             │
└──────────────────────────────────────────────────┼─────────────┘
                                                   │ HTTP (loopback)
┌─ coordinator ────────────────────────────────────▼─────────────┐
│ AssistantEndpoints (mỏng: đọc body, gọi store, map lỗi)        │
│        │                                                        │
│ AssistantSessionStore  ← giữ state + lock + stage              │
│        │                                                        │
│        ├─ WL1 ingest        sources/assistant_ingest.py  ♻     │
│        ├─ WL2 understand    sources/assistant_{roles,keys,understand}.py ♻
│        ├─ WL3 plan draft    ADAPTER MỚI → adapters/codex/typed.py ♻
│        ├─ validate plan     powerquery/typed/{registry,validation}.py ♻
│        ├─ executor          powerquery/typed_local/  ★ MỚI
│        ├─ reconcile         ★ MỚI (không còn recipe)
│        ├─ WL4 freeze        sources/assistant_{decisions,spec}.py ♻
│        ├─ WL6 apply         Excel writer hiện có + assistant_approval.py ♻
│        └─ WL7 record        sources/assistant_record.py ♻ + Custom XML ★
└────────────────────────────────────────────────────────────────┘
  ♻ dùng lại   ★ viết mới
```

### 1.2 Ai sở hữu cái gì

| Tầng | Sở hữu | Không được làm |
|---|---|---|
| `powerquery/typed/{registry,validation,compiler}` | Catalog đóng 15 thao tác, 10 biểu thức, kiểm tính hợp lệ | **Không sửa** catalog. Nếu thiếu thao tác → báo cáo, không tự thêm |
| `powerquery/typed_local/` ★ | Thi hành plan trên bảng trong bộ nhớ | Không biết Excel, không biết HTTP, không sinh số từ AI |
| `sources/assistant_session.py` ★ | State + lock + stage + hash chain | Không parse HTTP, không đọc `self.headers` |
| `coordinator/endpoints/assistant.py` ★ | HTTP | Không giữ quyền state, không tính số |
| `sources/assistant_*` ♻ | WL1/WL2/WL4/WL7 logic đã có | Không gọi Excel, không gọi mạng |

### 1.3 Quan hệ với `ASSISTANT_INTEGRATION_SPEC.md` (v1.x)

Doc đó vẫn dùng được làm **tham chiếu chi tiết**, không phải kế hoạch:

| Cần gì | Đọc ở doc v1.x |
|---|---|
| Ánh xạ mã lỗi engine → HTTP, wire shape `{error:{code,detail,path}}` | §4.4, §4.5 |
| Đọc full values qua Office.js, bẫy ngày `isoDateLocal`, `getDataBodyRange` | §6.2–§6.5 |
| Convention DOM (section/card/`data-state`), danh sách id, `switchTab` | §5.1–§5.6 |
| Quy tắc copy (không được nói "AI đã phân tích"), chip nhãn | §5.6 |
| Đặc tả đầy đủ `tools/assistant_flow_smoke.ps1` | §12 |
| Danh sách test/bảng ánh xạ case JS | §7 |

**Bỏ qua** ở doc v1.x: mọi phần về `_FIN`/`_SALES`, `result_rows`, `build_preview` theo recipe, `apply_result`, `measure_set`.

---

## 2. Năm nguyên tắc hiệu quả (áp cho mọi pha)

1. **Một nguồn sự thật cho kế hoạch.** Plan là dữ liệu JSON có schema; validate bằng catalog đóng. Executor đọc plan; compiler M đọc plan. Không có "đường tắt riêng" nào khác.
2. **Không Excel trong đường tính.** Executor là Python thuần (§7). Excel chỉ dùng để **ghi kết quả** (WL6) và để người dùng xuất M. Nhờ vậy preview A/B nhanh, và **toàn bộ gate chạy được không cần Excel**.
3. **Không có mẫu trong đường tính số.** `mode:"compute"` mới được freeze/execute (§4.1).
4. **Mọi bước là hàm thuần + hash.** Cùng input → cùng output. Không `uuid`, không `random` không seed, không `datetime.now()` bên trong engine — thời gian do caller truyền.
5. **Một pha = một thứ bấm được.** Cuối mỗi pha phải có lệnh test và quan sát cụ thể (§12). Không có pha "hạ tầng chưa thấy gì".

---

## 3. Dùng lại gì / thay gì — số liệu thật

Đã đọc source. Ước lượng theo trọng số file (~250 KB engine):

| Tầng | File | KB | Kết luận |
|---|---|---|---|
| WL1 ingest | `assistant_ingest.py`, `assistant_profile.py` | 29 | ♻ **Dùng lại**, thêm `mode` (§4.1) |
| WL2 understand | `assistant_keys.py`, `assistant_roles.py`, `assistant_understand.py` | 39 | ♻ **Dùng lại nguyên** — đây là nguồn "điểm chưa rõ" |
| WL3 brief | `assistant_brief.py`, `assistant_pack.py`, `assistant_findings.py` | 51 | ❌ **Thay lõi.** `measure_set` là **35 measure P&L gắn cứng** (`assistant_findings.py:305-336`), dispatch `_finance`/`_sales` theo tên cột. Giữ **hình dạng** output + `brief_hash` |
| WL4 freeze | `assistant_decisions.py`, `assistant_execution.py`, `assistant_spec.py` | 34 | ♻ **Dùng lại khung**; bỏ `compile_steps` (thay bằng plan) |
| WL5 preview | `assistant_preview.py` | 27 | ❌ **Bỏ** — `_FIN`/`_SALES`/`RESULT_COLUMNS`/`_supported_recipe` |
| WL5 reconcile | `assistant_reconcile.py` | 20 | ❌ **Viết lại** — `_controls`/`_bridge` gắn FIN (§8) |
| WL6 apply | `assistant_apply.py` | 21 | ❌ **Bỏ** — thay bằng Excel writer + `assistant_approval.py` |
| WL7 record | `assistant_record.py`, `assistant_delta.py` | 24 | ♻ **Dùng lại**, bỏ phần `_FIN` trong delta |
| Catalog + validate + compile | `powerquery/typed/*` | 137 | ♻ **Dùng lại** (chỉ phần registry/validation/compiler) |

**Tỷ lệ thật: ~55% dùng lại, ~45% thay.** Trước đây em nói 70% — sai, vì `measure_set` và `build_brief` đều gắn P&L. Con số 55% vẫn đáng kể vì phần giữ lại chính là **tầng hash/audit** khó nhất.

> **Hệ quả cho kế hoạch:** đừng đụng `assistant_apply.py` và `assistant_preview.py` nữa. Viết đường mới, để file cũ nằm yên cho v1.x (vẫn có test xanh bảo vệ).

---

## 4. Luồng 7 bước — chi tiết thi công

### 4.1 Bước 1 · Get Data — hai chế độ

**Chốt B + C.** Đây là thay đổi quan trọng nhất ở WL1.

```text
mode: "discover"                        mode: "compute"
─────────────────────────────────       ─────────────────────────────
đọc 20 dòng (seed tất định)             đọc toàn bộ dòng
dùng để: hiểu, hỏi, cho Codex xem       dùng để: tính số, preview A/B
KHÔNG được: freeze, execute             được: freeze, execute
```

#### Lấy mẫu tất định

```
seed    = sha256( header_json ‖ "|" ‖ rowCount ‖ "|" ‖ columnCount
                  ‖ "|" ‖ hash(row[0]) ‖ "|" ‖ hash(row[rowCount-1]) )
offsets = {0, rowCount-1} ∪ draw_18_distinct(seed, range = 1 .. rowCount-2)
sampleOrdinals = sorted(offsets)          # luôn tăng dần, không trùng
```

- Luôn ghim **dòng đầu và dòng cuối** (bắt được dòng bất thường ở biên).
- 18 dòng còn lại lấy theo PRNG có seed ở trên ⇒ **cùng file → cùng 20 dòng**.
- `rowCount <= 20` ⇒ lấy hết, `sampleOrdinals = [0..rowCount-1]`.
- `rowCount == 0` ⇒ `AF_INGEST_FAILED`.
- Hàm cũ `deterministicCheckRowOffsets` (`taskpane.js:322`) **giữ nguyên** cho đường PQ/Codex-advice; viết hàm mới cho luồng.

#### Payload gửi lên

```jsonc
{ "kind": "workbook",
  "mode": "discover",                  // hoặc "compute"
  "payload": {
    "header": ["PostingDate","Amount","..."],
    "rows": [["2026-09-01","1200"], ...],   // discover: 20 dòng; compute: toàn bộ
    "totalRows": 42318,                     // LUÔN là số dòng thật
    "totalColumns": 11,
    "sampleOrdinals": [0, 1, 7, 93, 1044, ...],
    "name": "book.xlsx", "origin": "Workbook!GL_Sep",
    "sheet": "GL_Sep", "range": "A1:K42319", "table": true } }
```

#### Luật validate ở server (bắt buộc, thêm mới)

| Điều kiện | Sai ⇒ |
|---|---|
| `mode ∈ {"discover","compute"}` | `INVALID_REQUEST` |
| `sampleOrdinals` là số nguyên, tăng dần, không trùng, trong `[0,totalRows)` | `AF_INGEST_FAILED` |
| `discover`: `len(rows) == len(sampleOrdinals)` và `len(rows) <= 20` | `AF_INGEST_FAILED` |
| `compute`: `len(rows) == totalRows` (giữ luật C6 cũ) | `AF_INGEST_FAILED` |
| Mọi dòng: `len(row) == len(header)` | `AF_INGEST_FAILED` |
| `mode:"discover"` ⇒ **không** được dùng để freeze | `AF_SAMPLE_ONLY` (mới) |

Thay `add_open_workbook` bằng hàm mới `add_workbook_selection(payload)` (giữ `add_open_workbook` cũ nguyên vẹn cho caller khác). Hàm mới ghi thêm vào raw table: `"mode"`, `"sampleOrdinals"`, `"totalRows"`.

**Artifact phải bind `mode`.** `snapshotHash` của chế độ discover khác compute (vì `tables[]` khác `rowCount`). Điều đó là **đúng** và là cơ chế bảo vệ: freeze kiểm `stage == compute`.

#### Đường file/thư mục (chốt E)

| Nguồn | Cách |
|---|---|
| Workbook đang mở | Office.js full read (§6.2 doc v1.x), gửi payload |
| File `.xlsx` / `.csv` khác | **Đường dẫn tuyệt đối** do người dùng gõ; server đọc đĩa. Phải đã Save |
| Thư mục | Đường dẫn tuyệt đối + pattern (mặc định `*.csv`) |

Giao diện phải nói rõ: *"File phải đã được Save. Nếu đang mở mà chưa Save, bản trên đĩa là bản cũ."*

#### UI (card 02)

Giữ theo §5.2 doc v1.x. Thêm:
- `flow-mode-badge`: `MẪU 20 dòng` / `TOÀN BỘ`
- `flow-sample-info`: "20/42.318 dòng · dòng: 0, 1, 7, 93, …"
- Nút **Nạp 20 dòng để hiểu** và **Đọc toàn bộ để tính** là **hai nút riêng**, không gộp

#### Test

| ID | Kiểm |
|---|---|
| `test_discover_sample_is_deterministic_per_content` | cùng bảng → cùng `snapshotHash` và cùng `sampleOrdinals`; đổi 1 byte cuối → khác |
| `test_sample_ordinals_are_validated` | ordinals ngoài biên / trùng / không tăng dần / sai độ dài ⇒ `AF_INGEST_FAILED` |
| `test_discover_snapshot_cannot_freeze` | freeze từ snapshot discover ⇒ `AF_SAMPLE_ONLY` |
| `test_compute_requires_full_rows` | `len(rows) != totalRows` ⇒ `AF_INGEST_FAILED` |

### 4.2 Bước 2 · Understand → điểm chưa rõ

**Dùng lại WL2 nguyên.** `build_understand(raw_tables, snapshot)` trả roles/relationships/assumptions/warnings — tất định.

Ghi chú tích hợp v2 (30/10/2026): WL2 v1 đòi một đồ thị fact/lookup với ít nhất hai bảng đích. Nếu chỉ thiếu bằng chứng cho đồ thị đó (ví dụ một bảng đơn), store v2 giữ `roles: []`, tái dùng kiểm binding, quan hệ và evidence hiện có, rồi hỏi người dùng về vai trò; không tự gán fact/dimension. Các lỗi hash, schema hoặc binding khác vẫn bị chặn. Không sửa hành vi hay guard của engine WL2 v1.

Phần **mới** là biến chúng thành **câu hỏi cho người dùng**. Thiết kế:

| Nguồn | Sinh câu hỏi gì |
|---|---|
| `warnings[]` (AF_MISSING_DATA…) | "Cột X có phải số tiền? Đơn vị?" |
| `relationships[]` với `status:"needs_confirm"` hoặc `fanOutRisk:"high"` | "Nối A↔B theo khoá này? (fan-out cao, sẽ nhân dòng)" |
| `roles[]` confidence thấp | "Bảng X là fact hay dimension?" |
| `columns[].nullRate` cao | "Cột X trống 42% — bỏ qua hay coi là 0?" |
| `assumptions[]` | "Giả định: … Đúng không?" |

Trả về `questions[]` dạng:

```jsonc
{ "id": "q_1", "topic": "amount", "question": "Cột Amount có phải số tiền?",
  "whyItMatters": "Ảnh hưởng mọi tổng và đối soát.",
  "kind": "single_choice", "options": ["Số tiền VND", "Số tiền ngoại tệ", "Không phải số tiền"],
  "evidence": [{ "kind": "stats", "value": "nullRate=0.00, distinctRatio=0.83" }] }
```

Luật: **câu hỏi sinh tất định từ dữ liệu**, không từ AI. Nếu AI có đề xuất ở P7 thì đề xuất đó là *thêm vào danh sách*, đánh dấu `source:"llm"`.

#### HTTP

`POST /api/assistant/understand` → trả `understand` + `questions[]` + `briefRequirements` (bỏ — không còn `_period`).

#### Test

| ID | Kiểm |
|---|---|
| `test_questions_are_deterministic_and_evidenced` | cùng snapshot → cùng câu hỏi; mỗi câu có `evidence` |
| `test_high_fanout_produces_confirmation_question` | nối fan-out cao ⇒ có câu hỏi `needs_confirm` |
| `test_high_null_rate_produces_question` | nullRate > ngưỡng ⇒ có câu hỏi |

### 4.3 Bước 3 · Codex sinh kế hoạch (WL3)

**Đây là pha mới lớn nhất.** Codex nhận mẫu + câu hỏi + câu trả lời, trả về **2 kế hoạch** (A và B).

#### Ai gọi Codex

Dùng lại `adapters/codex/typed.py` (`CodexTypedRunner`, đã có, đã bound + validate). Thêm hàm mới `draft_branch_plans(...)` trong adapter, **không** sửa `CodexTypedRunner` hiện có.

#### Hợp đồng gửi Codex (bounded)

```jsonc
{ "goal": "<prompt người dùng>",
  "sources": [  // chỉ schema + thống kê, không phải toàn bộ dữ liệu
    { "sourceId":"src_…", "kind":"excelTable", "name":"GL_Actuals_2026-09",
      "rowCount":42318,
      "columns":[{ "name":"PostingDate","type":"text","nullRate":0.0,
                   "distinctCount":30,"sample":["2026-09-01","2026-09-02"] }] } ],
  "sampleRows": [ ["2026-09-01","1200","VND",...], ... ],   // 20 dòng, đã ẩn danh? xem 4.3.1
  "sampleOrdinals": [ {"sourceId":"src_…", "ordinal":0}, ... ],
  "understand": { "roles":[…], "relationships":[…], "assumptions":[…], "warnings":[…] },
  "questions": [ {"id":"q_1","topic":"amount","question":"Cột Amount có phải số tiền?","options":["Số tiền VND","Khác"]} ],
  "answers": [ {"questionId":"q_1","answer":"Số tiền VND"} ],
  "catalog": { "operations": [ 15 tên ], "expressionKinds": [ 10 tên ] },
  "limits": { "maxSteps": 20, "maxColumns": 256 } }
```

#### 4.3.1 Disclosure (bắt buộc, không được bỏ)

Trước khi gửi, UI phải hiện rõ và người dùng phải bấm đồng ý:

> *"Sẽ gửi tới Codex: đề bài của bạn, 20 dòng dữ liệu mẫu (đã chọn tất định), tên cột và thống kê mô tả. Không gửi toàn bộ workbook, không gửi đường dẫn tệp."*

(AGENTS.md: chỉ gửi prompt + mẫu có giới hạn sau hành động của người dùng; phải hiện disclosure.)

#### Hợp đồng Codex trả về

```jsonc
{ "summary": "…",
  "questions": ["…"],                                  // điểm chưa rõ bổ sung
  "assumptions": [ {"statement":"…","risk":"low|medium|high"} ],
  "branches": [
    { "id":"A", "label":"Net = Gross − Returns − Discount", "rationale":"…", "maxFanOut":"1",
      "controlTotal": { "resultColumn":"netRevenue", "sourceColumn":"Amount",
                        "aggregation":"sum", "afterFilters":true },
      "plan": { "summary":"…", "questions":[], "assumptions":[], "warnings":[],
                "steps":[ … Typed draft hiện hành … ], "finalOutputRef":"…" } },
    { "id":"B", "label":"…", "controlTotal":{…}, "plan":{…} } ] }
```

#### Validate — **engine quyết định, không phải Codex**

Thứ tự bắt buộc, dừng ở lỗi đầu tiên:

1. Shape: `branches` đúng 2 phần tử, id `A`/`B`, `summary` không rỗng.
2. `plan` qua `_validate_draft_shape(...)` (từ `powerquery/typed/validation.py`).
3. `_normalize_steps(...)` với **source catalog thật** (`build_source_catalog(workbook)`).
4. Mọi cột tham chiếu phải tồn tại; kiểu phải khớp.
5. `len(steps) <= 20`; tổng cột ra `<= 256`.
6. `controlTotal.resultColumn` phải **có trong output schema** của plan; `sourceColumn` phải có trong input.
7. Không bước nào chứa giá trị literal "đã tính sẵn" cho một measure tổng (chặn Codex gài số).

Sai ⇒ `AF_PLAN_INVALID` + `path` chỉ đúng bước/field sai. **Không** tự sửa plan của Codex.

Chi tiết tích hợp 31/10/2026: giới hạn 20 dòng là tổng trên mọi nguồn; ordinal gửi planner kèm `sourceId` để không nhầm nguồn. `questions[]` gửi định nghĩa câu hỏi đã hiển thị, không gửi evidence/raw sample bổ sung; câu trả lời phải thuộc ID đã biết. Catalog hiện có nhận tối đa 200 cột nguồn (không cắt âm thầm), còn output tối đa 256 cột. Adapter dựng catalog bảng logic trong bộ nhớ cho CSV/thư mục/vùng Excel và giữ nguồn gốc thật ở WL1; M xuất từ catalog này cần các bảng/alias tương ứng, không tự đọc tệp CSV hay vùng gốc.

> **Import private:** `powerquery/typed/store.py:77-88` đã import `_validate_draft_shape`, `_normalize_steps`, `build_source_catalog` trực tiếp. Đi theo tiền lệ đó; **không** đổi tên thành public (sẽ phải sửa 1055 dòng store).

#### Test

| ID | Kiểm |
|---|---|
| `test_codex_plan_is_revalidated_and_rejects_unknown_column` | plan tham chiếu cột không có ⇒ `AF_PLAN_INVALID` |
| `test_codex_plan_rejects_unsupported_operation` | operation ngoài 15 ⇒ `PQV2_OPERATION_UNSUPPORTED` |
| `test_codex_plan_rejects_hardcoded_totals` | literal cho measure tổng ⇒ `AF_PLAN_INVALID` |
| `test_two_branches_required` | 1 hoặc 3 nhánh ⇒ `AF_PLAN_INVALID` |
| `test_disclosure_required_before_codex` | thiếu `acknowledged:true` ⇒ `AF_DISCLOSURE_REQUIRED` |

### 4.4 Bước 4 · Đọc toàn bộ + tính A/B

Sau khi Codex trả plan, **chưa** phải lúc chốt. Cần số thật của cả hai nhánh.

```text
1. UI: "Đọc toàn bộ để tính" → Office.js đọc full → /ingest mode=compute
2. Server: build snapshot compute (snapshotHash mới)
3. Validate lại 2 plan với catalog thật của snapshot compute
4. Chạy executor cho A và B trên full data
5. build_reconciliation cho A và B
6. Trả: 2 preview (kèm số) + delta giữa A và B
```

#### Tính chất bắt buộc

- Hai nhánh chạy trên **cùng một snapshot compute**.
- Mỗi nhánh có `previewHash` riêng, `reconcileHash` riêng.
- `delta` giữa A/B là **số engine tính**, không phải AI.
- Nếu một nhánh reconcile fail ⇒ nhánh đó **không được chọn** (khoá radio), nhưng nhánh kia vẫn chọn được.
- Nếu cả hai fail ⇒ dừng, chỉ đường quay lại bước 2/3.

#### Giới hạn hiệu năng (phải nêu trong UI)

- Executor chạy Python thuần trên `<= 100.000` dòng ⇒ A/B là 2 lần tính. Ghi thời gian thực tế vào response (`elapsedMs`) để người dùng thấy.
- Không cache kết quả A/B giữa hai lần gọi trừ khi `snapshotHash` + `planHash` giống hệt.

#### Test

| ID | Kiểm |
|---|---|
| `test_both_branches_run_on_same_snapshot` | 2 preview cùng `snapshotHash`; `previewHash` khác nhau |
| `test_failed_branch_cannot_be_chosen` | reconcile fail ⇒ chọn nhánh đó ⇒ `AF_RECONCILE_FAILED` |
| `test_ab_delta_is_engine_computed` | `delta` khớp hiệu số engine tính, không lấy từ response Codex |

### 4.5 Bước 5 · Chốt nhánh → Execution Spec (WL4)

**Dùng lại khung WL4.** `build_decisions(...)` + `build_spec(...)` vẫn đúng hình dạng, nhưng:

- `decisions[]` giờ chốt **nhánh** (`branch: "A"|"B"`) thay vì từng `SP-n` — hoặc giữ cả hai: `SP-n` cho policy, `branch` cho kế hoạch. **Chọn: giữ `SP-n`** để không phá shape, thêm `branchId`.
- `steps` trong Spec = **plan của nhánh đã chọn**, đã normalize. Không dùng `compile_steps`.
- `spec.fingerprint` bind `snapshotHash` + `decisionsHash` + `planHash`.

Lưu ý tích hợp đã kiểm trong code: validator WL4 v1 đóng theo Brief/SP và graph recipe; không gọi builder cũ rồi thay bước sau khi hash. V2 dùng builder/validator riêng trong `assistant_freeze.py`, giữ tên field/hash-chain tương ứng, bind nhánh Typed thật và không nới hàm v1. Metadata public chỉ chứa bước/schema an toàn và hash, không trả `plan.sources.sampleRows`.

Luật: **freeze chỉ khi** `snapshot.mode == "compute"` và mọi hard check của nhánh đã đạt. Nếu có tổng kiểm soát thì nhánh phải `passed:true`; nếu chỉ thiếu cơ sở tổng kiểm soát thì `passed` vẫn là `false`, cần acknowledgement tường minh và nhãn `unverified`. Không được dùng acknowledgement để vượt lỗi hình dạng, lệch tổng đã kiểm được hoặc fan-out vượt giới hạn.

#### Test

| ID | Kiểm |
|---|---|
| `test_freeze_requires_compute_snapshot` | discover ⇒ `AF_SAMPLE_ONLY` |
| `test_freeze_requires_chosen_branch_passed` | nhánh fail ⇒ `AF_RECONCILE_FAILED` |
| `test_spec_binds_plan_hash` | đổi 1 bước trong plan ⇒ `spec.fingerprint` đổi |

### 4.6 Bước 6 · Duyệt + Ghi (WL6)

**Bỏ `assistant_apply.apply_result`.** Dùng lại:

| Thành phần | Dùng cho |
|---|---|
| `assistant_approval` | tái sử dụng registry capability dùng một lần, bind `specFingerprint` + `previewHash`; thêm entry point v2 riêng để không nới bộ kiểm recipe của v1 |
| `applyPQValuesToOpenWorkbook` (taskpane.js:3581) | ghi values-only vào worksheet mới qua Office.js |
| `verify_values_only` (assistant_apply.py:137) | kiểm package — **giữ**, hàm này generic |

Luồng ghi:

```text
1. UI lấy result table của nhánh đã chốt (từ bước 4, hoặc tính lại nếu stale)
2. UI: exportWorkbookBase64() → gửi kèm /apply
3. Server: kiểm lại nguồn/approval/package/đích → consume → trả kết quả đã chốt; đây mới là bàn giao, chưa phải đã ghi workbook
4. Trả result.columns/rows + marker + labels + resultDigest
5. UI: tạo worksheet mới (tên do server trả, KHÔNG cho người dùng đặt), ghi values + marker
6. UI: đọc lại toàn bộ vùng kết quả và marker, so digest. Lệch ⇒ báo partial, KHÔNG tuyên bố thành công. Khớp thì gửi receipt ràng buộc spec/preview/result digest qua cùng `/apply`; chỉ receipt hợp lệ mới chuyển stage `applied` và cho phép tạo Record
7. Không save, không ghi sheet nguồn
```

Giữ nguyên hiệu lực **C2** (approval là object process-affine): store giữ strong ref, client không cầm approval.

Không phát hành lại quyền ghi sau khi capability đã consumed. Lỗi mạng hoặc read-back sau bàn giao giữ trạng thái partial/unknown và không tự retry. Trước khi consume, kiểm fingerprint file/thư mục hiện tại và đối chiếu lại toàn bộ nguồn workbook đã chọn; thay đổi nguồn hoặc workbook yêu cầu tính/duyệt lại. Khi ghi chuỗi bằng Office.js, đặt định dạng Text trước khi gán `.values`, để header/nội dung bắt đầu bằng `=` vẫn là giá trị literal; không phát sinh formula.

Writer v2 giữ chuỗi số Decimal ở dạng Text để bảo toàn chữ số và đọc lại chính xác; UI phải nêu rõ **"Số Decimal được giữ dạng văn bản để bảo toàn độ chính xác."** Không âm thầm ép sang binary Number. Đây là giới hạn sử dụng kết quả trong Excel: các ô số dạng Text cần chuyển đổi có chủ đích trước khi dùng các hàm Excel yêu cầu ô numeric. Boolean và giá trị integer JSON thực có thể giữ kiểu gốc.

Kiểm capability trước bàn giao/consume: xác minh values-only sau ghi dùng `getSpecialCellsOrNullObject`, thuộc ExcelApi 1.9 theo [Microsoft Learn](https://learn.microsoft.com/en-us/javascript/api/excel/excel.range?view=office-js). Host thiếu API này bị chặn trước khi ghi.

### 4.7 Bước 7 · Record + Custom XML (WL7)

**Dùng lại khung `assistant_record`**, bỏ phần `_FIN` của `compute_delta`. Validator/builder v1 thực tế còn gắn recipe và reconciliation v1; v2 dùng builder riêng, `schemaVersion:"2.0"`, giữ thứ tự/tên field `hashBasis` của Record v1. Executor metadata đặt trong `reconciliations[0].engine` nên được hash cùng Record. Không tạo Brief/recipe giả hoặc nới validator v1 để tái sử dụng.

Record giữ đầy đủ bước Typed đã chốt, gồm parameters/inputs/outputContract để kiểm lại thuật toán; không thay bằng hash parameters đơn thuần. Projection đối soát bổ sung `specFingerprint`, `finalOutputStepId` và schema nguồn an toàn để truy vết, được hash cùng Record; `reconcileHash` gốc vẫn kiểm riêng theo basis D đóng. Không đưa `plan.sources.sampleRows`, raw cell hoặc đường dẫn vào Record.

Record đã tạo là lịch sử bất biến. Gọi lại `/record` có thể cập nhật `staleCheck` tạm thời theo nguồn hiện tại, không tự sửa Record/hash hoặc XML đã lưu. Mức khớp tại lần đọc đầy đủ gần nhất không phải cam kết workbook liên tục được kiểm tra. Đọc metadata XML là thao tác Office cục bộ độc lập session/coordinator; ghi metadata mới vẫn cần Record/Spec và workbook đang được ràng buộc, dùng hash CAS đã được pane quan sát.

Record lưu **Custom XML** (chốt F):

```
namespace: urn:local-data-copilot:assistant-record:v1
node:      {schemaVersion:"1.0", id:"rec_…", hash:"sha256:…", recordHash:"sha256:…",
            snapshot:"sha256:…", spec:"sha256:…", branch:"A", createdAt:"…",
            labels:["assumed","unverified"]}
```

Luật:

| Luật | Chi tiết |
|---|---|
| Không lưu raw cell | Record engine đã từ chối binary/đường dẫn tuyệt đối; chỉ lưu hash + metadata |
| CAS | Đọc XML hiện có → so `hash` → ghi đè **chỉ khi** khớp, nếu khác ⇒ `PQPC_HISTORY_CONFLICT` |
| Read-back | Sau khi ghi, đọc lại, so `hash`; lệch ⇒ `AF_WRITE_PARTIAL` |
| Không Save | Ghi Custom XML **không** gọi `save()`; trạng thái "chưa lưu" được hiện rõ |
| Mở lại | Khi mở pane: đọc XML → verify hash → nếu nguồn đổi ⇒ `stale` banner |
| Giới hạn | 1 record/namespace/lần; dung lượng `<= 32 KB`; vượt ⇒ từ chối, không cắt |

Namespace **không** dùng chung với `urn:local-data-copilot:pq-problem-chain:v1`.

`node.hash` là SHA-256 của canonical JSON chứa **mọi field còn lại** trong node metadata cố định trên; helper phải tính hash thật bằng WebCrypto và từ chối field lạ. `node.recordHash` chỉ tham chiếu tới hash của Decision Record đầy đủ, không thể xác minh lại toàn bộ Record từ metadata. CAS dùng `node.hash`, tách biệt với `recordHash` của session. XML chứa đúng một payload metadata canonical đã kiểm, không chứa raw cell. Khi mở lại chỉ khôi phục metadata, hiển thị mức này rõ ràng; nguồn chưa được nạp lại có độ mới `unknown`, chỉ so snapshot sau khi nạp đủ nguồn hiện tại mới kết luận `stale` hay khớp. Bản Record đầy đủ để tải xuống giữ executor/knownDifferences.

#### Test

| ID | Kiểm |
|---|---|
| `test_record_custom_xml_roundtrip_hash_matches` | ghi → đọc lại → `record.hash` khớp |
| `test_record_cas_rejects_conflicting_write` | ghi 2 lần với hash cũ ⇒ conflict |
| `test_record_xml_has_no_raw_cells_or_paths` | quét XML: không có mảng cell, không có `C:\` |
| `test_record_marks_stale_after_source_change` | đổi CSV nguồn ⇒ mở lại thấy `stale` |

---

## 5. Hợp đồng HTTP (chỉ phần khác v1.x)

Giữ nguyên mọi thứ ở §4 của doc v1.x: token, `state()` slot, body limit, wire shape lỗi, `_error` có `extra`.

| Route | Thay đổi |
|---|---|
| `/api/assistant/session` | không đổi |
| `/api/assistant/ingest` | **thêm `mode`**, validate `sampleOrdinals`; trả `sampleInfo`. `expectedPlanningHash` tùy chọn ràng buộc kế hoạch hiện tại khi chuyển discover → compute; thiếu thì bỏ kế hoạch cũ, sai thì `AF_SPEC_STALE` |
| `/api/assistant/understand` | trả **`questions[]`** (mới), bỏ `briefRequirements` |
| `/api/assistant/plan-draft` ★ | **mới** — Codex sinh 2 nhánh; nhận `prompt`, `answers[]`, `acknowledged:true`; trả `planningHash` ràng buộc đề bài, câu trả lời và hai kế hoạch |
| `/api/assistant/branches` ★ | **mới** — chạy A/B trên snapshot, trả 2 preview + reconcile + delta |
| `/api/assistant/freeze` ★ | thay `/decisions` + `/spec`; chọn `branch`, trả `spec` |
| `/api/assistant/approvals` | không đổi |
| `/api/assistant/apply` | trả `result` + `marker` + `digest`; **không** trả `apply.workbook` bytes |
| `/api/assistant/record` ★ | **mới** — ghi Custom XML, trả `recordId`/`hash` |
| `/api/assistant/state` | thêm `mode`, `chosenBranch`, `recordHash` |
| `/api/assistant/reset` | không đổi |

Slot: toàn bộ `/api/assistant/*` dùng `state()`. **`/plan-draft` thêm vào `CODEX_JOB_PATHS`** (là lời gọi Codex thật). `/branches` và `/apply` **không** vào `EXCEL_JOB_PATHS` — executor là Python, không COM; riêng bước UI ghi vào Excel thì Office.js tự lo.

Stage `handoff` nằm giữa `approved` và `applied`: `/apply` lần đầu đã consume quyền ghi nhưng chưa chứng minh workbook được ghi. Cùng route nhận receipt ràng buộc spec/preview/result digest, đích, marker và kích thước sau khi UI đọc lại toàn bộ; receipt hợp lệ mới chuyển `applied`. Receipt lỗi chuyển `partial`. Cả `handoff` và `partial` không cho duyệt/phát hành quyền ghi lại.

Client phải gửi revision mà người dùng thực sự đang xem: `/freeze` yêu cầu `expectedPlanningHash` + `expectedPreviewHash` + `expectedResultDigest`; `/approvals` và `/apply` bàn giao yêu cầu `expectedSpecFingerprint` + `expectedPreviewHash` + `expectedResultDigest`. So sánh trước issue/consume; không lấy revision mới nhất trong server để duyệt thay một pane đang xem revision cũ.

---

## 6. Executor `powerquery/typed_local/` (mới)

### 6.1 Quyết định G — **đã chốt**: executor Python, không chạy M qua Excel

| | Python thuần ✅ **chốt** | Chạy M qua Excel COM (không chọn) |
|---|---|---|
| Tốc độ A/B | nhanh, 2 lần tính trong 1 process | **chậm** — mỗi preview một lần mở Excel, timeout 180 s |
| Test trong gate | ✅ chạy được trong `run_checks.py fast` | ❌ phải vào `runtime` gate, cần Excel |
| Nguồn file/thư mục | ✅ chạy được, không cần workbook | ❌ cần workbook + COM |
| Số thực | `Decimal` chính xác | phụ thuộc kiểu PQ |
| Khớp ngữ nghĩa PQ | **phải tự chịu trách nhiệm** (rủi ro cao) | đúng mặc định |

**Đã chốt Python.** Đây không còn là câu hỏi mở; rủi ro lệch ngữ nghĩa là **rủi ro phải quản**, không phải lựa chọn để cân lại. Cách quản ở §6.5.

**Ranh giới trách nhiệm phải hiểu đúng:** nguồn sự thật là **plan + catalog**, không phải Power Query. Executor đảm bảo *plan chạy đúng như plan mô tả, tất định*. Nếu sau này người dùng xuất M ra Power Query và thấy khác, đó là lỗi **của chúng ta** (executor sai) hoặc **khác biệt ngữ nghĩa đã ghi nhận** (§6.5) — không được nói "PQ sai".

### 6.2 Hợp đồng

```python
# powerquery/typed_local/__init__.py
def execute_plan(plan: dict, tables: list[dict]) -> dict:
    """Trả {"columns": [{"name","type"}], "rows": [[cell]], "rowCount": int,
             "elapsedMs": int}. Pure Python, tất định, không Excel."""
```

- `tables`: đã validate bởi `_normalize_steps` + `build_source_catalog`.
- Số: `Decimal` cho tới khi ra JSON (string).
- Không bao giờ đọc đĩa, không mạng, không thời gian hệ thống (thời gian do caller đo).
- Giới hạn: `MAX_ROWS=100_000`, `MAX_COLUMNS=256`; vượt ⇒ `AF_EXECUTOR_LIMIT`.
- Sắp xếp tất định: `groupRows`/`aggregateRows` sắp theo khoá nhóm tăng dần. Theo quyết định người dùng ngày 30/10/2026, `mergeTables` giữ đủ 6 `joinKind` của catalog (`inner`, `leftOuter`, `rightOuter`, `fullOuter`, `leftAnti`, `rightAnti`) và cột bảng lồng theo Typed; `expandTableColumn` mới mở rộng các dòng. Không đổi catalog hoặc âm thầm đổi kiểu join.

### 6.3 Phủ 15 thao tác

| Thao tác | Cách làm |
|---|---|
| `source.workbookTable` / `source.usedRange` | chọn bảng theo tên |
| `filterRows` | lọc bằng `_normalize_expression` đã chuẩn hoá |
| `selectColumns` / `removeColumns` / `renameColumns` | cắt/đổi tên theo schema |
| `changeTypes` | ép kiểu có kiểm (`text/integer/number/date/boolean`) |
| `addColumn` | biểu thức trên từng dòng |
| `sortRows` | sort ổn định, nhiều khoá |
| `distinctRows` | theo tập cột, giữ dòng đầu |
| `groupRows` / `aggregateRows` | nhóm + tổng hợp (`sum/count/min/max/average`) dùng `Decimal` |
| `appendTables` | nối theo schema chung, thiếu cột ⇒ null |
| `mergeTables` | 6 kiểu join theo catalog, giữ bảng lồng; **đếm fan-out** khi mở rộng và trả metrics trong kết quả để reconcile dùng |
| `expandTableColumn` | làm phẳng cột bảng lồng |

### 6.4 Test

| ID | Kiểm |
|---|---|
| `test_execute_plan_smoke_all_15_operations` | mỗi thao tác một case nhỏ, có kỳ vọng viết tay |
| `test_executor_is_deterministic` | chạy 2 lần cùng input ⇒ cùng output bytes |
| `test_executor_money_uses_decimal` | tổng tiền không có sai số float |
| `test_merge_reports_fan_out` | join gây nhân dòng ⇒ `fanOut` trong kết quả |
| `test_executor_enforces_limits` | >100k dòng ⇒ `AF_EXECUTOR_LIMIT` |

### 6.5 Quản rủi ro lệch ngữ nghĩa so với Power Query (vì đã chốt Python)

Đây là **chi phí thật** của quyết định G. Phải làm đủ 4 tầng, không được cắt.

#### Tầng 1 — Kỳ vọng viết tay (`fast` gate, bắt buộc)

Mỗi thao tác trong 15 có một case với kết quả **tính tay**, viết trong test, không suy ra từ code. Mẫu:

```python
# filterRows: kỳ vọng viết tay, không đọc lại từ executor
plan = {"steps": [{"id":"s1","operationType":"table.filterRows",
                   "parameters":{"source":"t","condition":{...}}}]}
self.assertEqual(execute_plan(plan, TABLES)["rows"],
                 [["2026-09-01","1200"], ["2026-09-03","900"]])
```

Với 15 thao tác × 2–3 biên (null, rỗng, trùng khoá) ⇒ ~40 case, không cần Excel.

#### Tầng 2 — Bảng khác biệt ngữ nghĩa **đã ghi nhận** (bắt buộc)

Có những chỗ Python và Power Query **cố ý** khác nhau. Ghi thành bảng, mỗi dòng một test khoá hành vi của chúng ta:

| Chủ đề | Power Query | Executor (chốt) | Vì sao |
|---|---|---|---|
| `sum` trên cột có null | bỏ qua null | **bỏ qua null** (giống) | |
| `average` mẫu rỗng | `null` | `null`, **không** `0` | tránh số giả |
| `average` chia 0 | `null`/lỗi | `null` + warning trong reconcile | |
| `min/max` toàn null | `null` | `null` | |
| so sánh text | theo collation, không phân biệt hoa thường ở một số locale | **phân biệt hoa thường, byte-wise** | tất định, không phụ thuộc locale |
| ép `date` từ text lạ | `null`/error | **`null`** + warning | |
| `distinctRows` giữ dòng nào | không đảm bảo | **giữ dòng đầu tiên** (ổn định) | tất định |
| `mergeTables` thứ tự ra | không đảm bảo | **theo thứ tự đầu vào**, phần không khớp của bảng phải theo thứ tự bảng phải; giữ bảng lồng cho tới bước expand | tất định |
| `sortRows` sort ổn định | không đảm bảo | **ổn định** | tất định |
| số thực | `number` (binary float) | **`Decimal`** tới khi xuất | không sai số tiền |

Bảng này phải **hiện trong tài liệu cho người dùng** (mục "Giới hạn" của runbook), không chỉ nằm trong code. Người dùng cần biết trước khi tin số.

#### Tầng 3 — Đối chiếu M ở `runtime` gate (opt-in, có Excel)

Test **không** chạy trong `fast`; chạy khi có Excel. Mục đích: bắt trôi ngữ nghĩa theo thời gian.

```python
# tests/runtime/test_typed_local_parity.py
@unittest.skipUnless(shutil.which("powershell.exe"), "no Excel")
def test_python_executor_matches_excel_m_for_same_plan(self):
    """Cùng plan → executor Python và M trong Excel phải ra CÙNG bảng."""
    plan = PLAN_COVERING_ALL_15_OPS
    python_rows = execute_plan(plan, TABLES)["rows"]
    m_rows = run_m_in_excel(compile_m(plan), TABLES)     # dùng lại PowerShellExcelRunner
    self.assertEqual(m_rows, python_rows)
```

- Plan dùng cho test này phủ **cả 15 thao tác** trong một pipeline.
- Nếu lệch: **hoặc** sửa executor, **hoặc** thêm dòng vào bảng Tầng 2 với lý do. Không được sửa test cho xanh.
- Chạy lại khi: thêm thao tác, đổi ngữ nghĩa, hoặc trước release.

#### Tầng 4 — Ghi nhận trong sản phẩm

Response `/branches` và record mang theo:

```jsonc
"engine": { "executor": "typed_local", "version": "1.0",
            "parityChecked": "runtime",        // hoặc "none" nếu chưa chạy
            "knownDifferences": ["text-compare-case-sensitive", "decimal-money"] }
```

Nếu `parityChecked == "none"` thì UI phải hiện một dòng: *"Bản này tính bằng engine nội bộ, chưa đối chiếu với Power Query trên máy bạn."* — để người dùng biết mức tin cậy.

#### Việc **không** được làm

- Không bán "khớp 100% với Power Query". Bán "tất định, kiểm chứng được, khác biệt có ghi nhận".
- Không thêm thao tác thứ 16 mà chưa có case Tầng 1 + dòng Tầng 2 + chạy Tầng 3.

---

## 7. Reconcile không còn recipe (việc khó nhất)

### 7.1 Vì sao khó

Bản v1.x kiểm `rowsIn == 42`, `rowsOut == 23`, `controlTotal == tổng GL`, `Op + FX = Total` — **tất cả viết cứng cho P&L**. Với kế hoạch do Codex sinh, không có gì để so cứng.

### 7.2 Thiết kế: reconcile theo **hợp đồng do plan tự khai**

Mỗi nhánh phải khai `controlTotal` (§4.3). Reconcile kiểm 4 tầng:

| Tầng | Kiểm gì | Fail ⇒ |
|---|---|---|
| **R1 · hình dạng** | `rowsOut == len(rows)`, `colsOut == len(columns)`, không cột trùng tên, không dòng rỗng | `AF_RECONCILE_FAILED` |
| **R2 · control total** | `sum(result[controlTotal.resultColumn])` so `sum(source[sourceColumn])` sau filter, sai số `<= tolerance` | `AF_RECONCILE_FAILED` |
| **R3 · fan-out** | kiểm mọi phần tử `fanOut.joins[]`: `rowsAfter <= rowsBefore * maxFanOut`. `maxFanOut` là metadata mỗi nhánh, decimal string hữu hạn trong `[1,100000]`, mặc định an toàn `"1"`; không thêm tham số vào catalog Typed | `AF_FANOUT_RISK` |
| **R4 · A/B** | `A.total - B.total == delta` (delta engine tính) | `AF_RECONCILE_FAILED` |

Nếu `controlTotal` **không khai được** (plan không có cột nguồn tương ứng):

- reconcile ghi `controlTotalApplicable: false` — **hiện lên UI**, không ẩn;
- approval yêu cầu **acknowledgement tường minh** `"Tôi hiểu nhánh này không có đối soát tổng kiểm soát"`;
- record gắn nhãn `unverified` và ghi rõ lý do.

Hợp đồng phân biệt xác minh và quyền chọn: `passed:false` khi R2 không áp dụng; `hardChecksPassed:true`, `acknowledgementRequired:true` và `selectable:true` chỉ khi các kiểm tra còn lại đều đạt. Freeze/approval xử lý acknowledgement riêng, không đổi `passed` thành `true`. Các pipeline chưa thể truy vết duy nhất tổng nguồn sau filter cũng phải nêu R2 không áp dụng, không lấy tổng kết quả làm tổng nguồn. Hash ràng buộc cả hợp đồng đối soát (`controlTotal`, `maxFanOut`); cache tính số không được tái sử dụng đối soát dưới policy khác.

Delta A/B chỉ áp dụng khi cả hai nhánh khai được cùng basis nguồn/measure; tên cột kết quả giống nhau không chứng minh tiền và số lượng cùng đơn vị. Thiếu hoặc khác basis thì `delta.applicable:false`, nêu lý do và R4 chưa áp dụng; không tự tạo tổng hoặc chặn thay các kiểm tra riêng của nhánh.

Đây là điểm trung thực then chốt: **không được giả vờ đã reconcile** khi không có cơ sở.

### 7.3 Test

| ID | Kiểm |
|---|---|
| `test_control_total_matches_source_after_filter` | đúng ⇒ pass; lệch ⇒ `AF_RECONCILE_FAILED` |
| `test_missing_control_total_requires_acknowledgement` | không khai ⇒ approve bị chặn tới khi ack |
| `test_fanout_over_declared_limit_blocks` | join vượt ⇒ `AF_FANOUT_RISK` |
| `test_ab_identity_holds` | `A.total - B.total == delta` |

---

## 8. UI — 8 card

Giữ nguyên toàn bộ convention và danh sách id ở §5.2 doc v1.x, **trừ các thay đổi sau**:

| Card | Thay đổi so với doc v1.x |
|---|---|
| 01 Kết nối workbook | không đổi |
| 02 Nguồn | thêm `flow-mode-badge`, `flow-sample-info`; **hai nút** "Nạp 20 dòng" / "Đọc toàn bộ" |
| 03 Đề bài + câu hỏi | thêm `flow-questions` (render `questions[]`), `flow-answers`; **disclosure checkbox** trước khi gọi Codex |
| 04 Cách hiểu | không đổi |
| 05 Kế hoạch A/B | **card mới**: `flow-branch-A`, `flow-branch-B` (mỗi cái: label, rationale, bảng preview có số, banner reconcile), `flow-branch-delta`, radio chọn nhánh |
| 06 Execution Spec | sửa: hiện **plan của nhánh đã chọn** (không phải 14 step FIN) |
| 07 Preview + Reconcile | giữ; thêm dòng `controlTotalApplicable` + ack khi false |
| 08 Kết quả + Record | thêm `flow-record-persist` ("Đã lưu vào workbook" / "Chưa lưu") |

Thêm một trạng thái `data-state` mới: `branching` (đang tính A/B).

---

## 9. Thang pha — từng bước, có lệnh kiểm

### P0 · Mở khoá

| Việc | File | Acceptance |
|---|---|---|
| P0-1 Guard cardinality (gate đang đỏ) | `assistant_brief.py` | `test_invalid_relationship_cardinality_is_rejected_before_brief` xanh |
| P0-2 Sửa Total Row trong `readWorkbook()` | `taskpane.js` + fake host | bảng có totals row ⇒ `totalRows` đúng |

```powershell
py tools/run_checks.py fast          # phải xanh
```

### P1 · Hiểu dữ liệu

Làm: `assistant_session.py` (chỉ WL1+WL2), `endpoints/assistant.py` (`session`/`ingest`/`understand`/`state`/`reset`), `add_workbook_selection`, `questions[]`, UI card 01/02/03/04.

```powershell
py tools/run_checks.py fast
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter understand
```

Quan sát: nạp 7 CSV fixture → thấy 7 bảng + navigator + "Cách hiểu" + ≥3 câu hỏi.

### P2 · Codex sinh kế hoạch

Làm: `/plan-draft`, `draft_branch_plans` trong adapter, validate 7 bước (§4.3), UI card 05 (chưa có số) + disclosure.

```powershell
$env:PQPC_LIVE_CODEX = "1"
py tools/run_checks.py codex    # cả Assistant plan và Problem Chain; request thật, nguồn tổng hợp
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter plan
```

Quan sát: thấy 2 nhánh A/B có label + danh sách bước; gửi plan sai ⇒ bị từ chối với `path` đúng.

### P3 · Tính số + A/B

Làm: `powerquery/typed_local/`, `reconcile` mới, `/branches`, UI card 05 hiện số.

```powershell
py -m unittest tests.unit.test_typed_local -v
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter branches
```

Quan sát: hai bảng có số + delta + banner reconcile cho từng nhánh.

### P4 · Chốt + thi hành

Làm: `/freeze`, `/approvals`, `/apply` (writer mới), UI card 06/07.

```powershell
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter apply
```

Quan sát: sheet kết quả xuất hiện, đúng số của nhánh đã chọn, `workbookSaved:false`.

### P5 · Record + Custom XML

Làm: `/record`, Custom XML read/write/CAS, UI card 08.

```powershell
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1     # 11 route; thêm ingest compute và receipt /apply
```

Quan sát: đóng/mở lại pane → record vẫn còn, hash khớp.

Smoke backend dùng workbook tổng hợp và receipt mô phỏng; không mở/ghi Excel và không phải bằng chứng Office.js. Luồng đầy đủ có 13 lời gọi POST: 11 route logic cộng lần ingest compute và receipt xác nhận read-back qua `/apply`.

### P6 · Hoàn thiện UI + tài liệu

Làm: 14 case JS, runbook, `ASSISTANT_TRACEABILITY.md`, `CURRENT_STATUS.md`, sửa `tools/excel_addin/README.md`.

```powershell
node tests/taskpane/taskpane_assistant_flow.js
py tools/run_checks.py fast
```

### P7 · Codex nhãn (tuỳ chọn, sau khi P6 xanh)

Nghĩa cột + định nghĩa + đề xuất câu hỏi bổ sung. Chỉ sinh nhãn/chữ; gắn `source:"llm"`.

---

## 10. Gate & test

| Gate | Nội dung | Ghi chú |
|---|---|---|
| `fast` | toàn bộ unit/contract/integration + 14 case JS + **~40 case executor (kỳ vọng viết tay)** | **không cần Excel, không cần Codex** — nhờ executor Python (chốt G) |
| `runtime` | Excel COM: apply vào workbook thật **+ đối chiếu parity executor ↔ M** (§6.5 tầng 3) | chỉ dùng cho WL6 và parity |
| `codex` | mọi module `tests.runtime.test_codex_*`, chỉ chạy khi `PQPC_LIVE_CODEX=1` | Assistant plan + Problem Chain; không chạy request Codex trong gate `runtime` |

**Điểm mạnh của chốt G:** `fast` gate phủ được tầng tính số — thứ mà đường Excel COM **không** kiểm được. Gate `runtime` vẫn cần, nhưng chỉ cho ghi workbook và parity, không còn là điều kiện để kiểm số học.

`parityChecked` trong response là `"runtime"` chỉ khi test tầng 3 đã chạy trên máy đó; mặc định `"none"` và UI phải hiện cảnh báo tương ứng (§6.5 tầng 4).

Đăng ký **mọi** case mới vào `tests/required_cases.json`. Xoá case cũ chỉ khi có case thay thế giữ hành vi (AGENTS.md).

**Không** đổi version application/npm/HTTP hay manifest trong spec này.

---

## 11. Rủi ro còn lại — phải nói, không được giấu

| Rủi ro | Mức | Xử lý |
|---|---|---|
| Executor Python lệch ngữ nghĩa so với Power Query | **Cao — đã chấp nhận khi chốt G** | 4 tầng ở §6.5: kỳ vọng viết tay (`fast`), bảng khác biệt có ghi nhận, đối chiếu M ở `runtime` gate, `engine.knownDifferences` trong response + dòng cảnh báo trên UI. Không hứa khớp PQ 100% |
| Reconcile yếu hơn khi plan không khai `controlTotal` | **Cao** | Đã thiết kế: hiện `controlTotalApplicable:false` + ack + nhãn `unverified`. Không giả vờ |
| Codex soạn plan sai/khó hiểu | Trung | Validate 7 bước + hiện lỗi theo `path`; không tự sửa |
| A/B là 2 lần tính trên 100k dòng | Trung | Đo `elapsedMs`; UI hiện thời gian; cache theo `snapshotHash+planHash` |
| Approval process-affine (một process) | Trung | Chấp nhận cho local add-in; ghi rõ "không restart giữa duyệt và ghi" |
| Không có live Office.js/Excel evidence tới khi P4 | **Cao** | Gate fake-host không thay live; phải chạy `tests/live/README.md` trước khi tuyên bố |
| Thêm domain vẫn cần catalog mở rộng | Thấp | Catalog đóng 15 thao tác phủ phần lớn báo cáo dạng bảng; thiếu thì **báo cáo**, không tự thêm |

### Điều spec này **không** hứa

1. Không hứa AI hiểu đúng nghiệp vụ. Codex đề xuất; người dùng chốt.
2. Không hứa kết quả nghiệp vụ đúng. Engine đúng **số học** trên plan, không đúng **ý nghĩa**.
3. Không hứa khớp Power Query từng bit. Cam kết là: **tất định, kiểm chứng được, khác biệt có ghi nhận** (§6.5).
4. Không hứa chạy được mọi workbook: plan phải nằm trong 15 thao tác + 10 biểu thức.
5. Không hứa live Excel cho tới khi P4 có evidence.

---

*Cập nhật đồng thời khi đổi hợp đồng: mục 5 (HTTP), §4 (luồng), §9 (pha), `tests/required_cases.json`. Không được nới 7 luật chống "giả kết quả" ở `ASSISTANT_FLOW_SPEC.md` §9.*
