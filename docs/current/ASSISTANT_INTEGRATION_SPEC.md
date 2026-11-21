# ASSISTANT_INTEGRATION_SPEC — Nối WL1–WL7 vào coordinator và task pane

> ## ⚠ ĐỌC DÒNG NÀY TRƯỚC
>
> **Tài liệu này là v1.x — KHÔNG phải kế hoạch thi công hiện hành.**
>
> Kế hoạch thi công chính thức: **[ASSISTANT_V2_BUILD_SPEC.md](ASSISTANT_V2_BUILD_SPEC.md)** (luồng v2: mọi workbook, Codex sinh kế hoạch, preview A/B trước khi chốt, Custom XML).
>
> **Không implement các phần sau của tài liệu này** (chúng sẽ bị v2 thay):
> `_FIN`/`_SALES`, `RESULT_COLUMNS`, `_supported_recipe`, `result_rows`, `build_preview` theo recipe, `apply_result`, `measure_set`, `/api/assistant/decisions` + `/spec` (v2 gộp thành `/freeze`).
>
> **Vẫn dùng tài liệu này để tra chi tiết:** ánh xạ mã lỗi HTTP (§4.4–4.5), đọc Office.js + bẫy ngày (§6), convention DOM (§5), quy tắc copy (§5.6), đặc tả smoke script (§12), danh sách test (§7).
>
> Tài liệu v1.x vẫn có giá trị nếu v2 bị hoãn — nhưng **đừng** xây WL5/WL6 của v1.x.

| Trường | Giá trị |
|---|---|
| Phiên bản | 1.5 — 30/10/2026 (Asia/Saigon) |
| Changelog | 1.1: chốt P0-2b (11.3), `briefRequirements` P0-3 (11.4), smoke script (mục 12), pha P1.5. **1.2: SỬA chỉ đạo — thay nội dung tab `Trợ lý`, KHÔNG thêm tab thứ ba** (5.1, 11.2); bảng ánh xạ 4 case JS (7.3.1); P4a/P4b; domain là enum đóng 2 giá trị (11.4). **1.3: chốt hướng Codex dài hạn — giữ `/api/excel/analyze`, 3 seam nhãn, pha P7** (11.5, D12–D15); thêm mục 13 đánh giá quỹ đạo. **1.4: thêm mục 14 — hướng sản phẩm v2.** **1.5: chốt Q1=(b) Codex soạn typed plan, Q3=seed tất định, Q4=preview A/B trước freeze, Q6=Custom XML; phát hiện Typed v1 đã là engine cho (b) ⇒ WL5/WL6 v1.x là bản trùng lặp; khuyến nghị đổi thứ tự + thêm P8** |
| Status | Spec thi hành; **chưa implement**, chưa có dòng code nào |
| Nguồn | `ASSISTANT_FLOW_SPEC.md` v1.1, `ASSISTANT_WL1..WL7.md`, `ASSISTANT_TRACEABILITY.md`, `ASSISTANT_FIXTURES.md`, `reports/audit/ponytail-preflight-audit.md`, `reports/audit/ponytail-taskpane-readiness.md` |
| Đối tượng | Codex / engineer implement; người kiểm thử chạy mục 7.4 và mục 12 |
| Phạm vi | WL1–WL7 **thay chỗ** UI tư vấn trong tab Trợ lý + coordinator HTTP + Office.js + script smoke |
| Ngoài phạm vi | AI narrative layer, fallback generic cho FIN, LY, PBIP patch, DAX/TMDL, Advanced M, domain pack thứ ba |

> **Mục tiêu một câu:** biến 17 module engine `pbip_assistant/sources/assistant_*.py` (hiện **chỉ test import**) thành chính tab Trợ lý — bấm được, ghi được kết quả, có hợp đồng HTTP/DOM/test rõ tới mức codex implement xong là chạy được ngay, không phải quyết định lại kiến trúc.

**Ba câu chốt để codex bắt đầu ngay, không cần hỏi lại:**

1. **Thay** nội dung tab `Trợ lý`, **không** thêm tab thứ ba; tab bar vẫn 2 tab (5.1, 11.2).
2. Sửa **cả** `readWorkbook()` (P0-2b) vì tab PQ vẫn dùng nó (11.3).
3. Có **`briefRequirements`** server-side (11.4 — P0-3) và có **`tools/assistant_flow_smoke.ps1`** (mục 12 — P1.5). Domain là enum đóng `fin-pl-v1` | `generic`, không có domain thứ ba.

---

## 1. Phân loại hiện trạng: cái gì có UI, cái gì chưa nối

### 1.1 Ba tầng hiện trạng

| Tầng | Định nghĩa | Kiểm thử được ngay? |
|---|---|---|
| **A · Đã nối** | Có UI trong task pane, có route coordinator, có store giữ quyền state | **Có** — bấm trong Excel hoặc chạy test sẵn có |
| **B · Chỉ có engine** | Có module Python + fixture + test synthetic; **không route, không UI** | **Không** — chỉ chạy được `py -m unittest`, không bấm được |
| **C · Chưa có** | Không engine, không UI, hoặc đã chốt là không làm | Không |

### 1.2 Bảng tổng hợp theo chức năng

| Chức năng | Tầng | Đường hiện có | Test được hôm nay? |
|---|---|---|---|
| Tab Trợ lý hiện tại | **A · sẽ bị thay ở P4a** | Office.js → `POST /api/excel/analyze` → Codex advice | Chạy được **hôm nay**, nhưng đó là UI sắp bỏ. `canApply=false` ⇒ bước 05/06 không bao giờ hiện |
| Typed Steps v2: root, clarification, continuation, branch, sửa step | **A** | `/api/pq/v2/plans`, `/revisions`, `/mutations/commit` + Custom XML read-back | Có |
| Preview cuối → Confirm → result sheet → cache | **A** | `/previews` → `/approvals` → `/applies/prepare` → writer → `/applies/complete` | Có (có defect đã biết) |
| Checkout / Quay về trong chain | **A** | `/problem-chains/checkout` → cache/fingerprint → restore hoặc staging | Có (finding 5) |
| Chuyển sang chain archived | **A** | `/problem-chains/chains/activate` — **đường riêng, defect** | Có defect (finding 2) |
| Diagnostic step: Run/Confirm/Cancel | **A** | `/step-diagnostics/*` | Có |
| Source-changed / session expiry / reload / reopen | **A** | version + fingerprint + Custom XML | Có |
| Advanced M (trusted) | **A · deferred** | `/api/pq/preview`, `/api/pq/save` | Có nhưng **chốt là deferred** |
| **Assistant WL1–WL7** | **B** | **Không có route, không có UI** | **Không** |
| PBIP / PBIR / TMDL catalog + proposal | **B** | CLI/backend; bridge smoke pass | Không qua task pane |
| Source web CSV/XLSX | **B · UI khác** | `py -m pbip_assistant.webapp --port 8765` | Có, nhưng **không phải** task pane |
| AI narrative layer (diễn giải nghĩa cột, đề xuất định nghĩa) | **C** | — | Không |
| Fallback generic khi thiếu finance pack | **C · chốt fail-closed** | — | Không |
| LY (Last Year) | **C · ngoài MVP** | — | Không |

### 1.3 Bằng chứng: Assistant engine không có một dòng nối nào

Kiểm bằng grep toàn repo (`*.py`, trừ chính engine):

```
pbip_assistant/coordinator/**        → 0 import assistant_*
pbip_assistant/excel_addin/**        → 0 tham chiếu "assistant", "WL1".."WL7", "ingest", "brief", "freeze"
pbip_assistant/adapters/codex/**     → 0
pbip_assistant/web/**                → 0
tools/**                             → 0 (không có CLI, không subcommand trong __main__.py)
tests/**                             → 177 match (toàn bộ)
```

Kiểm bằng grep trên file UI:

```
taskpane.js  : 4 hit, tất cả tự tham chiếu (dòng 291, 3485, 3487, 3937)
taskpane.html: 3 hit, chỉ là id="tab-assistant-button", id="tab-assistant", id="reconcile-status"
"WL1".."WL7" / "ingest" / "understand" / "brief" / "freeze" / "spec" → 0 hit
```

⇒ **`ASSISTANT_TRACEABILITY.md` ghi 20 dòng `partial`; gốc của cả 20 dòng không phải engine thiếu, mà là thiếu tầng nối.** Spec này đóng phần lớn trong số đó (mục 10).

### 1.4 Vì sao tab Trợ lý "chỉ trả đề xuất"

Chuỗi thật của tab Trợ lý hôm nay:

```
readWorkbook()  (samples 20 dòng/sheet, 20 dòng/table)
  → POST /api/excel/analyze  {prompt, workbook, formulaListSeparator}
  → adapters/codex/excel.py:206-226  luôn trả:
        status: "analysis_only" | "needs_clarification"
        canApply: false
  → renderPlan()  (taskpane.js:685)  setHidden("approval-section", status !== "review_ready" || canApply === false)
        ⇒ #approval-section LUÔN ẩn
        ⇒ #result-section cũng không bao giờ hiện (chỉ renderRuntime mở, chỉ /api/excel/apply gọi)
```

Đây không phải bug: `canApply=false` là biên sản phẩm (không Apply công thức tự do). Nhưng nó tạo hai hệ quả cần nói rõ:

1. Runbook `tools/excel_addin/README.md:59-65` (finding 7) mô tả **đường không tồn tại** (Analyze → 4 công thức → SIMULATED → duyệt copy → EXCEL VERIFIED). Đường đó là `POST /api/excel/plan` + `/api/excel/apply` (fixture connector), **không phải** `/api/excel/analyze`. Phải sửa runbook (mục 8, P6).
2. WL1–WL7 **không thể** đi qua tab Trợ lý hiện tại. Cần tab/màn mới.

---

## 2. Mười hai ràng buộc đã kiểm chứng (codex không được giả định khác)

Mỗi ràng buộc dưới đây đã đọc trực tiếp từ source. Vi phạm là hỏng luồng.

| # | Ràng buộc | Bằng chứng | Hệ quả thiết kế |
|---|---|---|---|
| **C1** | Luồng WL1–WL7 **không gọi AI/Codex**. WL2 là thống kê tất định; WL3 lấy chữ từ "authored pack" | `assistant_understand.py:98-118`, `assistant_pack.py`, `assistant_brief.py:128-168` | Không cần slot `codex`, không cần disclosure "gửi prompt". **Nhưng UI không được ghi "AI đã phân tích workbook"** — phải ghi đúng: đo tất định + pack biên soạn sẵn |
| **C2** | `_Approval` là object **process-affine**: `_ISSUED` là dict `weakref` khoá `id(approval)`; bản copy/JSON bị `_live()` từ chối | `assistant_approval.py:18-21,80-81` | Coordinator **phải giữ strong ref** tới đúng object giữa `/approvals` và `/apply`. Client **không được** cầm và gửi lại approval. Không được restart coordinator giữa 2 bước |
| **C3** | Preview **chỉ thực thi option A**. Chọn B ⇒ `AF_POLICY_UNSUPPORTED` | `assistant_preview.py:96-98,124` | UI phải nói rõ A là nhánh thực thi được; B chỉ ghi nhận quyết định, và báo blocker nếu chọn B |
| **C4** | Recipe đóng: chỉ **2 kịch bản** `tp-fin` (23×9) và `tp-sales` (4×4). Spec phải khớp từng step với định nghĩa cố định | `assistant_preview.py:30-34,112-125` | Không hứa "phân tích mọi workbook". UI phải hiện badge kịch bản và cảnh báo trước khi ingest dữ liệu không khớp |
| **C5** | WL1: chỉ "workbook đang mở" nhận **payload**; `csv`/`xlsx`/`folder` **chỉ nhận path** | `assistant_ingest.py:104,155,204,249` | Hai đường ingest: payload (Office.js) và path (server đọc đĩa). Không có ingest bytes |
| **C6** | `add_open_workbook` **từ chối** mẫu: `sampleOnly:true` bị chặn; `totalRows != len(rows)` bị chặn | `assistant_ingest.py:264-266` | Phải đọc **toàn bộ** vùng chọn, không đọc 20 dòng như `/api/excel/analyze` |
| **C7** | Ngày phải là **`YYYY-MM-DD`**: `date.fromisoformat(row[i])` | `assistant_brief.py:44-47` | Office.js trả `Date` cho ô ngày ⇒ **phải chuẩn hoá** trước khi gửi; `toISOString()` gây **lệch 1 ngày** với UTC+7 |
| **C8** | `build_preview` **không trả bytes**; muốn có file phải tự gọi `build_workbook` | `assistant_preview.py:441-468` | Coordinator không cần file trung gian; chỉ giữ artifact |
| **C9** | `AF_WRITE_PARTIAL` dùng cho **cả** lỗi trước khi ghi **và** lỗi sau khi đã consume | `assistant_apply.py:309 vs 314` | Phân biệt bằng `approval_state(approval)["consumed"]`: `False` ⇒ chưa ghi gì (được sửa và duyệt lại); `True` ⇒ token đã mất, **không bao giờ retry** |
| **C10** | Marker preview ≠ marker apply | `assistant_preview.py:433-438` vs `assistant_apply.py:283-286` | Preview dùng `result_digest`; Apply dùng `preview["previewHash"]` và sheet đích `*_Result`. Xây sai ⇒ `AF_SPEC_STALE`/`AF_WRITE_PARTIAL` |
| **C11** | Tên sheet bị chốt cứng: preview `PnL_Preview`/`Sales_Preview`, apply `PnL_Result`/`Sales_Result` | `assistant_preview.py:449-451`, `assistant_apply.py:265` | UI **không** cho người dùng đặt tên sheet ở bản này |
| **C12** | `build_snapshot` raise `ValueError` (không phải `InputError`); WL2 cũng chỉ raise `ValueError` | `assistant_profile.py:104-128`, `assistant_understand.py` | Adapter HTTP phải bắt **cả** `InputError` **và** `ValueError`, ánh xạ sang mã `AF_*` ổn định (mục 4.4) |

### 2.1 Ba defect phải sửa **trước** khi nối (nếu không, luồng sẽ sai số)

| Defect | Vị trí | Vì sao chặn luồng WL | Pha |
|---|---|---|---|
| Cardinality không hợp lệ lọt qua WL2→WL3 | `assistant_brief.py:102-115` | Gate đỏ `test_invalid_relationship_cardinality_is_rejected_before_brief`; mọi lần chạy `run_checks.py fast` đều fail | P0-1 |
| Total Row bị đếm là dữ liệu | `taskpane.js:388-431` | Đọc full giá trị bị lỗi này thì `totalRows` sai 1 và **dòng tổng bị đẩy vào WL1 như dữ liệu thật** ⇒ control total lệch ⇒ reconcile fail | P0-2a (hàm mới), P0-2b (sửa luôn `readWorkbook` — xem 11.3) |
| Chưa có đường đọc **full values** | `taskpane.js:375-398` chỉ lấy mẫu | C6 chặn mẫu ⇒ phải có hàm đọc mới | P0-2a |

Defect thứ ba phụ thuộc P0-3: UI không thể cảnh báo "thiếu cột `PostingDate`" nếu adapter không được phép gọi `required_date_column()` (11.4).

---

## 3. Kiến trúc đích

### 3.1 Thành phần mới (2 module code, 0 tab mới)

| Loại | Đường dẫn | Trách nhiệm | Không được làm |
|---|---|---|---|
| State owner | `pbip_assistant/sources/assistant_session.py` (mới) | Giữ session WL1, raw tables, snapshot, understand, brief, decisions, spec, pack, result, preview, reconciliation, **live `_Approval`**, delta, record. Sở hữu lock + stage | Không parse HTTP, không biết token, không đọc `self.headers` |
| HTTP adapter | `pbip_assistant/coordinator/endpoints/assistant.py` (mới) | Đọc body, gọi store, map lỗi, trả JSON | Không giữ quyền state, không tính số, không giữ approval |
| UI | `pbip_assistant/excel_addin/taskpane.html` + `taskpane.js` (thêm tab thứ 3) | DOM, gọi API, render, đọc Office.js | Không tính lại số engine |

Đăng ký trong `coordinator/server.py`:

```python
# dòng 25-31: thêm import
from pbip_assistant.coordinator.endpoints.assistant import AssistantEndpoints

# dòng 307-310: thêm mixin
class ExcelAddinRequestHandler(
    AnalysisEndpoints, AdvancedEndpoints, TypedEndpoints, HistoryEndpoints,
    DiagnosticsEndpoints, FixtureEndpoints, AssistantEndpoints,
    BaseHTTPRequestHandler,
):

# dòng 158-172: thêm toàn bộ vào STATE_PATHS (single-writer cho store)
ASSISTANT_PATHS = frozenset({
    "/api/assistant/session", "/api/assistant/ingest", "/api/assistant/understand",
    "/api/assistant/brief", "/api/assistant/decisions", "/api/assistant/spec",
    "/api/assistant/preview", "/api/assistant/approvals", "/api/assistant/apply",
    "/api/assistant/state", "/api/assistant/reset",
})
STATE_PATHS = STATE_PATHS | ASSISTANT_PATHS

# dòng 396-428: thêm 11 route
POST_ENDPOINTS = {
    ...
    '/api/assistant/session':    '_post_assistant_session',
    '/api/assistant/ingest':     '_post_assistant_ingest',
    '/api/assistant/understand': '_post_assistant_understand',
    '/api/assistant/brief':      '_post_assistant_brief',
    '/api/assistant/decisions':  '_post_assistant_decisions',
    '/api/assistant/spec':       '_post_assistant_spec',
    '/api/assistant/preview':    '_post_assistant_preview',
    '/api/assistant/approvals':  '_post_assistant_approvals',
    '/api/assistant/apply':      '_post_assistant_apply',
    '/api/assistant/state':      '_post_assistant_state',
    '/api/assistant/reset':      '_post_assistant_reset',
}
```

**Slot:** toàn bộ `/api/assistant/*` chỉ dùng `state()` (C2: một writer duy nhất cho store, và approval phải cùng process). **Không** đưa vào `CODEX_JOB_PATHS` (C1). **Không** đưa `/ingest` hay `/apply` vào `EXCEL_JOB_PATHS` — hai đường này không gọi Excel COM.

Lifecycle trong `ExcelAddinApp`:

```python
# __init__ (~dòng 269)
self.assistant = AssistantSessionStore()

# _clear_session_state (dòng 294-298) — thêm
self.assistant.reset()

# close (dòng 300-304) — thêm
self.assistant.close()
```

Bootstrap capability (dòng 350-367), để pane feature-gate và phát hiện coordinator cũ:

```python
"assistantFlowV1": True,
"assistantFlowNamespace": "urn:local-data-copilot:assistant-flow:v1",
"assistantFlowStages": ["new","ingested","understood","briefed","decided","frozen",
                        "previewed","reconciled","approved","applied","recorded"],
```

### 3.2 Chuỗi gọi engine — bản chuẩn

Đây là toàn bộ logic thật, chép đúng thứ tự từ `tests/unit/test_assistant_record.py:28-42` + `tests/contracts/test_assistant_e2e.py:51-90`. Store gọi **đúng** chuỗi này:

```python
# ── WL1 ────────────────────────────────────────────────────────────────
self._session = {"root": Path(root)}                    # root đã validate tuyệt đối
ingested = ingest.resolve(self._session, requests)      # ghi session["_assistant_ingest"]
if ingested["errors"] or ingested["requiresRename"] or any(
        o.get("needsClarification") for o in ingested["csvOptions"]):
    raise <IngestBlocked>(ingested)                     # không build snapshot
snapshot = build_snapshot(ingested, created_at=now_iso())
self._raw_tables = ingested["tables"]

# ── WL2 ────────────────────────────────────────────────────────────────
understand = build_understand(self._raw_tables, snapshot, created_from="wl1")
pack = load_pack(select_pack(understand))               # engine tự dò, KHÔNG dùng pack_id để gán

# ── WL3 ────────────────────────────────────────────────────────────────
brief = build_brief(self._raw_tables, snapshot, understand, pack, prompt,
                    policy_unresolved=frozenset(policy_unresolved),
                    output_contract_override=override)

# ── WL4 ────────────────────────────────────────────────────────────────
decisions = build_decisions(brief, choices=choices, acknowledgements=acks,
                            decision_metadata={...})     # decidedBy="user", decidedAt ISO+tz
assert not freeze_blocked(brief, decisions)["blocked"]
spec = build_spec(brief, decisions, pack, created_at=now_iso())

# ── WL5 ────────────────────────────────────────────────────────────────
result = result_rows(self._raw_tables, spec, decisions, pack)
scenario = "tp-fin" if pack["id"] == "fin-pl-v1" else "tp-sales"
preview_sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
preview = build_preview(result, spec, snapshot, sheet=preview_sheet,
                        marker=preview_marker(result, spec, sheet=preview_sheet),
                        source_evidence=self._csv_evidence())
reconciliation = build_reconciliation(preview, spec, self._raw_tables, result)

# ── WL6 ────────────────────────────────────────────────────────────────
assert_approvable(reconciliation)                        # CỔNG CỨNG, phải gọi ở đây
approval = issue_approval(spec, preview, approved_by="user", approved_at=now_iso())
self._approval = approval                                # STRONG REF (C2)

target_sheet = "PnL_Result" if scenario == "tp-fin" else "Sales_Result"
apply_marker = ("LOCAL_DATA_COPILOT|" + target_sheet + "|spec=" + spec["fingerprint"] +
                "|preview=" + preview["previewHash"] + "|labels=" + ",".join(spec["labels"]))
applied = apply_result(workbook_bytes, result=result, target_sheet=target_sheet,
                       marker=apply_marker, labels=spec["labels"],
                       approval=self._approval, spec=spec, preview=preview,
                       applied_at=now_iso())

# ── WL7 ────────────────────────────────────────────────────────────────
delta = compute_delta(self._raw_tables, result, spec, scenario=scenario)
record = build_record(snapshot, brief, decisions, spec, reconciliation, delta,
                      created_at=now_iso(), source_evidence=self._csv_evidence())
stale = detect_stale(record, current_snapshot=snapshot, current_decisions=decisions,
                     current_source_evidence=self._csv_evidence())
```

`_csv_evidence()` — chỉ cho nguồn CSV/folder (C5, `assistant_preview.py:347-348`). Đọc lại từ đĩa **tại thời điểm apply** để bắt nguồn đã đổi ⇒ `AF_SPEC_STALE`. Với nguồn `workbook` trả `None`:

```python
def _csv_evidence(self):
    if any(s["type"] == "workbook" for s in self._snapshot["sources"]):
        return None
    root = self._session["root"]
    return {p.relative_to(root).as_posix(): p.read_bytes().decode("utf-8")
            for p in sorted(root.rglob("*.csv"))}
```

### 3.3 Mô hình state của store

```python
class AssistantSessionStore:
    _LOCK: RLock                     # mọi method public đều giữ lock này
    _session: dict | None            # dict cho ingest.resolve (giữ "_assistant_ingest")
    _root: Path | None               # tuyệt đối, đã resolve; KHÔNG trả về client
    _ingested: dict | None
    _raw_tables: list[dict] | None   # FULL rows — bộ nhớ lớn nhất, ~100k dòng/table
    _snapshot, _understand, _brief, _decisions, _spec, _pack
    _result, _preview, _reconciliation
    _approval                        # live _Approval, strong ref (C2)
    _delta, _record
    _stage: str                      # xem _STAGES
    _applied: dict | None
```

`_STAGES = ("new","ingested","understood","briefed","decided","frozen","previewed","reconciled","approved","applied","recorded")`

Mỗi method kiểm **tiền điều kiện stage** và ném `AssistantStageError(code="AF_STAGE_INVALID")` nếu sai thứ tự. Đây là lớp thứ hai; lớp thứ nhất là chính engine tự verify hash.

Reset/close: `close()` gọi `ingest.close(session)` (giải phóng `_assistant_ingest`), xoá mọi artifact, `self._approval = None`. **Không xoá file, không Save.**

---

## 4. Hợp đồng HTTP

### 4.1 Nguyên tắc chung

- Tất cả `POST`, JSON, header `X-Local-Token` (pane đã tự gắn trong `api()`).
- Mọi response đều có `stage` hiện tại của store (để pane đồng bộ máy trạng thái).
- **Không endpoint nào trả raw rows của nguồn.** `/preview` và `/apply` trả tối đa **200 dòng** kết quả kèm `truncated` + `totalRows`.
- **Không endpoint nào trả `_root` tuyệt đối**; chỉ `rootLabel` = tên thư mục cuối.
- Body limit: thêm vào `coordinator/endpoints/__init__.py`:

```python
MAX_ASSISTANT_JSON_BYTES = 8 * 1024 * 1024        # mọi route trừ /apply
MAX_ASSISTANT_INGEST_JSON_BYTES = 72 * 1024 * 1024  # /ingest khi có payload workbook
# /apply dùng lại MAX_APPLY_JSON_BYTES = 48 MiB (đã có)
```

`72 MiB` suy từ `MAX_BYTES_PER_FILE = 64 MiB` (`assistant_ingest.py:15`) + overhead escape JSON. **Pane phải tự chặn sớm hơn** (mục 6.4) để không bao giờ chạm limit này.

### 4.2 Danh sách route

| Route | Stage vào | Stage ra | Engine gọi |
|---|---|---|---|
| `/api/assistant/session` | any | `new` | — |
| `/api/assistant/ingest` | `new` | `ingested` \| `ingest_blocked` | `resolve`, `build_snapshot` |
| `/api/assistant/understand` | `ingested` | `understood` | `build_understand`, `load_pack`, `select_pack` |
| `/api/assistant/brief` | `understood` | `briefed` | `build_brief` |
| `/api/assistant/decisions` | `briefed` | `decided` | `build_decisions`, `freeze_blocked` |
| `/api/assistant/spec` | `decided` | `frozen` | `build_spec` |
| `/api/assistant/preview` | `frozen` | `previewed` \| `reconciled` | `result_rows`, `build_preview`, `build_reconciliation` |
| `/api/assistant/approvals` | `reconciled` | `approved` | `assert_approvable`, `issue_approval` |
| `/api/assistant/apply` | `approved` | `recorded` | `apply_result`, `compute_delta`, `build_record`, `detect_stale` |
| `/api/assistant/state` | any | (không đổi) | — |
| `/api/assistant/reset` | any | `new` | `ingest.close` |

### 4.3 Đặc tả từng route

#### `POST /api/assistant/session`

```jsonc
// request
{ "root": "C:\\Users\\me\\fixtures\\tp-fin\\source" }   // bắt buộc; tuyệt đối, tồn tại, là thư mục
// response 200
{ "stage": "new",
  "rootLabel": "source",
  "limits": { "maxRows": 100000, "maxColumns": 512, "maxCellChars": 10000,
              "maxBytesPerFile": 67108864, "maxBytesPerSession": 134217728 } }
```

Lỗi: `ASSISTANT_ROOT_INVALID` (400) khi không tuyệt đối / không tồn tại / không phải thư mục / là reparse point.

#### `POST /api/assistant/ingest`

```jsonc
// request
{ "requests": [
    { "kind": "csv", "path": "GL_Actuals_2026-09.csv" },
    { "kind": "xlsx", "path": "book.xlsx", "options": { "sheet": "Data" } },
    { "kind": "folder", "path": "orders", "name": "Orders", "options": { "pattern": "*.csv" } },
    { "kind": "workbook",
      "payload": { "header": ["region","revenueVnd"],
                   "rows": [["North","1200"]],
                   "name": "book.xlsx", "origin": "Workbook!Orders",
                   "sheet": "Orders", "range": "A1:J400",
                   "table": true, "totalRows": 1, "totalColumns": 2 } }
  ] }
```

`payload.origin` **phải là locator tương đối**, không `..`, không tuyệt đối (`assistant_ingest.py:280`). `totalRows`/`totalColumns` **phải bằng** `len(rows)`/`len(header)` (C6).

```jsonc
// response 200 — thành công
{ "stage": "ingested",
  "snapshot": { "snapshotId":"snap_…", "snapshotHash":"sha256:…", "createdAt":"…",
                "sourceCount":7, "tableCount":7 },
  "sources": [ { "id":"src_…", "name":"GL_Actuals_2026-09.csv", "type":"csv",
                 "origin":"GL_Actuals_2026-09.csv", "hash":"sha256:…", "addedAt":"…" } ],
  "tables":  [ { "id":"tbl_…", "sourceId":"src_…", "name":"GL_Actuals_2026-09",
                 "rowCount":42, "columnCount":11,
                 "locator": { "kind":"csv" },
                 "columns":[ { "name":"PostingDate", "nullRate":0.0, "distinctCount":12,
                               "distinctRatio":0.286, "sample":["2026-09-01", "…"] } ] } ],
  "warnings": [], "schemaVersion": "1.0" }

// response 200 — bị chặn nhưng người dùng sửa được  (KHÔNG phải HTTP error)
{ "stage": "ingest_blocked",
  "errors": [ { "code":"AF_INGEST_FAILED", "severity":"blocker",
                "path":"orders", "detail":"…" } ],
  "warnings": [ { "code":"AF_MISSING_DATA", "severity":"warning", "message":"…" } ],
  "requiresRename": [ { "tableName":"Orders", "sources":["src_a","src_b"] } ],
  "csvOptions": [ { "sourceId":"src_c", "encoding":"utf-8", "delimiter":";",
                    "headerRow":1, "needsClarification":true,
                    "candidates":[{"delimiter":";","rows":42},{"delimiter":",","rows":1}] } ] }
```

**Quy tắc:** engine **trả** lỗi chứ không raise (WL1). `stage:"ingest_blocked"` là **200** vì người dùng còn sửa được (đổi tên bảng, chọn delimiter). Chỉ khi body sai shape mới là 400.

Pane phải render 3 khối điều kiện từ response này: rename list, CSV option picker, error/warning list.

#### `POST /api/assistant/understand`

```jsonc
{ "packId": "auto" }        // "auto" | "generic" | "fin-pl-v1"
// response 200
{ "stage": "understood",
  "understandHash": "sha256:…",
  "pack": { "id":"fin-pl-v1", "version":"1.0", "genericMode":false, "notice":null },
  "roles": [ { "tableId":"tbl_…", "structural":"fact", "domainLabel":"…",
               "confidence":0.92,
               "evidence":[ { "kind":"stats", "value":"…", "ref":null, "formulaId":null } ] } ],
  "relationships": [ { "id":"rel_…", "fromTable":"tbl_a", "fromColumns":["AccountCode"],
                       "toTable":"tbl_b", "toColumns":["AccountCode"],
                       "cardinality":"N:1", "score":0.98,
                       "evidence": { "name":"exact", "type":"text", "overlap":0.98, "orphan":3 },
                       "status":"auto", "fanOutRisk":"none", "fanOutEvidence":null } ],
  "assumptions": [ { "id":"asm_…", "statement":"…", "source":"pack",
                     "confidence":0.5, "risk":"low", "evidence":[] } ],
  "warnings": [ { "code":"AF_MISSING_DATA", "severity":"warning", "message":"…" } ],
  "briefRequirements": { "dateColumn":"PostingDate",
                         "grain":["accountCode","costCenter","entityCode","period"],
                         "scenario":"tp-fin" } }
```

`briefRequirements` là **bổ sung của adapter** (không có trong engine) để UI cảnh báo sớm thay vì để `/brief` fail bằng `AF_BRIEF_INVALID`. Cách tính phải **dùng chung một nguồn** với `_period` (`assistant_brief.py:36-38`):

> **Yêu cầu refactor nhỏ (bắt buộc):** thêm vào `assistant_brief.py`
> ```python
> def required_date_column(pack_id: str) -> str:
>     return "PostingDate" if pack_id == "fin-pl-v1" else "OrderDate"
> ```
> và cho `_period` dùng hàm này. Adapter import chính hàm đó. Không được chép chuỗi sang JS.

Lỗi: `AF_UNDERSTAND_INVALID` (409) cho mọi `ValueError` của WL2, gồm: hash snapshot không khớp, profile lệch snapshot, finance pack thiếu schema, vượt giới hạn dò khoá (`MAX_KEY_SEARCH_COMBINATIONS`, `MAX_RELATIONSHIP_CANDIDATES`).

#### `POST /api/assistant/brief`

```jsonc
{ "prompt": "Báo cáo P&L theo cost center, quy VND, tách FX.",
  "policyUnresolved": ["SP-3"],
  "outputContractOverride": null }
// response 200
{ "stage": "briefed", "briefHash": "sha256:…",
  "outputContract": { "grain":["accountCode","costCenter","entityCode","period"],
                      "measures":[{"name":"netRevenue","formulaId":"fm_net_revenue"}],
                      "currency":"VND",
                      "period":{"from":"2026-09-01","to":"2026-09-30","label":"T9/2026"},
                      "filters":[{"field":"period","operator":"between","value":["…","…"]}] },
  "findings": [ { "id":"fd_…", "statement":"…",
                  "value":{"formulaId":"fm_net_revenue","value":"1234567890","unit":"VND"},
                  "evidence":[…], "status":"inferred", "provenance":"pack" } ],
  "insightCases": [ { "id":"ic_…", "kind":"hypothesis" } ],
  "subProblems": [ { "id":"SP-1", "question":"…", "whyItMatters":"…",
                     "status":"assumed", "provenance":"pack",
                     "options":[ {"id":"A","label":"…","recommended":true,
                                  "consequence":{"statement":"…","value":{…}}},
                                 {"id":"B","label":"…","recommended":false,
                                  "consequence":{"statement":"…","value":{…}}} ],
                     "proposedOptionId":"A", "chosenOptionId":null,
                     "blocker":true, "consequenceOfChoice":null, "labels":["assumed"] } ],
  "scenarios": [ {"id":"A","label":"…","values":[…]}, {"id":"B","label":"…","values":[…]} ],
  "delta": { "formulaId":"…", "value":"…", "unit":"VND" },
  "assumptions": [ { "id":"asm_…", "statement":"…", "source":"pack",
                     "confidence":0.5, "risk":"low", "evidence":[] } ],
  "labels": ["assumed","unverified"],
  "executableOptionId": "A" }
```

`executableOptionId` là **bổ sung adapter** phản ánh C3, để UI tô đúng nút A là "thực thi được" còn B là "chỉ ghi nhận".

Lỗi: `AF_BRIEF_INVALID` (409). Detail tiếng Việt từ engine, hiển thị nguyên văn cho người dùng.

#### `POST /api/assistant/decisions`

```jsonc
{ "choices": { "SP-1":"A", "SP-2":"A" },
  "acknowledgements": { "SP-7":"out_of_scope" },
  "decisionMetadata": { "decidedBy":"user",
                        "decidedAt":"2026-10-30T09:10:00+07:00",
                        "rationale":"",
                        "acknowledgementNotes":"" } }
// response 200
{ "stage": "decided", "decisionsHash":"sha256:…",
  "decisions":[ {"subProblemId":"SP-1","optionId":"A","decidedBy":"user",
                 "decidedAt":"2026-10-30T09:10:00+07:00","rationale":""} ],
  "acknowledgements":[ {"subProblemId":"SP-7","acknowledged":"out_of_scope","note":""} ],
  "freezeBlocked": false,
  "blockers": [ {"code":"AF_MISSING_DATA","severity":"warning","message":"…"} ],
  "checklist": [ "…" ] }
```

`choices` chỉ chứa SP có `status != "missing_data"`; `acknowledgements` chỉ chứa SP `missing_data`; hai tập **rời nhau** (`assistant_preview.py:89-95`). `decidedAt` **bắt buộc** ISO có timezone; `decidedBy` chỉ `null` hoặc `"user"`.

Lỗi: `AF_DECISIONS_INVALID` (409), `AF_SPEC_STALE` (409 khi brief đã đổi).

#### `POST /api/assistant/spec`

```jsonc
{ "createdAt": "2026-10-30T09:11:00+07:00" }
// response 200
{ "stage": "frozen",
  "spec": { "schemaVersion":"1.0", "id":"spec_…", "snapshotHash":"sha256:…",
            "decisionsHash":"sha256:…", "briefHash":"sha256:…",
            "labels":["assumed","unverified"], "unverifiedAssumptions":["asm_…"],
            "fingerprint":"sha256:…", "createdAt":"…", "stale":false,
            "variantOf":null, "variantReason":null,
            "hashBasis":[ … 11 key … ],
            "steps":[ { "id":"st_01", "kind":"recipe", "label":"…",
                        "decisionRefs":["SP-1"], "inputs":[], "output":"q_01",
                        "dependsOn":[], "status":"ok", "guard":null,
                        "params": { "operation":"dedupe", "chosenOptions":{"SP-1":"A"} } } ] } }
```

Lỗi: `AF_MISSING_DATA` (409 — còn SP chưa chốt), `AF_SPEC_INVALID`, `AF_SPEC_STALE`, `AF_EXECUTION_INVALID`, `AF_FANOUT_RISK`.

#### `POST /api/assistant/preview`

```jsonc
{ "tolerance": "0.01" }        // optional, 0 ≤ t ≤ 0.01
// response 200
{ "stage": "reconciled",
  "preview": { "previewHash":"sha256:…", "specFingerprint":"sha256:…",
               "target": { "workbook":"temp_copy", "sheet":"PnL_Preview",
                           "mode":"values_only", "marker":"LOCAL_DATA_COPILOT|PnL_Preview|…" },
               "counts": { "formulaCount":0, "queryCount":0, "connectionCount":0 },
               "source": { "before":"sha256:…", "after":"sha256:…", "unchanged":true },
               "sheets": { "before":{"rows":42,"cols":11}, "after":{"rows":23,"cols":9} } },
  "reconciliation": { "passed":true, "reconcileHash":"sha256:…",
                      "rowsIn":42, "rowsInDeduped":40, "rowsOut":23, "colsIn":11, "colsOut":9,
                      "controlTotalSource":"…", "controlTotalResult":"…",
                      "controlTotalTolerance":"0.01", "controlTotalPassed":true,
                      "bridge": { "applicable":true, "op":"…", "fx":"…", "total":"…",
                                  "variance":"…", "passed":true },
                      "checks": [ {"id":"row_count","passed":true,"detail":"…"} ],
                      "blockers":[], "warnings":[], "labels":["assumed","unverified"] },
  "result": { "columns":["pnlLine","accountCode","costCenter","entityCode","actualVnd",
                         "budgetVnd","varianceVnd","period","currency"],
              "rows":[ … tối đa 200 dòng, số dạng chuỗi … ],
              "totalRows":23, "truncated":true },
  "resultDigest": "sha256:…",
  "approveBlocked": null }
```

Khi reconcile fail: `"approveBlocked": { "code":"AF_RECONCILE_FAILED", "detail":"…" }` và `"stage":"previewed"`. UI **khoá nút duyệt** (AF-EX-006).

Lỗi chặn quan trọng:
- `AF_POLICY_UNSUPPORTED` (409) khi có lựa chọn khác A (**C3**) — detail phải được hiển thị nguyên văn: *"Slice preview hiện chỉ thực thi policy A…"*.
- `AF_MISSING_DATA` khi thiếu lựa chọn/metadata.
- `AF_SPEC_STALE` khi decisions/spec/brief lệch nhau.

#### `POST /api/assistant/approvals`

```jsonc
{ "approvedAt": "2026-10-30T09:15:00+07:00" }
// response 200 — BẢN COPY CHỈ ĐỂ HIỂN THỊ
{ "stage": "approved",
  "approval": { "approvalId":"apr_…", "approvedBy":"user", "approvedAt":"…",
                "boundTo": { "specFingerprint":"sha256:…", "previewHash":"sha256:…" },
                "consumed":false, "singleUse":true } }
```

> ⚠ **Bất biến C2:** response trên là `dict(approval)` để hiển thị. Store **giữ** object `_Approval` gốc. `/apply` **không nhận** approval từ client. Nếu pane gửi lại, adapter phải bỏ qua và dùng `self._approval` — nếu dùng bản gửi lại thì `_live()` ném `AF_SPEC_STALE` và luồng chết.

#### `POST /api/assistant/apply`

```jsonc
{ "workbookBase64": "UEsDBBQ…",       // BẮT BUỘC — bytes của workbook đang mở
  "appliedAt": "2026-10-30T09:16:00+07:00" }
// response 200
{ "stage": "recorded",
  "apply": { "specFingerprint":"sha256:…", "previewHash":"sha256:…",
             "target": { "workbook":"current", "sheet":"PnL_Result",
                         "mode":"values_only", "writeMode":"new_sheet_only",
                         "marker":"LOCAL_DATA_COPILOT|PnL_Result|preview=…" },
             "written": { "rowCount":23, "columnCount":9 },
             "source": { "before":"sha256:…", "after":"sha256:…",
                         "unchanged":true, "sheetsWritten":[] },
             "workbookSaved": false,
             "labels":["assumed","unverified"], "appliedAt":"…",
             "approval": { "approvalId":"apr_…", "consumed":true, "singleUse":true },
             "hash":"sha256:…" },
  "result":        { "columns":[…], "rows":[[ … ]], "totalRows":23, "truncated":false },
  "resultDigest":  "sha256:…",
  "delta":         { "rowsIn":42, "rowsOut":23,
                     "nullsBefore":{"…":0}, "nullsAfter":{"…":0},
                     "duplicatesBefore":2, "duplicatesAfter":0,
                     "changedColumns":["netRevenue","variance"] },
  "record":        { … full Decision Record, JSON thuần, ≤ 2 MiB … },
  "staleCheck":    null }
```

Client **phải** dùng `result.columns`/`result.rows` để ghi bằng Office.js (mục 6.5) và so `resultDigest` sau khi ghi.

Lỗi — **phân biệt bằng `approvalConsumed` (C9):**

```jsonc
{ "error": { "code":"AF_WRITE_PARTIAL",
             "detail":"Read-back giá trị không khớp kết quả đã Preview; …",
             "approvalConsumed": true,      // ← trường bổ sung của adapter
             "written": null,       // unknown sau khi đã consume
             "retryable": false } }
```

- `approvalConsumed=false` ⇒ engine từ chối **trước** khi tiêu token. **Chưa ghi gì.** Người dùng sửa được (ví dụ sheet `PnL_Result` đã tồn tại) rồi duyệt lại.
- `approvalConsumed=true` ⇒ token đã mất, kết quả **partial/unknown**. `retryable=false`, UI phải hiện cảnh báo và **không** tự chạy lại.

Bảng chi tiết `written`/`retryable` theo `approvalConsumed` phải nằm ở **adapter**, không ở engine.

Các mã khác: `AF_SPEC_STALE` (approval đã dùng / binding lệch), `AF_DELTA_INVALID`, `AF_RECORD_INVALID`.

#### `POST /api/assistant/state`

```jsonc
{}
// response 200
{ "stage": "frozen",
  "hashes": { "snapshotHash":"sha256:…", "understandHash":"sha256:…", "briefHash":"sha256:…",
              "decisionsHash":null, "specFingerprint":null, "previewHash":null,
              "approvalId":null, "recordHash":null },
  "pack": { "id":"fin-pl-v1", "genericMode":false },
  "snapshot": { "snapshotId":"snap_…", "tableCount":7, "sourceCount":7 },
  "approvalConsumed": false,
  "reconcilePassed": null }
```

Dùng khi pane reload (Office task pane reload mất toàn bộ `state`) — cho phép hiển thị lại đúng bước thay vì bắt đầu từ đầu. Store thuộc session coordinator, sống qua reload pane.

#### `POST /api/assistant/reset`

`{}` → `{"stage":"new"}`. Gọi `ingest.close`, xoá artifact, `_approval=None`.

### 4.4 Ánh xạ lỗi trong adapter

Wire shape hiện có là `{"error": {"code", "detail", "path"}}` do `_error()` sinh ra (`server.py:616-621`). Pane đọc đúng `result.error.code` / `result.error.detail` (`taskpane.js:188-192`). Vì vậy trường bổ sung **phải nằm trong `error`**, và `_error()` cần thêm tham số `extra`:

```python
# server.py:616-621 — mở rộng tối thiểu, giữ nguyên chữ ký cũ cho mọi caller hiện có
def _error(
    self, status: HTTPStatus, code: str, detail: str, *, path: str = "",
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,      # ← THÊM
) -> None:
    self.close_connection = True
    payload = {"code": code, "detail": detail, "path": path}
    if extra:
        payload.update(extra)
    self._json(status, {"error": payload}, headers=headers)
```

```python
class AssistantEndpoints:
    _ASSISTANT_STATUS = {
        "AF_SPEC_STALE": HTTPStatus.CONFLICT,
        "AF_MISSING_DATA": HTTPStatus.CONFLICT,
        "AF_FANOUT_RISK": HTTPStatus.CONFLICT,
        "AF_POLICY_UNSUPPORTED": HTTPStatus.CONFLICT,
        "AF_RECONCILE_FAILED": HTTPStatus.CONFLICT,
        "AF_SOURCE_LOST": HTTPStatus.CONFLICT,
        "AF_STAGE_INVALID": HTTPStatus.CONFLICT,
        "AF_APPROVAL_MISSING": HTTPStatus.CONFLICT,
        "AF_WRITE_PARTIAL": HTTPStatus.INTERNAL_SERVER_ERROR,
        "AF_INGEST_FAILED": HTTPStatus.UNPROCESSABLE_ENTITY,
        "ASSISTANT_ROOT_INVALID": HTTPStatus.BAD_REQUEST,
        "ASSISTANT_WORKBOOK_REQUIRED": HTTPStatus.BAD_REQUEST,
    }

    def _assistant_error(self, exc: BaseException, *, consumed: bool | None = None) -> None:
        # C12: engine trộn InputError và ValueError
        if isinstance(exc, InputError):
            code, detail = exc.code, exc.detail
        else:
            code, detail = "AF_ADAPTER_INVALID", str(exc)
        status = self._ASSISTANT_STATUS.get(code, HTTPStatus.UNPROCESSABLE_ENTITY)
        extra = None
        if code == "AF_WRITE_PARTIAL":
            # C9: phân biệt "chưa ghi gì" với "đã tiêu token, kết quả không xác định"
            burned = bool(consumed)
            extra = {"approvalConsumed": burned, "written": None if burned else False, "retryable": not burned}
        self._error(status, code, detail, extra=extra)
```

Mã **mới** do adapter bịa ra phải ghi vào bảng (mục 4.5) — không được trùng với mã engine.

> **Lưu ý cho codex:** `_error()` đặt `close_connection = True`. Sau lỗi `AF_WRITE_PARTIAL`, pane phải mở lại kết nối ở request kế tiếp — `fetch` tự làm việc này, nhưng không được dùng chung một `AbortController` đã abort.

### 4.5 Bảng mã lỗi adapter (mới, không có trong engine)

| Mã | HTTP | Nghĩa |
|---|---|---|
| `ASSISTANT_ROOT_INVALID` | 400 | `root` không tuyệt đối / không tồn tại / không phải thư mục |
| `AF_STAGE_INVALID` | 409 | Gọi sai thứ tự bước (ví dụ `/preview` khi chưa `frozen`) |
| `AF_UNDERSTAND_INVALID` | 409 | Gói `ValueError` của WL2 |
| `AF_ADAPTER_INVALID` | 422 | Gói `ValueError` không phân loại được |
| `ASSISTANT_WORKBOOK_REQUIRED` | 400 | `/apply` thiếu `workbookBase64` |
| `AF_APPROVAL_MISSING` | 409 | `/apply` khi chưa `/approvals` |

---

## 5. Hợp đồng task pane

### 5.1 Quyết định D1 — **thay** nội dung tab `Trợ lý`, không thêm tab thứ ba

Tab bar **giữ nguyên 2 tab** `Trợ lý` · `PQ_Code-M`. Luồng WL1–WL7 vào **chính tab Trợ lý**, thay chỗ UI tư vấn Codex.

**Không phải sửa `switchTab()`, không thêm `tab-button`, không sửa `bindEvents` phần tab.** Đây là lý do phương án này rẻ hơn phương án tab thứ ba.

#### Giữ / bỏ / thêm

| Card hiện có (`taskpane.html`) | Xử lý | Ghi chú |
|---|---|---|
| `01 · Workbook` — `workbook-name`, `active-sheet`, `schema-summary`, `api-version`, `workbook-message`, `refresh-button` | **GIỮ NGUYÊN** | Đây là trạng thái kết nối Excel; vẫn cần và vẫn hữu ích. `refreshWorkbook()` giữ nguyên |
| `02 · Yêu cầu` — `#prompt`, `#prompt-count` | **GIỮ** 2 id này, **đổi nhãn + placeholder** | Ô đề bài là đầu vào thật của `/brief` |
| `02 · Yêu cầu` — `#analyze-button` | **BỎ**, thay bằng `flow-analyze-button` | Nút cũ gọi Codex advice; nút mới gọi `/understand` + `/brief` |
| `03 · Kế hoạch` — `plan-section`, `plan-title`, `plan-status`, `plan-summary`, `analysis-notes`, `warning-list`, `code-section`, `operation-list`, `code-list` | **BỎ TOÀN BỘ** | Đây là "chỉ trả đề xuất" mà anh/chị muốn bỏ |
| `04 · Preview` — `preview-section`, `preview-title`, `preview-label`, `before-table` | **BỎ TOÀN BỘ** | Thay bằng before/after thật của WL5 (`flow-*`) |
| `05 · Duyệt` — `approval-section`, `approval-title`, `approval-check`, `apply-button`, `apply-progress` | **BỎ TOÀN BỘ** | Thay bằng duyệt tường minh của WL6 |
| `06 · Runtime` — `result-section`, `result-title`, `runtime-badge`, `copy-path`, `excel-version`, `reconcile-status`, `runtime-table` | **BỎ TOÀN BỘ** | Đường `/api/excel/apply` + copy file không còn lộ ra UI |
| `#formula-list-separator` (ngoài tab) | **BỎ** | Chỉ dùng cho advice |
| `#codex-status` (header) | **BỎ** | Sau khi bỏ advice, không còn gì để báo. Giữ `#connection-badge` |
| `#error-panel` / `#error-code` / `#error-detail` | **GIỮ NGUYÊN** | Dùng chung, vẫn cần |
| — | **THÊM** 8 card mới S0–S6 | Bảng ở 5.2 |

#### Hàm JavaScript bị xoá (đều thuộc riêng advice flow)

`analyze()` · `applyPlan()` · `renderPlan()` · `renderOperations()` · `renderCodeBlocks()` · `renderCodeCard()` · `renderRuntime()` · `updateApplyState()` · `invalidatePlan()`

Kiểm chứng "thuộc riêng advice flow": `renderCodeBlocks` chỉ được gọi từ `renderPlan` (taskpane.js:662); `renderCodeCard` chỉ từ `renderOperations` (:611) và `renderCodeBlocks` (:620); `renderRuntime` chỉ từ `applyPlan` (:808). Không hàm nào phục vụ tab PQ.

Field `state.plan` và `state.codexAvailable` cũng bỏ (kiểm lại `setBusy` dòng 131 và `bootstrap` dòng 291-303).

> **Hệ quả phải xử lý, không được bỏ qua:** xoá các hàm trên sẽ làm đỏ **4** script JS test. Bảng thay thế hành vi bắt buộc ở **mục 7.3.1** — không được xoá test mà không có case giữ hành vi (AGENTS.md).

### 5.2 DOM trong `#tab-assistant`

Dùng lại đúng convention hiện có: `section.card.hidden` + `p.step` + `h2` có id cho `aria-labelledby`. **Mọi card mới bắt đầu `hidden`**, chỉ render function mở. Đánh số tiếp từ `01 · WORKBOOK` cho liền mạch.

| Card | ID section | Các ID con | Nội dung / người ghi |
|---|---|---|---|
| 01 · Workbook | (giữ nguyên) | `workbook-name`, `active-sheet`, `schema-summary`, `api-version`, `workbook-message`, `refresh-button` | không đổi |
| **02 · Nguồn dữ liệu** (S0) | `flow-source-section` | `flow-root-input` | `input[type=text]` — đường dẫn gốc tuyệt đối |
| | | `flow-root-button` | "Gắn thư mục" → `/session` |
| | | `flow-root-label` | `span` — `rootLabel` trả về |
| | | `flow-add-csv` / `flow-add-xlsx` / `flow-add-folder` | "Thêm CSV" / "Thêm Excel" / "Thêm thư mục" |
| | | `flow-path-input` | `input[type=text]` — locator tương đối so với root |
| | | `flow-add-workbook` | "Thêm workbook đang mở" → `flowReadOpenWorkbook()` |
| | | `flow-source-status` | `p.hint[aria-live=polite]` |
| | | `flow-source-list` | danh sách source: tên · type · hash rút gọn |
| | | `flow-navigator` | mỗi table một `input[type=checkbox]` + `tên · N dòng · M cột` (AF-GD-002) |
| | | `flow-rename-list` | `div.notice.notice-warning` — bảng trùng tên |
| | | `flow-csv-options` | mỗi source mơ hồ: `select` delimiter/encoding/header (AF-GD-003) |
| | | `flow-ingest-button` | "Nạp nguồn" → `/ingest` |
| **03 · Đề bài** (S0b) | `flow-prompt-section` | `#prompt` (tái dùng, **`maxlength` 4 000 → 20 000**) | giới hạn engine là 20 000 (`assistant_brief.py:96`) |
| | | `#prompt-count` (tái dùng) | hiển thị `len / 20000` |
| | | `flow-analyze-button` | "Phân tích" → `/understand` rồi `/brief` (1 nút, 2 call) |
| **04 · Cách hiểu** (S1) | `flow-understand-section` | `flow-understand-toggle` | `button.button-ghost[aria-expanded=false]` — **thu gọn mặc định** |
| | | `flow-understand-summary` | `pack.id` · fact/dim · số quan hệ · cảnh báo cột ngày |
| | | `flow-understand-body` | `div.hidden` — thân thu gọn |
| | | `flow-role-list`, `flow-relationship-list`, `flow-assumption-list` | vai cấu trúc, dây nối `A ──98%──► B · N:1`, Assumption Ledger |
| **05 · Decision Brief** (S2) | `flow-brief-section` | `flow-contract` | `outputContract`: grain/measure/kỳ/tiền tệ |
| | | `flow-findings` | finding: chữ + `value` (**đọc từ field, không tự tính**) |
| | | `flow-subproblems` | mỗi SP: câu hỏi + chip status + radio A/B + hệ quả |
| | | `flow-scenarios`, `flow-insights` | 2 kịch bản A/B + `delta`; insight 2 loại |
| | | `flow-freeze-blockers` | `div.notice.notice-warning` |
| | | `flow-freeze-button` | "Chốt & tạo Spec" → `/decisions` rồi `/spec` |
| **06 · Execution Spec** (S4) | `flow-spec-section` | `flow-spec-summary` | `dl.facts` — `spec.id` · fingerprint rút gọn · `createdAt` · nhãn |
| | | `flow-step-list` | step: `st_NN` · kind · label · status · guard |
| | | `flow-preview-button` | "Chạy preview" → `/preview` |
| **07 · Preview + Reconcile** (S5) | `flow-preview-section` | `flow-reconcile-banner` | `div[role=status]` — pass/fail + từng check |
| | | `flow-reconcile-facts` | `dl.facts` — rowsIn→rowsOut · control total · bridge op/fx/total |
| | | `flow-before-table` / `flow-after-table` | `div.table-scroll` — `renderTable()` |
| | | `flow-approve-check` | `input[type=checkbox]` — xác nhận tường minh |
| | | `flow-approve-button` | "Duyệt" → `/approvals` |
| | | `flow-apply-button` | "Ghi sheet kết quả" → `/apply` + Office.js |
| **08 · Kết quả + Decision Record** (S6) | `flow-result-section` | `flow-result-summary` | `dl.facts` — sheet · `written` · `workbookSaved:false` |
| | | `flow-label-badges` | **mọi** nhãn: `assumed` / `unverified` / `out_of_scope` / `stale` |
| | | `flow-delta` | `dl.facts` — rowsIn/rowsOut · null ± · dupe ± · cột đổi |
| | | `flow-stale-banner` | `div.notice.notice-warning` — khi `staleCheck` khác null |
| | | `flow-record-download` | "Tải Decision Record" (Blob JSON) |
| | | `flow-reset-button` | "Bắt đầu lại" → `/reset` |

`#prompt` được tái dùng nên `updatePromptCount()` và handler `input` hiện có vẫn phải gắn; chỉ đổi đếm từ 4 000 sang 20 000.

**Bắt buộc khi thêm card mới** (chỗ dễ hỏng nhất, có nguy cơ hồi quy):

1. Thêm `setHidden("flow-*")` vào `invalidateSessionBoundState()` (dòng 241-275) để session mới không giữ dữ liệu cũ.
2. `refreshWorkbook()` (dòng 511-529) hiện gọi `invalidatePlan(...)` — thay bằng `resetFlowView(...)` để đổi workbook là reset luồng.
3. Không dùng `innerHTML` cho dữ liệu; chỉ `textContent` hoặc `replaceChildren()`.
4. Mọi nút mới vào `updateFlowButtons()`; gọi từ `setBusy()` (dòng 128-136).
5. Không `window.confirm` (`ASSISTANT_FLOW_SPEC.md` §16.7).


### 5.3 State của pane

Thêm một nhánh, **không** sửa 38 field hiện có:

```js
state.flow = {
  stage: "new",
  flowCapability: false,       // từ capabilities.assistantFlowV1
  rootLabel: "",
  snapshot: null,              // bản rút gọn từ /ingest
  sources: [], tables: [], selectedTableIds: new Set(),
  csvOptions: [], requiresRename: [], errors: [], warnings: [],
  bindings: [],                // checkbox DOM ↔ table id
  understand: null, brief: null, decisions: null, spec: null,
  preview: null, reconciliation: null, approval: null,
  applyResult: null, delta: null, record: null,
  busy: false,
};
```

Không đặt `state.flow` vào `state.busy` toàn cục — luồng có nhịp riêng, tránh khoá nhầm nút bấm của tab `PQ_Code-M`.

### 5.4 Hàm JavaScript cần có

```js
// bootstrap
function flowCapabilityAvailable()                       // gate theo capabilities.assistantFlowV1
async function flowLoadState()                           // /state khi mở tab hoặc reload pane

// S0
async function flowBindRoot()                            // /session
async function flowIngest(kind)                          // /ingest (csv|xlsx|folder|workbook)
async function flowReadOpenWorkbook()                    // Office.js full values (mục 6.2)
async function flowAddOpenWorkbook()                     // flowReadOpenWorkbook → /ingest payload
function renderFlowSources()  function renderFlowNavigator()
function renderFlowCsvOptions() function renderFlowConditions()

// S0b + S1 — MỘT nút "Phân tích" gọi 2 call liên tiếp
async function flowAnalyze()                             // /understand rồi /brief
async function flowUnderstand()                          // chỉ /understand (dùng lại được)
function renderFlowUnderstand()

// S2
function renderFlowBrief()   function renderFlowSubProblems()
function collectFlowChoices()                            // đọc radio → {choices, acknowledgements}
async function flowFreeze()                              // /decisions → /spec (2 call, 1 nút)

// S4/S5
async function flowPreview()                             // /preview
function renderFlowSpec()    function renderFlowPreview() function renderFlowReconcile()

// S6
async function flowApprove()                             // /approvals
async function flowApply()                               // exportWorkbookBase64 → /apply → Office.js write → verify
function renderFlowResult()  function flowDownloadRecord()
function updateFlowButtons() function resetFlowView()

// tiện ích
function flowError(error)                                // showError + giữ trạng thái
function isoDateLocal(date)                              // mục 6.3
function flowNowIso()                                    // new Date().toISOString() cho *At (có tz)
```

### 5.5 Máy trạng thái → hiển thị

| `stage` | Card mở | Nút bị khoá | Ghi chú |
|---|---|---|---|
| `new` | 02 Nguồn | 03 Đề bài trở đi | |
| `ingest_blocked` | 02 Nguồn | 03 Đề bài | hiện `errors`/`requiresRename`/`csvOptions` |
| `ingested` | 02, 03 | `flow-analyze-button` nếu prompt rỗng | |
| `understood` | +04 Cách hiểu | — | hiện cảnh báo `briefRequirements.dateColumn` nếu thiếu |
| `briefed` | +05 Brief | `flow-freeze-button` nếu `freezeBlocked` | A/B bắt buộc chọn đủ |
| `decided` | +05 | — | hiện `checklist` còn lại |
| `frozen` | +06 Spec | `flow-preview-button` nếu có step `status!=="ok"` | |
| `previewed` | +07 Preview | `flow-approve-button` nếu `approveBlocked` | banner đỏ + lý do |
| `reconciled` | +07 | `flow-approve-button` mở | checkbox xác nhận còn phải tick |
| `approved` | +07 | `flow-apply-button` mở | hiện `approvalId` |
| `applied` | +08 Kết quả | — | |
| `recorded` | +08 | — | hiện delta + nhãn + nút tải record |

Mỗi card gắn `data-state="<stage>"` để test JS bám vào (`ASSISTANT_FLOW_SPEC.md` §16.8).

### 5.6 Quy tắc copy — chỗ dễ nói sai sự thật

Vì C1 (không AI), các câu sau **bị cấm** trong tab Trợ lý sau khi thay nội dung:

| ❌ Cấm | ✅ Dùng |
|---|---|
| "AI đã hiểu workbook của bạn" | "Engine đã đo cấu trúc: 7 bảng, 5 quan hệ" |
| "AI đề xuất" | "Domain pack `fin-pl-v1` đề xuất" |
| "AI nghĩ rằng" / "có thể đúng" | chip status: `Đã xác nhận` / `Suy ra` / `Giả định` / `Chưa rõ` / `Thiếu dữ liệu` / `Xung đột` |
| "Đã xác minh" cho suy luận | chỉ `unverified` / `assumed`; `verified` chỉ khi `status==="verified"` do engine gán |
| "Phân tích mọi workbook" | badge kịch bản: `P&L Actual vs Budget` hoặc `Doanh số theo khu vực` |

Chip status phải có **icon + chữ + màu**, không chỉ màu (spec §16.9). Dùng `LUCIDE_ICONS` sẵn có, không CDN, không SVG người dùng.

Khi `pack.genericMode === true`, hiện nguyên văn `pack.notice`: *"Không có domain pack: mô hình generic kém chính xác hơn; cần người dùng rà soát nghĩa nghiệp vụ."*

Khi `executableOptionId === "A"`, cạnh option B ghi: *"B được ghi nhận vào quyết định nhưng bản này chưa có recipe thực thi cho B; chọn B sẽ dừng ở bước Preview."*

---

## 6. Đọc workbook qua Office.js

### 6.1 Vì sao không dùng `readWorkbook()` hiện có

`readWorkbook()` (taskpane.js:334-438) lấy **mẫu 20 dòng** (`deterministicCheckRowOffsets`) và `core/workbook_snapshot.py` chặn ở `MAX_ROWS=20`, `MAX_COLUMNS=200`, `MAX_CELL_CHARS=1000`. C6 **từ chối** payload mẫu. Nên phải có hàm đọc **riêng cho luồng**, không thay `readWorkbook()` bằng nó.

Lý do vẫn giữ `readWorkbook()`: sau khi bỏ advice UI, tab **PQ_Code-M** vẫn dùng nó (`proposePQ`, `previewPQ`, `selectedPQSource`, và `taskpane_usedrange.js` kiểm shape of sheets). `readWorkbook()` chỉ được **sửa lỗi Total Row** (P0-2b, mục 11.3) — cùng một bản sửa, hai đường đọc khác mục đích:

| Hàm | Ai dùng | Trả gì | Giới hạn |
|---|---|---|---|
| `readWorkbook()` | tab **PQ_Code-M** | mẫu 20 dòng + `totalRows/totalColumns` | `MAX_ROWS=20` phía server snapshot |
| `flowReadOpenWorkbook()` | tab **Trợ lý** (luồng) | **toàn bộ** giá trị | `FLOW_MAX_CELLS = 400000` phía pane |

### 6.2 `flowReadOpenWorkbook()` — đọc full values

```js
async function flowReadOpenWorkbook() {
  return Excel.run(async (context) => {
    const workbook = context.workbook;
    const sheets = workbook.worksheets;
    sheets.load("items/name");
    await context.sync();

    const selections = [];              // {sheet, name, header, rows, table}
    for (const sheet of sheets.items) {
      sheet.tables.load("items/name");
    }
    await context.sync();

    for (const sheet of sheets.items) {
      const tables = sheet.tables.items;
      if (tables.length > 0) {
        for (const table of tables) {
          // SỬA DEFECT FINDING 3: data body KHÔNG có header và KHÔNG có totals row
          const body = table.getDataBodyRange();
          const head = table.getHeaderRowRange();
          body.load("values,rowCount,columnCount");
          head.load("values");
          selections.push({sheet: sheet.name, name: table.name, body, head, table: true});
        }
      } else {
        const used = sheet.getUsedRangeOrNullObject(true);
        used.load("values,rowCount,columnCount,isNullObject");
        selections.push({sheet: sheet.name, name: sheet.name, body: used, table: false});
      }
    }
    await context.sync();

    const result = [];
    for (const sel of selections) {
      if (sel.body.isNullObject || sel.body.rowCount === 0) continue;
      const header = sel.table
        ? sel.head.values[0].map((v, i) => flowHeaderCell(v, i))
        : (sel.body.values[0] || []).map((v, i) => flowHeaderCell(v, i));
      // dòng đầu của usedRange là header; của DataBodyRange là dữ liệu
      const rawRows = sel.table ? sel.body.values : sel.body.values.slice(1);
      const totalRows = sel.table ? sel.body.rowCount : Math.max(0, sel.body.rowCount - 1);
      result.push({
        sheet: sel.sheet, name: sel.name, table: sel.table,
        header, rows: rawRows.map((row) => row.map(flowCell)), totalRows,
        totalColumns: header.length,
      });
    }
    return result;
  });
}

function flowHeaderCell(value, index) {
  const text = value === null || value === undefined || value === "" ? "" : String(value).trim();
  return text || columnLetter(index);       // header rỗng → chữ cái cột, KHÔNG gửi ""
}

function flowCell(value) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return isoDateLocal(value);   // C7
  if (typeof value === "number") return String(value);      // JS repr ngắn nhất, khớp str() Python
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  return String(value);
}
```

**Ba lỗi phải tránh trong hàm này** (đều là defect đã biết, đừng lặp lại):

1. Dùng `table.getRange()` thay vì `getDataBodyRange()` ⇒ totals row thành dữ liệu (finding 3).
2. Không lọc header rỗng/không phải chuỗi ⇒ `add_open_workbook` từ chối ("header is invalid") và `readWorkbook` hiện tại cũng bị `INVALID_WORKBOOK` (`core/workbook_snapshot.py:20-23`).
3. Không chặn số cột/dòng phía client ⇒ payload vượt `MAX_ASSISTANT_INGEST_JSON_BYTES`.

### 6.3 `isoDateLocal()` — bẫy lệch một ngày

```js
function isoDateLocal(date) {
  const y = date.getFullYear();                       // PHẢI dùng getter LOCAL
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
```

**`date.toISOString().slice(0,10)` là SAI** ở UTC+7: ô `2026-09-01` đọc thành `Date` nửa đêm giờ máy ⇒ `toISOString()` cho `2026-08-31T17:00Z` ⇒ gửi `"2026-08-31"`. Sai một ngày làm `_period()` tính sai kỳ ⇒ mọi số FIN sai. Đây là test bắt buộc (mục 7.2, F-JS-02).

### 6.4 Chặn phía client trước khi gửi

```js
const FLOW_MAX_ROWS = 100000, FLOW_MAX_COLUMNS = 512, FLOW_MAX_CELLS = 400000;
```

Trước khi POST `/ingest`, kiểm tổng `rows.length` và `rows.length * header.length`. Vượt ⇒ từ chối **ở pane** với thông báo rõ (chọn vùng nhỏ hơn) thay vì timeout hoặc 413 từ server. Ghi rõ số đo thực tế để người dùng hiểu.

### 6.5 Ghi kết quả bằng Office.js (`flowApply`)

`/apply` trả `result.columns` + `result.rows` (giá trị engine đã read-back). Pane ghi đúng các giá trị đó, **không tự tính lại**:

1. `exportWorkbookBase64()` (đã có, dòng 761) → gửi kèm `/apply`.
2. Nhận `apply.target.sheet` (`PnL_Result`/`Sales_Result`) + `result`.
3. Mở `Excel.run`; nếu sheet đích đã tồn tại ⇒ **dừng** (engine cũng đã chặn: "Tên sheet kết quả đã tồn tại").
4. `worksheets.add(name)`; `getRangeByIndexes(0,0,rows.length,columns.length)`; `.values = [columns, ...rows]`; gắn marker vào ô cuối.
5. `context.sync()`; đọc lại vùng vừa ghi, tính digest giống `resultDigest` và so. Lệch ⇒ báo `AF_WRITE_PARTIAL` mức UI, **không** tuyên bố thành công.
6. **Không** `workbook.save()`, **không** ghi sheet nguồn (AF-AP-003).

Tham chiếu pattern có sẵn: `applyPQValuesToOpenWorkbook()` (taskpane.js:3581), và test `tests/taskpane/taskpane_pq_write.js`.

### 6.6 Khi nguồn là CSV/thư mục (không có workbook)

Luồng vẫn chạy hết WL1–WL5. WL6 cần bytes workbook: dùng `exportWorkbookBase64()` của workbook đang mở bất kỳ (Excel luôn có một workbook mở). Nếu `Office.context.document.getFileAsync` không khả dụng, `/apply` trả `ASSISTANT_WORKBOOK_REQUIRED` và UI nói rõ: *"Bản này chỉ ghi được vào workbook đang mở. Hãy mở một workbook và thử lại; kết quả Preview/Reconcile vẫn còn nguyên."*

---

## 7. Kế hoạch test

### 7.1 Test Python (HTTP, không cần Excel)

File mới `tests/integration/test_assistant_flow_api.py`. Dùng harness sẵn có của `tests/integration/test_excel_addin_server.py` (server thật, port thật, token thật).

| Case ID | Kiểm gì |
|---|---|
| `test_fin_folder_flow_reaches_record_with_expected_dimensions` | `/session` root `tests/fixtures/assistant/tp-fin` → `/ingest` 7 CSV → `/understand` → `/brief` → `/decisions` → `/spec` → `/preview` → `/approvals` → `/apply` (workbook = fixture xlsx) → assert: 23×9, 14 steps, `reconciliation.passed`, `bridge.passed`, `record.hash` recompute được, `workbookSaved is False` |
| `test_sales_generic_flow_reports_not_applicable_bridge` | TP-SALES: 4×4, 10 steps, `pack.genericMode true`, `bridge.applicable false` |
| `test_stage_order_is_enforced` | `/preview` khi `stage=="new"` ⇒ `AF_STAGE_INVALID`; `/apply` khi chưa approve ⇒ `AF_APPROVAL_MISSING` |
| `test_policy_b_is_blocked_at_preview` | chọn B ⇒ `/preview` `AF_POLICY_UNSUPPORTED`, `stage` vẫn `frozen` (C3) |
| `test_ambiguous_csv_returns_options_and_resolves` | fixture CSV delimiter mơ hồ ⇒ `ingest_blocked` + `csvOptions[].candidates`; chọn lại ⇒ `ingested` |
| `test_duplicate_table_names_block_snapshot` | 2 bảng trùng tên ⇒ `requiresRename`, không có `snapshot` |
| `test_ingest_rejects_sample_only_and_totals_mismatch` | payload `sampleOnly:true` ⇒ 400; `totalRows` sai ⇒ 400 (C6) |
| `test_csv_source_change_between_preview_and_apply_marks_stale` | đổi 1 byte CSV sau `/preview` ⇒ `/apply` `AF_SPEC_STALE` |
| `test_apply_partial_write_is_reported_as_not_retryable` | `fail_after_sheet=True` qua tham số test ⇒ `AF_WRITE_PARTIAL` với `approvalConsumed:true`, `retryable:false` |
| `test_approval_cannot_be_replayed` | `/apply` 2 lần ⇒ lần 2 `AF_SPEC_STALE` (C2/C9) |
| `test_reset_clears_store_and_closes_session` | `/reset` ⇒ `stage:"new"`, `_assistant_ingest` không còn, `/preview` tiếp theo ⇒ `AF_STAGE_INVALID` |
| `test_absolute_root_and_traversal_are_rejected` | root tương đối ⇒ 400; `path:"../x.csv"` ⇒ `AF_INGEST_FAILED` |

Case bắt buộc thêm cho defect P0:

| Case ID | Kiểm gì |
|---|---|
| `test_assistant_behavior_guards.…cardinality…` | test **đã có**, phải chuyển từ đỏ sang xanh sau P0-1. Giữ nguyên ID |
| `test_brief_accepts_every_catalog_cardinality` | thêm mới: cả 4 giá trị `1:1/1:N/N:1/N:N` được chấp nhận ⇒ guard không quá tay |

### 7.2 Test JavaScript (fake host, không cần Excel)

File mới `tests/taskpane/taskpane_assistant_flow.js`, theo **đúng** pattern `taskpane_live_analyze.js`: `vm.runInNewContext` + `globalThis.__x = x` + `Map` DOM stub + `fetch` recorder + `console.log("… passed")`.

| Case | Kiểm gì |
|---|---|
| F-JS-01 | Nút "Phân tích" gọi `/api/assistant/understand` **rồi** `/api/assistant/brief`; khi `capabilities.assistantFlowV1 !== true` thì nút bị khoá và không có request nào |
| F-JS-02 | `isoDateLocal(new Date(2026,8,1))` === `"2026-09-01"` **và** khác `toISOString().slice(0,10)` khi `TZ=Asia/Saigon`. Test chống lệch ngày (C7) |
| F-JS-03 | `flowReadOpenWorkbook()` gọi `getDataBodyRange()`/`getHeaderRowRange()`, **không** gọi `getRange()`; `totalRows` = `rowCount` của data body (chống finding 3) |
| F-JS-04 | Header rỗng → chữ cái cột; `totalColumns` = `header.length`; payload không chứa `sampleOnly` |
| F-JS-05 | Chọn B ở một SP ⇒ `/preview` trả `AF_POLICY_UNSUPPORTED` ⇒ `flow-approve-button` vẫn khoá và banner hiện nguyên văn detail |
| F-JS-06 | `reconciliation.passed === false` ⇒ `flow-approve-button` khoá, `flow-reconcile-banner` có `role=status` và nội dung lý do |
| F-JS-07 | `/apply` trả `AF_WRITE_PARTIAL` + `approvalConsumed:true` ⇒ KHÔNG hiện "Đã ghi", hiện cảnh báo partial/unknown và không cho retry (chống finding 5) |
| F-JS-08 | `apply.target.sheet` `PnL_Result` — pane tạo worksheet mới, ghi đúng `result.rows`, **không** `save()`, **không** ghi sheet nguồn |
| F-JS-09 | Khôi phục sau reload: `/state` trả `stage:"frozen"` ⇒ mở đúng card 02..06, không gọi lại engine |
| F-JS-10 | Số liệu trên UI lấy từ field `value` của engine, không có phép tính nào trong JS cho các con số tài chính |
| **F-JS-11** | **Nút "Phân tích" đọc lại workbook ngay trước khi gửi; nếu lần đọc lỗi thì KHÔNG gửi snapshot cũ và `state.flow` giữ `stage` cũ** ← *thay hành vi của `taskpane_live_analyze.js`* |
| **F-JS-12** | **Ctrl+Enter trong `#prompt` chỉ kích hoạt khi `flow-analyze-button` đang bật; `isComposing`/`repeat` bị bỏ qua** ← *thay hành vi của `taskpane_shortcut.js`* |
| **F-JS-13** | **Trong `#tab-assistant` không tồn tại phần tử nào của advice UI** (`plan-section`, `code-list`, `operation-list`, `approval-section`, `result-section`, `apply-button`, `analyze-button`, `formula-list-separator`) và `renderPlan`/`renderCodeBlocks` không tồn tại trong bundle ← *thay hành vi của `taskpane_code_blocks.js`* (khoá bất biến "đã bỏ đề xuất", xem 7.3.1) |
| **F-JS-14** | **`flowApply()` không gọi `/api/assistant/apply` khi chưa tick `flow-approve-check`** ← *thay assertion "main assistant apply still requires its explicit approval checkbox" đang nằm trong `taskpane_pq.js`* |

Đăng ký: thêm 1 method vào `tests/taskpane/test_taskpane_js.py`:

```python
@unittest.skipUnless(shutil.which("node"), "Node.js is not available")
def test_assistant_flow_stage_gating_dates_and_partial_write(self) -> None:
    script = Path(__file__).with_name("taskpane_assistant_flow.js")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=20, check=False)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("passed", result.stdout)
```

### 7.3 Đăng ký `tests/required_cases.json`

`tools/run_checks.py:56-61` chặn nếu một ID đã khai báo mà biến mất. Nên **mọi case mới phải thêm ID đầy đủ**:

```
tests.integration.test_assistant_flow_api.AssistantFlowApiTests.test_fin_folder_flow_reaches_record_with_expected_dimensions
tests.integration.test_assistant_flow_api.AssistantFlowApiTests.test_sales_generic_flow_reports_not_applicable_bridge
… (12 case mục 7.1)
tests.taskpane.test_taskpane_js.TaskpaneJavaScriptTests.test_assistant_flow_stage_gating_dates_and_partial_write
```

Đó là **13** ID Python mới (12 case mục 7.1 + 1 case guard biên cardinality) và **1** ID JS mới. Nhưng vì P4 **xoá** advice UI (5.1), phải xử lý **4 case JS bị ảnh hưởng** — bảng ở 7.3.1.

Xoá case cũ chỉ được phép khi có case thay thế giữ nguyên hành vi (AGENTS.md). Riêng `test_invalid_relationship_cardinality_is_rejected_before_brief` **phải giữ nguyên ID** và phải chuyển từ đỏ sang xanh — đó là bằng chứng P0-1.

#### 7.3.1 Bốn case JS bị P4 làm đỏ — thay thế bắt buộc

Xoá advice UI sẽ làm đỏ 4 script. **Không được xoá test không có case thay thế.** Bảng dưới là ánh xạ bắt buộc; cột "case thay thế" là nơi hành vi được giữ lại.

| Script bị ảnh hưởng | Hành vi đang được giữ | Case thay thế | Xử lý file |
|---|---|---|---|
| `taskpane_live_analyze.js` | Phân tích **đọc lại** workbook ngay trước khi gửi; đọc lỗi thì **không** gửi snapshot cũ, `state` về rỗng, mã `OFFICE_READ_FAILED` | **F-JS-11** | viết lại thành `taskpane_assistant_flow.js`; **xoá file cũ** cùng case ID cũ |
| `taskpane_shortcut.js` | Ctrl+Enter chỉ chạy khi nút đang bật; bỏ `isComposing`/`repeat` | **F-JS-12** | gộp vào `taskpane_assistant_flow.js`; **xoá file cũ** |
| `taskpane_code_blocks.js` | Tách văn xuôi khỏi code sao chép được | **F-JS-13** (đảo thành bất biến âm: advice UI **không còn tồn tại**) | **xoá file cũ**; xem lý do dưới |
| `taskpane_pq.js` (1 assertion, dòng 174-177) | Apply của assistant **bắt buộc** tick xác nhận tường minh | **F-JS-14** | **xoá đúng 3 dòng** 174-176 + assert 177 khỏi `taskpane_pq.js`; phần còn lại của file giữ nguyên |
| `test_assistant_flow_api.py` bootstrap stages | Danh mục stage v2 đóng | `test_all_routes_registered_with_central_authorization_and_slots` giữ kiểm danh mục chính xác; HTTP journey kiểm bàn giao/receipt/partial | Thay kỳ vọng 9 stage bằng danh sách 11 stage có `handoff` và `partial`, không chỉ nới số lượng |
| `test_excel_addin_server.py::test_taskpane_assets_and_bootstrap_capabilities` | HTML/JS được phục vụ, trạng thái kết nối trước thanh tab và các capability/đường PQ giữ nguyên | Cùng test kiểm chính xác 8 card, thứ tự card, connection badge trước thanh tab, helper XML tải trước taskpane và advice DOM không quay lại; F-JS-13 giữ toàn bộ bất biến âm | Thay các assertion về `formula-list-separator`/`codex-status`/toolbar advice bằng hợp đồng UI v2; giữ các assertion PQ, CSP và capability còn lại |
| `taskpane_advanced_policy.js`, `taskpane_pq.js`, `taskpane_pq_typed.js`, `taskpane_usedrange.js` | Các hành vi policy/PQ/used-range hiện có; DOM giả cần mô phỏng status chip có icon | Giữ nguyên case ID và toàn bộ assertion hành vi; bổ sung DOM giả `createElement`/`setAttribute`/`replaceChildren` đúng chức năng | Chỉ mở rộng fake host cho API DOM mà UI 8 card dùng, không bỏ hoặc nới assertion sản phẩm |

**Vì sao F-JS-13 là thay thế hợp lệ cho `taskpane_code_blocks.js`.** Case cũ bảo vệ một tính năng ("hiển thị đề xuất công thức có thể sao chép") mà chính P4 xoá bỏ. Giữ nguyên case cũ là giữ một khẳng định sai. Nhưng không được để trống chỗ: bất biến mới **khoá lại việc đã bỏ**, và đó là biên sản phẩm thật — *"AI advice does not grant approval"* / không có Apply công thức tự do (AGENTS.md). F-JS-13 kiểm rằng không id nào của advice UI quay lại, và `renderPlan`/`renderCodeBlocks` không còn trong bundle. Nếu ai đó vô tình khôi phục UI đề xuất, test đỏ.

**Việc phải làm trong `tests/required_cases.json`:**

| Hành động | ID |
|---|---|
| Xoá (kèm thay thế ở trên) | `…test_analyze_reads_live_workbook_and_blocks_stale_snapshot_on_failure` · `…test_ctrl_enter_analyzes_only_when_button_is_enabled` · `…test_text_and_copyable_code_are_rendered_separately` |
| Giữ nguyên | `…test_pq_preview_copies_result_and_source_apply_is_separately_confirmed` (chỉ sửa nội dung file) · `…test_used_range_fallback_without_excel_table` (không đổi) |
| Thêm | `…test_assistant_flow_stage_gating_dates_and_partial_write` |

Tổng sau P4: **850 − 3 + 1 (JS) + 13 (Python) = 861**. Con số này phải khớp khi chạy `py tools/run_checks.py fast --list | Select-Object -Last 1`.

> **Chưa biết trước thì đừng đoán:** nếu P4 phát sinh thêm test đỏ ngoài 4 cái trên, ghi lại và bổ sung dòng vào bảng này **trước** khi sửa test — không được nới assertion cho xanh.

### 7.4 Gate và runbook cho người kiểm thử

**Gate tự động:**

```powershell
py tools/run_checks.py fast        # phải xanh: 13 case Python mới + 1 script JS mới, và 3 case cũ đã xoá có thay thế
node --check pbip_assistant/excel_addin/taskpane.js
py -m unittest tests.contracts.test_assistant_e2e -v     # engine không hồi quy
```

**Test tay trong Excel (10 phút, sau khi implement xong P1–P4):**

1. `py -m pbip_assistant.excel_addin_server` — giữ cửa sổ mở, ghi lại PORT.
2. Mở task pane — vẫn **2 tab** `Trợ lý` · `PQ_Code-M`. Tab Trợ lý **không còn** nút "Phân tích workbook", không còn khối "Kế hoạch đề xuất", "Preview", "Duyệt", "Runtime".
3. Dán root: `<repo>\tests\fixtures\assistant\tp-fin\source` → **Gắn thư mục**.
4. Bấm **Thêm CSV** với `GL_Actuals_2026-09.csv`; kiểm navigator hiện 1 bảng `42 dòng · 11 cột`. Thêm tiếp 6 CSV còn lại, rồi **Nạp nguồn**.
5. Nhập đề bài: *"Báo cáo P&L theo cost center, quy VND, tách FX."* → **Phân tích**.
6. Kiểm card 04 Cách hiểu: `pack: fin-pl-v1` (không phải generic), có ≥5 quan hệ, không có cảnh báo thiếu `PostingDate`.
7. Kiểm card 05 Brief: ≥5 SP, mỗi SP có A/B + hệ quả; có 2 scenario + delta; có insight cả hai loại.
8. Chọn A cho mọi SP không phải `missing_data`; SP `missing_data` chọn *out_of_scope*. **Chốt & tạo Spec**.
9. Kiểm card 06 Spec: 14 step cho FIN, mọi `status:ok`, không `guard`.
10. **Chạy preview**. Kiểm card 07: `rowsIn 42 → rowsOut 23`, control total khớp, bridge `Op+FX=Total` ✓, banner xanh.
11. Tick xác nhận → **Duyệt** → **Ghi sheet kết quả**.
12. Kiểm card 08: sheet `PnL_Result` xuất hiện, 23 dòng × 9 cột, có dòng marker, **nhãn `assumed`/`unverified` hiển thị**, `Workbook đã lưu: Không`. Tải Decision Record, mở JSON, `hash` khớp.
13. **Không** Save workbook. Đóng không lưu.

**Đối chứng số (dùng để phát hiện sai số, không phải để tự tính):**

| Kiểm | TP-FIN | TP-SALES |
|---|---|---|
| Kích thước kết quả | 23 × 9 | 4 × 4 |
| Số step trong Spec | 14 | 10 |
| `bridge.applicable` | `true` | `false` |
| `pack.id` | `fin-pl-v1` | `generic` + `notice` |
| `reconciliation.passed` | `true` | `true` |

**Điều bắt buộc được ghi vào biên bản test:** kết quả trên là **engine synthetic + fake host**, **không** phải Office.js/Excel live end-to-end. Muốn đóng gate live phải chạy `tests/live/README.md` harness và ghi lại revision, layer, pass/fail, elapsed, mã lỗi, revision/step, kích thước kết quả, fingerprint nguồn.

---

## 8. Phân kỳ giao hàng

Mỗi pha tự đứng được: xong pha nào test được pha đó. Đây là thứ tự **bắt buộc** vì P0 là điều kiện đúng số.

| Pha | Nội dung | File | Acceptance | Test được ngay |
|---|---|---|---|---|
| **P0-1** | Guard cardinality tại biên WL2→WL3 | `assistant_brief.py` (+`assistant_understand.py`) | `test_invalid_relationship_cardinality_is_rejected_before_brief` **xanh**; 4 giá trị hợp lệ vẫn qua | `py -m unittest tests.contracts.test_assistant_behavior_guards` |
| **P0-2a** | `getDataBodyRange()` trong hàm đọc **mới** | `taskpane.js` (`flowReadOpenWorkbook`) | Không gọi `getRange()`; totals row không vào `rows` | case JS F-JS-03/04 |
| **P0-2b** | Sửa **luôn** `readWorkbook()` của tab Trợ lý + fake host | `taskpane.js`, 2–3 file fake host | Test JS mới: bảng có totals row ⇒ `totalRows` đúng; 12 script JS cũ vẫn xanh | `node tests/taskpane/taskpane_usedrange.js` + case mới |
| **P0-3** | `required_date_column()` dùng chung | `assistant_brief.py` | `_period` không còn chuỗi cứng; import được từ adapter | `py -m unittest tests.unit.test_assistant_brief` |
| **P1** | Store WL1–WL3 + 4 route + test | `assistant_session.py`, `endpoints/assistant.py`, `server.py`, `test_assistant_flow_api.py` | TP-FIN đi tới `stage:"briefed"`; TP-SALES ra `genericMode` | `py tools/run_checks.py fast` |
| **P1.5** | `tools/assistant_flow_smoke.ps1` **khung + bước 01–04** (mục 12) | `tools/assistant_flow_smoke.ps1` | `-StopAfter brief` chạy `PASS`, exit 0 | `pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter brief` |
| **P2** | WL4 + WL5 + 3 route | như trên | TP-FIN tới `stage:"reconciled"`, 14 step, `passed:true` | gate + `-StopAfter approvals` |
| **P3** | WL6 + WL7 + 2 route + **hoàn tất smoke script** | như trên + `assistant_flow_smoke.ps1` | `stage:"recorded"`, `record.hash` recompute, `workbookSaved:false`; smoke `PASS` đủ 11 bước + case âm + test parse | gate + `pwsh -File tools/assistant_flow_smoke.ps1` |
| **P4a** | **Bỏ** advice UI khỏi tab Trợ lý + gỡ code chết (5.1) | `taskpane.html`, `taskpane.js`, 4 script JS test | Danh sách giữ/bỏ ở 5.1 đúng; `node --check` sạch; 4 case ánh xạ đúng bảng 7.3.1 | `py tools/run_checks.py fast` |
| **P4b** | Thêm 8 card S0–S6 + full values + ghi Office.js | `taskpane.html`, `taskpane.js`, `taskpane_assistant_flow.js` | 14 case JS; runbook 7.4 chạy hết; smoke vẫn `PASS` | `node tests/taskpane/taskpane_assistant_flow.js` + Excel tay |
| **P5** | Traceability + tài liệu | `ASSISTANT_TRACEABILITY.md`, `CURRENT_STATUS.md` | 20 dòng `partial` được cập nhật đúng (mục 10) | review |
| **P6** | Sửa runbook (finding 7) | `tools/excel_addin/README.md` | Không còn hướng dẫn Analyze → EXCEL VERIFIED; tách 3 đường: advice / Typed-Problem Chain / fixture connector | review |
| **P7 · SAU, không găng** | Cắm Codex vào 3 seam nhãn (11.5) | `schemas/assistant_domain_pack.schema.json`, `endpoints/assistant.py`, `taskpane.*` | Nới enum nhận `llm` mà **không** đổi `understandHash` của golden; Codex không đi vào `measure_set`/`result_rows`/`build_reconciliation` | review + smoke vẫn `PASS` |

**Thứ tự test thực tế cho buổi test:** P0-1 → P0-3 → P0-2a → P1 → **P1.5 (kiểm backend bằng smoke, không cần Excel)** → P2 → P3 → **smoke `PASS` đủ** → P4 (UI) → P5/P6. Nghĩa là mọi thứ về số đã được chứng minh **trước** khi mở Excel.

**P7 nằm ngoài đường găng.** Đừng gộp Codex vào P1–P4: luồng phải chạy đúng và chứng minh được **khi chưa có AI**; thêm AI vào một luồng chưa ổn định là mất khả năng biết lỗi do đâu.

**Không** đổi version application/npm/HTTP (1.2.0) hay manifest (1.2.0.0) trong spec này — chỉ sau khi gate exact-current xanh (AGENTS.md).

---

## 9. Những gì spec này **không** hứa

Ghi rõ để không ai tuyên bố quá mức trong biên bản test:

1. **Không phải AI.** WL1–WL7 là engine tất định + domain pack biên soạn sẵn. Không có lời gọi Codex nào trong luồng. (C1)
2. **Không phải engine tổng quát.** Chỉ 2 recipe đóng: `tp-fin` (23×9) và `tp-sales` (4×4). Dữ liệu ngoài schema sẽ dừng ở WL5 với `AF_POLICY_UNSUPPORTED`/`AF_PREVIEW_INVALID` — đó là hành vi đúng, không phải bug. (C4)
3. **Không thực thi được option B.** Chọn B chỉ được ghi vào Decision Record. (C3)
4. **Không có Apply công thức tự do.** Sau P4a, tab Trợ lý **không còn** UI đề xuất công thức; `/api/excel/analyze` vẫn tồn tại nhưng không lộ ra UI (11.5). Biên sản phẩm "AI advice không cấp approval" vẫn nguyên.
5. **Không auto-save, không rollback.** `workbookSaved` luôn `false`. Muốn hoàn tác: đóng không lưu. (AF-AP-003)
6. **Không đóng gate live.** Mọi acceptance trong spec là fake-host/HTTP. Office.js/Excel live, Codex live, Power BI Desktop đều **Not run**.
7. **Không đóng** `AF-UN-005` (diễn giải nghĩa cột bằng AI), `AF-UN-007`/`T-E2E-NOPACK` (fallback generic cho FIN — đã chốt fail-closed). (mục 10)
8. **Không sửa** finding 1 (date epoch fingerprint) và finding 2/5 (checkout/partial-write của Problem Chain) trừ phần P0-2. Đó là phạm vi khác; P0-2 chỉ sửa **đường đọc mới** của Assistant và đường `readWorkbook` hiện có.

---

## 10. Cập nhật traceability (P5)

Sau khi implement, `ASSISTANT_TRACEABILITY.md` phải chuyển các dòng sau từ `partial` sang `covered`, **kèm ghi chú lớp** ("engine synthetic + HTTP fake host, không phải Office live"):

| ID | Vì sao được nâng |
|---|---|
| AF-GD-001 | 4 connector có UI: workbook qua Office.js full read, CSV/XLSX/folder qua path |
| AF-GD-002 | Navigator tick/bỏ chọn trên task pane (`flow-navigator`) |
| AF-GD-003 | `flow-csv-options` hiện encoding/delimiter/header và cho chọn lại |
| AF-BF-001 | `flow-contract` hiện và cho override grain/measure |
| AF-EX-006 | `flow-approve-button` khoá khi reconcile fail + banner lý do |
| AF-AP-002 | Ghi sheet kết quả vào workbook đang mở qua Office.js, read-back so digest |
| AF-AP-005 | `flow-label-badges` hiện marker + nhãn provenance |
| AF-VF-001 | `flow-delta` hiện rows/nulls/dupes/cột đổi |
| T-WL1-01, T-WL1-02, T-WL3-01, T-WL5-05, T-WL6-01, T-WL6-05, T-WL7-01 | tương ứng theo FR ở trên |
| AF-UN-003 / T-WL2-02 | **chỉ** phần guard cardinality đóng (P0-1); phần tổng hợp điểm score vẫn `partial` |

Giữ nguyên `partial`:

| ID | Lý do |
|---|---|
| AF-UN-005 | Cần lớp AI diễn giải nghĩa cột — ngoài phạm vi (spec §2 ngoài phạm vi) |
| AF-UN-007 / T-E2E-NOPACK | Đã chốt fail-closed, không làm fallback generic cho FIN |

Sau khi cập nhật, tổng phải đọc lại đúng: 15 trong 20 dòng `partial` chuyển `covered` (8 FR + 7 test ID), 2 dòng giảm một phần nhưng **vẫn** `partial` (AF-UN-003, T-WL2-02). Tức `covered` 72 → khoảng **87**, `partial` 20 → **5**. **Số dòng khai báo không phải tỷ lệ hoàn thành sản phẩm.**

Đồng thời cập nhật `CURRENT_STATUS.md`: thêm dòng cho luồng Assistant với kết quả gate thực tế và ghi rõ **chưa có** live Office.js evidence.

**Ba tài liệu khác phải sửa cùng P4/P5, không được bỏ sót:**

| Tài liệu | Sửa gì |
|---|---|
| `docs/current/TASKPANE_UI.md` | UI-001…UI-009 đang mô tả 6 card cũ (Kế hoạch đề xuất / code-block / Duyệt copy / Runtime). Phải viết lại theo 8 card mới ở 5.2; bỏ mọi yêu cầu về khối code sao chép được, thêm yêu cầu về chip status + `data-state` |
| `docs/current/ASSISTANT_FLOW_SPEC.md` §16.2 | Bảng màn hình đang đặt S4–S6 ở tab `PQ_Code-M`. Thực tế bản này đặt **cả S0–S6 ở tab Trợ lý** vì `PQ_Code-M` đã kín (Typed Steps + M nâng cao). Phải ghi rõ sai lệch này và lý do |
| `docs/current/CURRENT_STATUS.md` | Thêm dòng: `/api/excel/analyze` **không còn UI** (11.5); tab Trợ lý dùng luồng WL1–WL7 |

---

## 11. Quyết định đã chốt

### 11.1 Đã chốt trong spec này (codex không cần hỏi lại)

| # | Quyết định | Lý do |
|---|---|---|
| D1 | **Thay** nội dung tab `Trợ lý` bằng luồng WL1–WL7 (không thêm tab thứ ba) | Xem 5.1 + 11.2 |
| D2 | Store đặt tại `sources/assistant_session.py` | Theo đúng chỗ 17 module assistant đang nằm; không tạo top-level module mới trái AGENTS.md |
| D3 | Toàn bộ `/api/assistant/*` chỉ dùng `state()` slot | C2: một writer duy nhất cho store; approval phải cùng process |
| D4 | Approval **không bao giờ** đi qua client | C2: `_live()` từ chối bản copy |
| D5 | Tên sheet chốt cứng, UI không cho đổi | C11 |
| D6 | Root gắn qua input text (không có file picker trong Office.js) | Office.js không cho chọn path filesystem |
| D7 | `/ingest` trả 200 cho `ingest_blocked` | Lỗi WL1 là dữ liệu người dùng sửa được, không phải lỗi giao thức |
| D8 | Marker Apply do adapter tự xây, không lấy từ engine | C10: engine không xuất hàm này |
| D9 | **Sửa cả `readWorkbook()`** của tab Trợ lý (P0-2b) | Xem 11.3 |
| D10 | **Làm `briefRequirements` server-side** (P0-3) | Xem 11.4 |
| D11 | **Làm `tools/assistant_flow_smoke.ps1`** | Xem mục 12 |

### 11.2 Không có tab mới — vì sao

Quyết định ban đầu của spec (thêm tab thứ ba `Luồng`) là **sai so với chỉ đạo**: tab tư vấn phải bị **thay**, không phải được giữ bên cạnh. Bản này sửa lại.

| Phương án | Kết luận |
|---|---|
| **Thay nội dung tab `Trợ lý`** ✅ | Đúng chỉ đạo. **Rẻ hơn**: không sửa `switchTab`, không thêm `tab-button`, không thêm listener. Tab bar vẫn 2 tab |
| Thêm tab thứ ba `Luồng` ❌ | Bỏ. Giữ lại tab tư vấn là thứ đã bị yêu cầu bỏ |
| Đổi tên tab `Trợ lý` → tên khác ❌ | Không cần. Tab vẫn là "trợ lý": hiểu dữ liệu, hỏi ngoại lệ, thi hành, ghi kết quả. Chỉ *cách* trợ lý thay đổi |

**Hệ quả tích cực:** vì `#tab-assistant` được tái dùng, các thứ sau **không phải sửa**: `switchTab()`, `tab-assistant-button`, `bindEvents` phần tab, `.tab-bar` CSS, và `#error-panel` (nằm ngoài 2 tab nên lỗi vẫn hiện đúng chỗ).

**Nhãn nút bên trong tab thì đổi** để khớp nghĩa mới:

| Cũ | Mới |
|---|---|
| `#analyze-button` — "Phân tích workbook" | `#flow-analyze-button` — **"Phân tích"** |
| `#prompt` placeholder *"Phân tích cột Mã đơn hàng thô và đề xuất công thức tách…"* | *"Ví dụ: Báo cáo P&L theo cost center, quy VND, tách FX cho tháng 9."* — bỏ ví dụ gắn với fixture cũ |
| `#prompt-count` "`n` / 4000" | "`n` / 20000" (`maxlength` đổi theo) |
| Nhãn tiến trình: "Codex đang phân tích…" | "Engine đang đo cấu trúc…" (C1: không có Codex) |

`#prompt` tái dùng nên `updatePromptCount()` và handler `input` giữ nguyên, chỉ đổi hằng số 4 000 → 20 000.

### 11.3 P0-2 — có sửa `readWorkbook()` của tab Trợ lý không?

**Trước hết, câu hỏi này nói về cái gì.** Có **hai** chỗ đọc bảng từ Excel:

| Chỗ đọc | Ai dùng | Hiện trạng |
|---|---|---|
| `readWorkbook()` — `taskpane.js:334-438` | Tab **PQ** (`proposePQ`, `previewPQ`, …) sau khi bỏ advice; trước đó cả `analyze()` | Có bug Total Row (finding 3) |
| `flowReadOpenWorkbook()` — **mới**, mục 6.2 | Tab **Trợ lý** (luồng WL1) | Viết mới, dùng `getDataBodyRange()` nên **không** có bug |

Bug nằm ở dòng 363: `table.getRange()` trả **cả** header **và** totals row; code chỉ trừ 1 dòng (header) ở dòng 392 và 430. Hệ quả:

- `totalRows` **cao hơn thực tế 1**;
- `deterministicCheckRowOffsets` ghim các offset cuối (`rowCount-3, -2, -1`) ⇒ dòng **tổng cộng bị lấy mẫu như dòng dữ liệu** và gửi sang Codex.

**Nghĩa là:** nếu chỉ viết hàm mới cho luồng, tab **PQ_Code-M** **vẫn** nhận `totalRows` sai 1 và dòng tổng bị lấy mẫu như dữ liệu (đi vào `/api/pq/propose` và các đường Typed).

**Cách tự thấy bug (làm trước khi sửa, 1 phút):** tạo một Table có bật **Total Row** (Table Design → Total Row), ở tab **PQ_Code-M** chọn bảng đó rồi **Đề xuất M**, xem mẫu nguồn — dòng cuối là dòng nhãn tổng (ví dụ `Total`), không phải dữ liệu.

> Trước khi bỏ advice UI, đường thấy nhanh nhất là nút **Phân tích workbook** ở tab Trợ lý + khối "Mẫu dữ liệu nguồn". Sau P4a thì dùng tab PQ như trên.

**Chi phí sửa cả hai:**

| Việc | Chi phí |
|---|---|
| `getRange()` → `getDataBodyRange()` + `getHeaderRowRange()` trong `readWorkbook()` | ~15 dòng, cơ học |
| Cập nhật fake host trong test JS: thêm `getDataBodyRange()`/`getHeaderRowRange()` cho object table giả | 2–3 file (`taskpane_usedrange.js`, `taskpane_live_analyze.js` → nay là `taskpane_assistant_flow.js`, có thể `taskpane_pq*.js`) |
| Test hồi quy mới: bảng có totals row ⇒ `totalRows` đúng, dòng tổng không vào `rows` | 1 case |

**Chốt D9: CÓ, sửa cả hai, tách 2 commit:**

- **P0-2a** — `flowReadOpenWorkbook()` đúng ngay từ đầu (không thêm rủi ro).
- **P0-2b** — sửa `readWorkbook()` + cập nhật fake host + test totals row. Đóng finding 3 cho cả add-in.

Nếu buổi test gấp: P0-2a là **bắt buộc**, P0-2b có thể lùi sau — nhưng khi đó finding 3 vẫn **mở** và biên bản test phải ghi rõ "tab PQ còn bug totals row".

### 11.4 `briefRequirements` — "chưa biết domain chính" thì lấy gì?

**Trả lời ngắn: không cần biết, vì domain là tập đóng và chỉ có 2 giá trị.** Đã kiểm:

| Bằng chứng | Nội dung |
|---|---|
| `pbip_assistant/schemas/assistant_domain_pack.schema.json` | `properties.id.enum = ["fin-pl-v1", "generic"]` — schema **đóng**, `required` đủ 9 field, `_validate_schema` từ chối field ngoài hợp đồng (`assistant_pack.py:115,151`) |
| `sources/packs/fin_pl_v1.json` (22.5 KB) | `industry: "finance"` — pack **chính**, có đầy đủ policies/metrics cho P&L |
| `sources/packs/generic.json` (9.9 KB) | pack **dự phòng**, `genericMode: true`, có `notice`, dùng cho kịch bản SALES |

Engine tự chọn pack, **không phải người dùng chọn**: `build_understand` dò schema bằng `has_finance_schema` rồi gán (`assistant_understand.py:106-108`). `scenario` suy từ `pack.id` (`assistant_preview.py:107`).

**Nhưng câu hỏi của anh/chị bắt đúng một chỗ đau thật.** Em đã kiểm pack resource: **không pack nào khai báo cột ngày.**

```text
grep PostingDate|OrderDate|period  trong sources/packs/  →  0 match
signature của fin_pl_v1.json = { columns: ["AccountCode","Currency"],
                                 tables:  ["CoA","FX_Rates_2026"] }
```

Nghĩa là `"PostingDate"` / `"OrderDate"` **chỉ tồn tại dưới dạng literal Python** trong `_period` (`assistant_brief.py:37`). Đây là giới hạn **có sẵn của engine**, không phải thứ bản tích hợp này sinh ra. `briefRequirements` chỉ phơi nó ra UI.

Hai cách, và chi phí khác nhau rất nhiều:

| Phương án | Việc phải làm | Rủi ro |
|---|---|---|
| **(1) `required_date_column(pack_id)` trong Python** ✅ **chốt** | 4 dòng; `_period` gọi nó; adapter import | Không. Vì domain là enum đóng 2 giá trị, hàm này **không thể** trả sai |
| (2) Đưa `periodColumn` vào `signature` trong pack + schema | Sửa `assistant_domain_pack.schema.json` (đóng, required-all) + 2 pack JSON + 19 schema trong `tests/fixtures/assistant/schema` + **tái sinh toàn bộ golden** | ⚠ **Không nhỏ.** `pack` nằm trong `_HASH_BASIS` của WL2 (`assistant_understand.py:14`) ⇒ đổi pack JSON ⇒ đổi `understandHash` ⇒ đổi `briefHash` ⇒ đổi `decisionsHash` ⇒ đổi `specFingerprint`/`previewHash`/`record.hash`. Phải chạy lại `py -m tests.support.assistant_fin`, `assistant_sales`, `assistant_variants` |

⇒ **Phương án 1 bây giờ; phương án 2 là việc mở rộng domain, không phải việc tích hợp.** Khi nào thật sự thêm domain thứ ba thì làm (2) một lần, lúc đó `briefRequirements` tự khớp vì nó đọc pack.

Điều này cũng trả lời "dùng domain nào chính": **`fin-pl-v1` là domain chính** (P&L, đủ chính sách); `generic` là dự phòng và hiện dùng cho kịch bản SALES. Bản này **không** thêm domain nào.

**`briefRequirements` là một field nhỏ thêm vào response `/understand`:**

```json
"briefRequirements": { "dateColumn": "PostingDate", "scenario": "tp-fin",
                       "grain": ["accountCode","costCenter","entityCode","period"] }
```

để UI kiểm **ngay ở card 04** và hiện:

> ⚠ Kỳ báo cáo sẽ dùng cột `PostingDate`. Hiện **0 bảng** có cột này — Brief sẽ dừng. Hãy thêm nguồn có cột `PostingDate`.

Nó biến một lỗi khó hiểu ở bước Brief thành một pre-check thấy được ở bước Cách hiểu.

Refactor P0-3 (bắt buộc, 4 dòng):

```python
# assistant_brief.py — thêm hàm public, và _period dùng nó thay chuỗi cứng
def required_date_column(pack_id: str) -> str:
    """Cột ngày mà Brief bắt buộc phải có đúng một bảng chứa nó."""
    return "PostingDate" if pack_id == "fin-pl-v1" else "OrderDate"

# trong _period():
field = required_date_column("fin-pl-v1" if finance else "generic")
```

Adapter `/understand` chỉ được gọi hàm này, **không** được chép chuỗi sang JS.

### 11.5 Codex: giữ, và cắm vào đúng ba chỗ

**Người dùng dùng Codex thật** ⇒ không xoá. Nhưng phải tách rõ: cái bị bỏ là **pipeline đề xuất giả** (`status:"analysis_only"` + `canApply:false` + duyệt copy → `EXCEL VERIFIED` không bao giờ tới được), **không phải** năng lực Codex.

#### Phần giữ / bỏ

| Phần | Xử lý | Vì sao |
|---|---|---|
| `POST /api/excel/analyze` + `adapters/codex/excel.py` | **GIỮ** | Đây là adapter Codex **tốt**: validate từng field, whitelist sheet/column theo snapshot, chỉ nhận công thức bắt đầu `=`, cap độ dài, `canApply:false` (dòng 152-199). Không có lý do xoá |
| `CodexExecRunner`, `codex_available()`, `CodexCooldown` | **GIỮ** | Hạ tầng auth/429/backoff đã đúng |
| 5 card pipeline (03 Kế hoạch → 06 Runtime) | **XOÁ** (5.1) | Đúng chỉ đạo |
| 1 khối **"Hỏi Codex"** gọn (tuỳ chọn) | **ĐỀ XUẤT GIỮ** | Xem dưới |
| `POST /api/excel/plan` / `/api/excel/apply` | **GIỮ** | Đường developer-only, đã tách khỏi UI |

**Về một khối "Hỏi Codex" gọn.** Nếu anh/chị dùng Codex hằng ngày thì bỏ hết UI là tự bỏ công cụ. Đề xuất: **một** card nhỏ trong tab Trợ lý (dưới card 01), gồm `#prompt`, nút "Hỏi Codex", và **chỉ** hiện `summary` + `questions` + `warnings` + các `codeBlocks` (read-only, dùng lại `renderCodeCard`). **Không** plan-status, **không** operations, **không** approval, **không** runtime. Như vậy Codex vẫn dùng được, còn "chỉ trả đề xuất" không còn đóng giả là một luồng ghi được.

⚠ **Xung đột giới hạn phải xử lý:** Codex chặn prompt ở **4 000** ký tự (`core/limits.py:3 MAX_PROMPT_CHARS = 4_000`), còn Brief cho **20 000** (`assistant_brief.py:96`). Dùng chung `#prompt` (maxlength 20 000) thì:
- gọi `/brief` với 4 001–20 000 ký tự: **hợp lệ**;
- gọi `/excel/analyze` cùng prompt đó: **`PROMPT_LIMIT`**.

Nên pane phải kiểm riêng trước khi gọi Codex và báo rõ ("Codex chỉ nhận 4 000 ký tự; phần Brief thì không"), **không** hạ maxlength chung xuống 4 000 (sẽ mất khả năng đề bài dài cho luồng).

#### Ba chỗ Codex *nên* được cắm về lâu dài

Đây là chỗ đúng để dùng Codex mà **không** phá tính tất định — vì cả ba đều chỉ sinh **nhãn và chữ**, không sinh **số**:

| Seam | Codex làm gì | Vì sao an toàn | Hôm nay |
|---|---|---|---|
| **S1 · Cách hiểu** | Đề xuất nghĩa cột + định nghĩa (date/amount/key/percent/currency) | `roles`/`columns` chỉ là nhãn; số đo vẫn do `measure_set` tính. Gắn `provenance:"llm"`, status `inferred`/`assumed`; người dùng sửa được | Thiếu = `AF-UN-005` (partial) |
| **S0b · Đề bài** | Chuyển câu tự do → `outputContract` `{grain, measure, filter, kỳ}` | `_output_contract` chỉ cho **thu hẹp** trong phạm vi pack; measure phải có `formulaId` trong registry engine (dòng 65-76). Codex không thể bịa measure | Thiếu = `AF-BF-001` (partial) |
| **S2 · Brief** | Diễn giải lại finding/SP cho dễ đọc | Engine đã có `value`; Codex chỉ được *diễn giải field đó*, cấm tạo số (AF-BF-BR-001) | Pack authored đang làm thay |

**Ranh giới cứng, không được vượt:** Codex **không bao giờ** đi vào `measure_set`, `result_rows`, `build_reconciliation`, `build_record`. Ba hàm đó phải thuần tất định. Cách cưỡng chế: Codex chỉ được gọi ở tầng WL2/WL3 nhãn, output phải qua `canonical_hash` + kiểm enum + kiểm length giống `analyze_workbook` đang làm.

**Phát hiện quan trọng — kiến trúc đã chừa sẵn chỗ cho Codex, chỉ là chưa mở cửa:**

```text
assistant_record.py:193   entry["source"] in {"data","pack","history","user","llm"}   ← record CHẤP NHẬN llm
assistant_domain_pack.schema.json  assumption.source  enum: ["pack","data"]           ← pack CHẶN llm
                                   policy.provenance  enum: ["pack","data"]
```

Nghĩa là **tầng record đã có `llm`**, chỉ tầng pack là đóng. Mở cửa rất rẻ: **nới enum trong schema** từ `["pack","data"]` thành `["pack","data","history","llm","user"]`.

Vì sao rẻ: nới enum **không đổi nội dung pack JSON** ⇒ `understand.pack` (dict `{id,version,genericMode,notice}` do `build_understand` dựng) **không đổi** ⇒ `understandHash` **không đổi** ⇒ **không phải tái sinh golden**. Đây là thay đổi một file schema, không phải một cuộc migration.

#### Codex ở thời điểm *soạn*, không chỉ lúc chạy — hướng tối ưu dài hạn

Điều đáng làm nhất cho một người dùng Codex: **dùng Codex để soạn/ làm mới domain pack**, không phải để tính lúc chạy.

Lý do: WL5 chỉ có **2 recipe đóng** (`_FIN`, `_SALES` trong `assistant_execution.py:22,38` và `RESULT_COLUMNS` trong `assistant_preview.py:30`). Thêm domain thứ ba hiện nay = viết thêm tuple Python + `RESULT_COLUMNS` + test. Nếu để Codex sinh số lúc chạy thì mất bảo đảm tất định; còn để Codex **soạn pack** rồi người duyệt và version-hoá thì:

- vẫn giữ "cùng input → cùng output" (AF-PR-002);
- mở rộng domain bằng **dữ liệu** (JSON có schema) chứ không bằng code;
- mọi con số vẫn do engine tính;
- pack có `version` + hash → audit được pack nào sinh ra kết quả nào.

Đó là cách dùng Codex "tối ưu lâu dài": **Codex là tác giả pack + người diễn giải nhãn; engine là nơi duy nhất sinh số.**

#### Chốt

| # | Quyết định |
|---|---|
| D12 | **GIỮ** `/api/excel/analyze` + `adapters/codex/excel.py` + `CodexExecRunner`/`CodexCooldown`. Không xoá |
| D13 | Bỏ 5 card pipeline; **đề xuất giữ 1 card "Hỏi Codex" gọn** (read-only). Nếu anh/chị không cần, bỏ luôn thì route vẫn còn cho test/CLI |
| D14 | Ba seam Codex (S1 định nghĩa cột, S0b prompt→contract, S2 diễn giải) là **pha riêng P7**, **không** nằm trên đường găng của buổi test này |
| D15 | Nới enum `assumption.source` / `policy.provenance` để nhận `llm` là **điều kiện của P7**, làm cùng P7, không làm lẻ |

---

## 12. `tools/assistant_flow_smoke.ps1` — thiết kế để codex implement

### 12.1 Mục đích

Cho phép kiểm **toàn bộ P1–P3 không cần mở Excel**: một script chạy 11 call HTTP theo đúng thứ tự, tự tính `choices` từ Brief, assert các con số đối chứng, in chuỗi hash. Đây là công cụ để người implement tự chứng minh trước khi bàn giao, và để người test kiểm backend trước khi đụng Office.js.

Nguyên tắc: **chỉ đọc fixture synthetic**, không bao giờ đụng workbook người dùng; không Save; không gọi Codex (C1); chạy được trên cả Windows PowerShell 5.1 và `pwsh` 7.

> **Lưu ý vận hành.** Script lấy token qua `GET /api/bootstrap`. Nếu task pane đang mở trong Excel, hai bên **dùng chung một session và chung một store** — bước 11 (`/reset`) sẽ đưa tab Trợ lý về `stage:"new"`. Đó là lý do có `-KeepSession`. Muốn cô lập hoàn toàn thì chạy smoke trước khi mở pane, hoặc dùng `-KeepSession` rồi tự `reset` bằng nút "Bắt đầu lại".

### 12.2 Cách chạy

```powershell
# terminal 1 — giữ mở
py -m pbip_assistant.excel_addin_server

# terminal 2
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -Scenario tp-sales
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter brief     # khi mới xong P1
pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -Port 3079 -KeepSession -RecordOut .\record.json
```

### 12.3 Đặc tả tham số

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `-Port` | `0` | `0` = tự dò `3079..3072` bằng `GET /api/health` (`status -eq "ok"`) |
| `-Root` | `tests/fixtures/assistant/<Scenario>/source` | thư mục gốc gửi cho `/session`; phải tuyệt đối hoá bằng `Resolve-Path` |
| `-Workbook` | `tests/fixtures/source/orders_synthetic.xlsx` | workbook cho `/apply` (đọc bytes, **không** mở Excel) |
| `-Scenario` | `tp-fin` | `tp-fin` \| `tp-sales` |
| `-StopAfter` | `apply` | `session\|ingest\|understand\|brief\|decisions\|spec\|preview\|approvals\|apply` — để chạy được phần đã implement |
| `-RecordOut` | rỗng | ghi Decision Record ra file JSON (UTF-8 **không BOM**) để soi |
| `-KeepSession` | tắt | không gọi `/api/assistant/reset` ở cuối |

### 12.4 Hợp đồng I/O của script

**Exit code** — dùng để cắm vào bất kỳ đâu:

| Code | Nghĩa |
|---|---|
| `0` | Mọi assertion xanh |
| `1` | Có assertion sai (in hết danh sách sai) |
| `2` | Không thấy coordinator ở pool cổng |
| `3` | Lỗi HTTP ở một bước (in `code` + `detail` của envelope lỗi) |

**Output** — bảng sau mỗi bước, rồi tổng kết:

```
STEP            HTTP  STAGE        GHI CHÚ
01 /session     200   new          rootLabel=source
02 /ingest      200   ingested     sources=7 tables=7 snapshot=snap_1a2b3c
03 /understand  200   understood   pack=fin-pl-v1 rel=6 assumptions=5
04 /brief       200   briefed      SP=6 scenarios=2 findings=4
05 /decisions   200   decided      choices=5 acks=1 freezeBlocked=False
06 /spec        200   frozen       steps=14 fingerprint=sha256:9f8e…
07 /preview     200   reconciled   rowsIn=42 rowsOut=23 passed=True
08 /approvals   200   approved     apr_4d5e consumed=False
09 /apply       200   recorded     23x9 sheet=PnL_Result saved=False
10 /state       200   recorded     record=rec_7a8b…
11 /reset       200   new          —

KẾT QUẢ: PASS — 12 assertion, 4.212 s
```

**Chuỗi hash** in thành khối riêng để so giữa hai lần chạy (kiểm determinism AF-PR-002):

```
snapshotHash    sha256:…
understandHash  sha256:…
briefHash       sha256:…
decisionsHash   sha256:…
specFingerprint sha256:…
previewHash     sha256:…
record.hash     sha256:…
```

### 12.5 Khung code bắt buộc

```powershell
[CmdletBinding()]
param(
    [int]$Port = 0,
    [string]$Root,
    [string]$Workbook,
    [ValidateSet("tp-fin", "tp-sales")][string]$Scenario = "tp-fin",
    [ValidateSet("session","ingest","understand","brief","decisions",
                 "spec","preview","approvals","apply")][string]$StopAfter = "apply",
    [string]$RecordOut,
    [switch]$KeepSession
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Root)     { $Root     = Join-Path $RepoRoot "tests/fixtures/assistant/$Scenario/source" }
if (-not $Workbook) { $Workbook = Join-Path $RepoRoot "tests/fixtures/source/orders_synthetic.xlsx" }
$Root     = (Resolve-Path -LiteralPath $Root).Path
$Workbook = (Resolve-Path -LiteralPath $Workbook).Path

$script:Failures = New-Object System.Collections.Generic.List[string]
$script:Steps    = New-Object System.Collections.Generic.List[object]
$script:Count    = 0

function Now-Iso {
    (Get-Date).ToUniversalTime().ToString(
        "yyyy-MM-dd'T'HH:mm:ss'Z'", [System.Globalization.CultureInfo]::InvariantCulture)
}

function Assert-Equal($name, $actual, $expected) {
    $script:Count++
    if ("$actual" -ne "$expected") {
        $script:Failures.Add("$name : mong đợi '$expected', nhận '$actual'")
    }
}

function Assert-True($name, $condition) {
    $script:Count++
    if (-not $condition) { $script:Failures.Add("$name : mong đợi true") }
}
```

`Invoke-Flow` — một hàm duy nhất cho mọi bước, tự ghi bảng và tự thoát `3` khi HTTP lỗi. **Ba điểm phải đúng:**

```powershell
function Invoke-Flow {
    param([string]$Step, [string]$Path, [hashtable]$Payload)
    # (1) Content-Length bắt buộc: server đọc đúng số byte (server.py:554-561)
    # (2) UTF-8 thủ công: PS 5.1 mặc định không gửi UTF-8, tiếng Việt trong prompt sẽ hỏng
    $json  = $Payload | ConvertTo-Json -Depth 32 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        $response = Invoke-RestMethod -Uri "$script:Base$Path" -Method Post -Body $bytes `
            -ContentType "application/json; charset=utf-8" -Headers $script:Headers -TimeoutSec 180
    } catch {
        $raw = ""
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $raw = $_.ErrorDetails.Message }
        $code = ""; $detail = $raw
        try { $env = $raw | ConvertFrom-Json; $code = $env.error.code; $detail = $env.error.detail } catch { }
        $script:Steps.Add([pscustomobject]@{ Step = $Step; Http = "ERR"; Stage = "-"; Note = $code })
        Complete-Smoke -HttpFailure "$Step → $code : $detail"
        exit 3
    }
    $script:Steps.Add([pscustomobject]@{ Step = $Step; Http = 200
                                        Stage = [string]$response.stage; Note = "" })
    return $response
}
```

### 12.6 Trình tự bắt buộc + assertion

| Bước | Route | Payload | Assertion |
|---|---|---|---|
| 01 | `/api/assistant/session` | `@{ root = $Root }` | `rootLabel` có giá trị |
| 02 | `/api/assistant/ingest` | danh sách `kind:"csv"` cho mọi `*.csv` (sort theo tên); riêng `tp-sales` thêm `@{kind="folder"; path="orders"; name="Orders"}` | `sources.Count` = **7** (tp-fin) / **5** (tp-sales); `tables.Count` bằng `sources.Count`; `stage -eq "ingested"` |
| 03 | `/api/assistant/understand` | `@{ packId = "auto" }` | tp-fin: `pack.id -eq "fin-pl-v1"`, `pack.genericMode -eq $false`; tp-sales: `pack.id -eq "generic"`, `pack.notice` có nội dung |
| 04 | `/api/assistant/brief` | `@{ prompt = <xem dưới>; policyUnresolved = @() }` | `subProblems.Count -ge 5` (tp-fin) / `-ge 3` (tp-sales) |
| 05 | `/api/assistant/decisions` | tính từ Brief — xem 12.7 | `freezeBlocked -eq $false` |
| 06 | `/api/assistant/spec` | `@{ createdAt = (Now-Iso) }` | `spec.steps.Count` = **14** / **10** |
| 07 | `/api/assistant/preview` | `@{}` | `reconciliation.passed`, `controlTotalPassed`; tp-fin: `bridge.applicable` + `bridge.passed`; tp-sales: `bridge.applicable -eq $false`; `rowsOut/colsOut` = **23/9** / **4/4** |
| 08 | `/api/assistant/approvals` | `@{ approvedAt = (Now-Iso) }` | `approval.singleUse`, `approval.consumed -eq $false` |
| 09 | `/api/assistant/apply` | `@{ workbookBase64 = <base64 file>; appliedAt = (Now-Iso) }` | `apply.target.sheet` = `PnL_Result`/`Sales_Result`; `written` 23×9 / 4×4; `workbookSaved -eq $false`; `apply.approval.consumed`; `record.hash` có; `record.stale -eq $false`; `$null -eq staleCheck`; `record.labels -contains "unverified"` |
| 10 | `/api/assistant/state` | `@{}` | `stage -eq "recorded"`; `approvalConsumed -eq $true` |
| 11 | `/api/assistant/reset` | `@{}` | `stage -eq "new"` — **bỏ qua nếu `-KeepSession`** |

Prompt dùng (giữ cố định để so determinism):

- tp-fin: `"Báo cáo P&L theo cost center, quy VND, tách FX cho tháng 9."`
- tp-sales: `"Doanh thu theo khu vực quý 3 giảm vì đơn huỷ hay thiếu khách?"`

> ⚠ **`prompt` phải gửi bằng UTF-8 bytes.** Nếu dùng `Invoke-RestMethod` với body là string, PS 5.1 gửi theo ANSI/UTF-16 và dấu tiếng Việt hỏng ⇒ `briefHash` khác ⇒ bước 07/09 lệch. Đây là lỗi hay gặp nhất khi viết script loại này.

### 12.7 Tính `choices` từ Brief — quy tắc duy nhất

Script **không** đọc file golden. Nó suy ra từ response `/brief`, đúng theo ràng buộc C3 của engine (`assistant_preview.py:96`):

```powershell
$choices = @{}; $acks = @{}
foreach ($sp in $s4.subProblems) {
    if ($sp.status -eq "missing_data") { $acks[$sp.id] = "out_of_scope" }
    else                               { $choices[$sp.id] = "A" }
}
```

Vì engine **chỉ** thực thi option `A`, và `_supported_recipe` đòi `chosenOptions` bằng `{key:"A"}` cho mọi ref, nên "A cho tất cả + `out_of_scope` cho `missing_data`" là cách duy nhất đi qua được. Nếu Brief có SP `missing_data` mà script gán `A`, `/decisions` sẽ trả `AF_DECISIONS_INVALID` — và assertion sẽ chỉ đúng chỗ sai.

`decisionMetadata` gửi:

```powershell
@{ decidedBy = "user"; decidedAt = (Now-Iso); rationale = "assistant_flow_smoke"; acknowledgementNotes = "" }
```

Phải là `decidedBy = "user"` — engine từ chối giá trị khác (`assistant_preview.py:94`).

### 12.8 Tổng kết, ghi record, và assertion kiểu "phải đỏ"

```powershell
function Complete-Smoke {
    param([string]$HttpFailure)
    # bảng bước ở 12.4
    if ($HttpFailure) { Write-Host "LỖI HTTP: $HttpFailure" -ForegroundColor Red }
    if ($script:Failures.Count) {
        Write-Host "KẾT QUẢ: FAIL — $($script:Failures.Count)/$($script:Count) assertion" -ForegroundColor Red
        $script:Failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        exit 1
    }
    Write-Host "KẾT QUẢ: PASS — $($script:Count) assertion" -ForegroundColor Green
}
```

`-RecordOut`:

```powershell
if ($RecordOut -and $s9.record) {
    $text = $s9.record | ConvertTo-Json -Depth 32
    [System.IO.File]::WriteAllText($RecordOut, $text,
        (New-Object System.Text.UTF8Encoding($false)))     # UTF-8 không BOM, như fixture
}
```

**Assertion âm bắt buộc** (chứng minh script không phải "luôn xanh"): chạy thêm một lần với dữ liệu cố ý hỏng và phải nhận exit `1`.

```powershell
-Context "negative" { pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter brief -Root <thư mục rỗng> }
# kỳ vọng: exit 1, thông điệp nêu bước 02 hoặc 04 sai
```

Không có case âm thì script không chứng minh được gì.

### 12.9 Acceptance và vị trí trong gate

| Kiểm | Lệnh | Kỳ vọng |
|---|---|---|
| Cú pháp | `pwsh -NoProfile -Command "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('tools/assistant_flow_smoke.ps1',[ref]$null,[ref]$e); if($e){$e|%{$_.Message};exit 1}"` | exit 0 |
| Chạy thật `pwsh` 7 | `pwsh -NoProfile -File tools/assistant_flow_smoke.ps1` | `PASS`, exit 0 |
| Chạy thật Windows PowerShell 5.1 | `powershell.exe -NoProfile -File tools/assistant_flow_smoke.ps1` | `PASS`, exit 0 |
| Determinism (AF-PR-002) | chạy 2 lần, so khối hash | `snapshotHash`, `understandHash`, `briefHash` **giống nhau**; `specFingerprint`/`previewHash`/`record.hash` được phép khác vì có `createdAt`/`approvedAt`/`appliedAt` |
| Case âm | `-StopAfter brief -Root <rỗng>` | exit `1` |

**Không** đưa script vào `py tools/run_checks.py fast` — nó cần server đang chạy, vào gate sẽ làm gate phụ thuộc trạng thái máy. Các case HTTP tương ứng đã nằm trong `tests/integration/test_assistant_flow_api.py` (mục 7.1). Thêm **một** test rẻ để script không bị hỏng âm thầm:

```python
# tests/taskpane/test_taskpane_js.py — hoặc file riêng tests/integration/test_assistant_smoke_script.py
@unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell.exe"), "no PowerShell")
def test_assistant_flow_smoke_script_parses(self) -> None:
    shell = shutil.which("pwsh") or "powershell.exe"
    script = ROOT / "tools" / "assistant_flow_smoke.ps1"
    command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('"
               + str(script) + "',[ref]$null,[ref]$e); if($e){ $e | %{ $_.Message }; exit 1 }")
    result = subprocess.run([shell, "-NoProfile", "-Command", command],
                            capture_output=True, text=True, timeout=60, check=False)
    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
```

### 12.10 Việc codex phải làm, theo pha

| Pha | Mở rộng script tới | Điều kiện dừng |
|---|---|---|
| P1 | `-StopAfter brief` chạy xanh (bước 01–04) | kiểm WL1–WL3 không cần Excel |
| P2 | `-StopAfter approvals` (bước 05–08) | kiểm WL4–WL5, số reconcile |
| P3 | đủ 11 bước, `PASS`, có case âm và test parse | bàn giao backend đã chứng minh |
| P4 | không đổi — P4 chỉ thêm UI; chạy lại `PASS` để chắc không hồi quy | |


---

## 13. Tổng quan quỹ đạo WL1–WL7 — luồng có đang đi đúng hướng?

Mục này là đánh giá, không phải yêu cầu thi hành. Đọc khi cần quyết định đầu tư tiếp.

### 13.1 Luồng đang chạy thực sự là gì

```text
WL1  ingest      17 module  •  resolve / add_* / build_snapshot        → snapshotHash
WL2  understand              •  build_understand (thống kê tất định)     → understandHash
WL3  brief                   •  build_brief + pack biên soạn sẵn         → briefHash
WL4  decisions/spec          •  build_decisions / build_spec             → decisionsHash, fingerprint
WL5  preview/reconcile       •  result_rows / build_preview / build_reconciliation
WL6  approve/apply           •  issue_approval / apply_result (bytes)    → approvalId
WL7  delta/record            •  compute_delta / build_record             → record.hash
```

Mọi mắt nối là **hash của bước trước**, và **mỗi hàm tự tính lại hash của input**. Không thể bỏ qua hay làm giả một bước: truyền artifact cũ là `raise`, không phải degrade. Đây là điểm mạnh nhất của dự án và hiếm gặp.

**E2E hiện có** (`tests/contracts/test_assistant_e2e.py`): 4 hành trình engine — `tp-fin` (23×9, 14 step), `tp-sales` (4×4, 10 step), `tp-unknown` (chặn freeze, không chọn hộ), `tp-nopack` (fail-closed). Tất cả chạy trên **bytes synthetic**, không Office.js, không Excel, không Codex.

### 13.2 Đúng quỹ đạo / rủi ro / lệch

| Hạng mục | Đánh giá | Căn cứ |
|---|---|---|
| Tất định & "cùng input → cùng output" | ✅ **Tốt** | Hash chain 8 tầng; `build_spec`/`build_preview` idempotent; test determinism ở mọi WL |
| Không bịa số | ✅ **Tốt** | Số chỉ từ `measure_set`; AI/chữ không sinh số; 7 luật ở `ASSISTANT_FLOW_SPEC` §9 có test |
| Nhãn & provenance | ✅ **Tốt** | `assumed/inferred/unverified/out_of_scope/stale`; record từ chối `verified` cho suy luận |
| Ranh giới ghi | ✅ **Tốt** | `values-only`, không Save, không ghi sheet nguồn, approval dùng một lần; read-back đối chiếu digest |
| Bounded input | ✅ **Tốt** | 64 MiB/file, 128 MiB/session, 100k dòng, cap cell; không temp rác khi lỗi |
| **Phủ chức năng** | ⚠ **Hẹp hơn tên gọi** | Chỉ **2 recipe đóng**. Đây là "máy báo cáo P&L + doanh số khu vực", không phải "copilot phân tích mọi workbook" |
| **A/B** | ⚠ **Một nửa** | Preview chỉ thực thi option **A** (`assistant_preview.py:96`). B chỉ ghi vào record. UX "exception-based" chưa thật |
| **Lưu trữ** | ⚠ **Yếu hơn tính năng cũ** | Record là JSON trả về; không persist. Problem Chain đã lưu vào **Custom XML** của workbook; luồng Assistant **chưa**. Đóng pane/restart coordinator là mất |
| **Vòng đời approval** | ⚠ **Process-affine** | `_ISSUED` khoá `id(object)` ⇒ một process, một phiên, không restart giữa duyệt và ghi |
| **Bộ nhớ** | ⚠ **Chưa đo** | Raw tables nằm RAM cả phiên (tới 100k dòng × N bảng) để WL2/WL3 tính lại. Chưa có số peak memory |
| **"AI-first"** | ⚠ **Tên lệch thực tế** | Luồng **không gọi AI**. WL3 là pack biên soạn sẵn. Người dùng dùng Codex sẽ thấy hụt kỳ vọng nếu không nói rõ (C1 + 11.5) |
| Gate & bằng chứng | ❌ **Đỏ một phần** | Cardinality guard đỏ; finding 1/2/3/5 mở; **0** bằng chứng Office.js/Excel live |
| Tài liệu | ❌ **Trôi** | `CURRENT_STATUS.md` ghi gate 386 case (22/10); audit 30/10 ghi 852 case. Chênh lệch chưa giải thích |

### 13.3 Ba câu hỏi chiến lược cần trả lời trước khi đầu tư tiếp

**1. Sản phẩm là "một báo cáo P&L" hay "mọi workbook"?**
Nếu là (a): quỹ đạo **đúng**, chỉ cần đóng vòng và chứng minh live. Nếu là (b): WL5 sẽ không scale — mỗi domain mới cần thêm một tuple `_FIN`/`_SALES` + `RESULT_COLUMNS` + test. Cần quyết trước khi wire, không phải sau.

**2. Quyết định của người dùng có thực thi được thật không?**
Option B hiện không chạy được. Nếu sản phẩm hứa "bạn chỉ chốt ngoại lệ", thì A/B phải thực thi được cả hai — hoặc UI phải nói thẳng "bản này chỉ chạy nhánh A" (spec này chọn cách thứ hai, C3). Cách thứ nhất là việc lớn hơn nhiều.

**3. Kết quả sống ở đâu?**
Problem Chain đã lưu vào Custom XML; Assistant thì chưa. Cho người dùng đã quen "mở lại vẫn còn lịch sử", đây là **bước lùi**. Đề xuất: sau P3, cân nhắc lưu Decision Record + Spec fingerprint vào Custom XML cùng namespace riêng, theo đúng pattern Problem Chain. Không thuộc phạm vi spec này, nhưng nên ghi vào backlog ngay.

### 13.4 Kết luận ngắn

- **Tầng engine: đúng quỹ đạo**, chất lượng cao, kỷ luật tốt — nhưng đang **đầu tư lệch**: 17 module, 45 test ID, 72/92 covered, 4 E2E… mà **0 route, 0 UI**. Backend được xây trước khi vòng lặp được đóng.
- **Rủi ro lớn nhất không phải thiếu UI**, mà là: (a) chỉ 2 recipe, (b) option B không chạy, (c) không persist. Ba điều này quyết định sản phẩm là gì; UI chỉ là lớp cuối.
- **Việc đúng bây giờ** là đóng vòng cho **một** kịch bản, chứng minh bằng smoke (mục 12) rồi bằng Excel thật, **rồi** mới bàn mở rộng domain và cắm Codex (P7).

---

## 14. Hướng sản phẩm v2 — **CHƯA CHỐT, KHÔNG IMPLEMENT**

Mục 1–13 mô tả **v1.x**: engine tất định, 2 recipe đóng, không AI. Người dùng đã nêu một hướng khác. Mục này ghi lại hướng đó và các điểm phải chốt **trước khi** codex viết dòng nào của v2.

> ⚠ **Codex: không implement mục 14** cho tới khi các câu hỏi 14.5 được trả lời và mục này được nâng thành spec chính thức. Mục 1–13 vẫn còn giá trị: nếu v2 bị hoãn, v1.x là đường chạy được.

### 14.1 Hướng người dùng nêu (nguyên văn ý)

1. **Mọi workbook, không chỉ P&L.** Hỏi người dùng phạm vi: chỉ sheet đang mở, hay cần nhiều file dữ liệu khác. Đọc **20 dòng** cho mọi loại dữ liệu khách hàng cho phép truy cập. Đưa ra đề xuất + điểm chưa rõ để khách trả lời. Rồi gửi Codex phân tích dữ kiện khách đã cung cấp → Codex đề xuất phù hợp với **chính workbook/báo cáo này**.
2. **A/B phải xem được trước khi chốt.** Trước hết cho khách chọn bảng sẽ phân tích, rồi **hiện preview cho cả nhánh A và nhánh B**. Khách chốt A hay B thì **mới** làm chi tiết.
3. (Chưa trả lời) Decision Record + Spec fingerprint lưu vào Custom XML theo pattern Problem Chain.

### 14.2 Sáu điểm engine hiện tại **chặn trực tiếp** hướng này

| # | Chặn ở đâu | Vì sao chặn | Hướng v2 cần |
|---|---|---|---|
| **V2-1** | Không có AI trong luồng (C1) | `build_understand`/`build_brief` thuần tất định; WL3 lấy chữ từ pack | Thêm tầng Codex — phải chốt Codex đề xuất **gì** (14.5 Q1) |
| **V2-2** | Chỉ 2 recipe đóng (C4) | `_FIN`/`_SALES` (`assistant_execution.py:22,38`) + `RESULT_COLUMNS` (`assistant_preview.py:30`) | Dựng recipe **động** từ quyết định của người dùng |
| **V2-3** | Preview chỉ chạy option A (C3) | `assistant_preview.py:96` — `optionId != "A"` ⇒ `AF_POLICY_UNSUPPORTED` | Phải tính được **cả hai nhánh** để so trước khi chốt |
| **V2-4** | WL1 **từ chối mẫu** (C6) | `assistant_ingest.py:264-266` — `sampleOnly:true` và `totalRows != len(rows)` đều bị chặn | Cho phép chế độ "chỉ mẫu để hiểu" **tách khỏi** chế độ "đọc đủ để tính" |
| **V2-5** | "20 dòng **ngẫu nhiên**" phá tất định | `deterministicCheckRowOffsets` (`taskpane.js:322`) cố ý tất định; `profile.py` tính trên toàn dữ liệu | Ngẫu nhiên **có seed tất định** + ghi `sampleOrdinals` vào artifact (14.5 Q3) |
| **V2-6** | Office.js chỉ đọc **workbook chứa pane** | `officeDocumentUrl()` trả **một** document; platform không cho liệt kê workbook đang mở khác | File khác phải qua **đường dẫn trên đĩa** (đã Save) — không phải "file đang mở" |

### 14.3 Cái đã có sẵn cho yêu cầu "preview A và B trước khi chốt"

Không phải làm từ số 0. `_scenario_fx_basis` (`assistant_findings.py:393-413`) **đã tính cả hai nhánh bằng số** và **tự kiểm đẳng thức**:

```python
if (measures["op"] + measures["fx"] != measures["variance"]
        or measures["bridge_total"] != measures["variance"]
        or measures["op_policy_b"] + measures["fx_zero"] != measures["variance"]
        or measures["scenario_ab_delta"] != abs(measures["fx"] - measures["fx_zero"])):
    raise ValueError("Kịch bản FX không đóng với measure nguồn")
```

trả về `scenarios: [{id:"A", values:[FX, Op]}, {id:"B", values:[FX_zero, Op_policy_b]}]` + `delta` — và **từ chối** nếu hai nhánh không đóng với nguồn.

⇒ Mẫu "hai nhánh + delta + kiểm đẳng thức" đã có, đã được test, và đã đi vào `brief.scenarios`/`brief.delta`. Việc của v2 là **tổng quát hoá mẫu này** ra ngoài cột FX, chứ không phải phát minh lại.

### 14.4 Cái gì dùng lại được — và cái gì là hàng dùng một lần

Nếu v2 được chốt, ước lượng theo trọng số file:

| Tầng | Dùng lại? | Ghi chú |
|---|---|---|
| WL1 ingest + snapshot + fingerprint | ✅ **Dùng lại** (thêm chế độ "sample-only" bên cạnh "full") | `assistant_ingest.py` 22 KB, `assistant_profile.py` 7 KB |
| WL2 understand (thống kê) | ✅ **Dùng lại** — đây chính là nguồn "điểm chưa rõ" | `assistant_roles.py`, `assistant_keys.py` ~31 KB |
| WL3 brief (cấu trúc SP/A-B/ledger) | ✅ **Dùng lại khung**, bỏ phần pack cứng | `assistant_brief.py` 13 KB |
| WL4 decisions/spec + hash | ✅ **Dùng lại** | `assistant_decisions.py`, `assistant_spec.py` ~20 KB |
| WL5 recipe + result_rows | ❌ **Hàng dùng một lần** | `_FIN`/`_SALES`, `RESULT_COLUMNS`, `_supported_recipe` — chính là phần "mỗi domain một tuple" |
| WL5 workbook builder / values-only | ✅ **Dùng lại** | `build_workbook`, `_verify_workbook`, `preview_marker` |
| WL5 reconcile (row/col + đẳng thức) | ✅ **Dùng lại khung**, bridge FIN là riêng | `assistant_reconcile.py` 20 KB |
| WL6 approval + apply | ✅ **Dùng lại nguyên** | `assistant_apply.py` generic hoàn toàn (bytes in → bytes out) |
| WL7 delta + record | ✅ **Dùng lại** | `assistant_delta.py` có phần `_FIN` riêng |
| Codex adapter | ✅ **Dùng lại** | `adapters/codex/excel.py` đã validate chặt |

**Kết luận định lượng:** phần **generic ≈ 70%**, phần **gắn recipe ≈ 30%** và tập trung ở WL5. Nên đừng đập bỏ; nhưng cũng **đừng đánh bóng WL5** — đó là phần sẽ thay.

### 14.5 Câu hỏi chặn — trạng thái chốt

| # | Câu hỏi | Trạng thái |
|---|---|---|
| **Q1** | Codex đề xuất **cái gì**? | ✅ **CHỐT (b)** — Codex đề xuất **công thức/thuật toán dạng typed operation**, engine chạy. Không phải (c). Xem 14.7 |
| **Q2** | Con số **cuối cùng** tính trên 20 dòng mẫu hay **toàn bộ** dữ liệu? | ⛔ **CHƯA TRẢ LỜI** — chặn P1 |
| **Q3** | "20 dòng ngẫu nhiên" thật ngẫu nhiên hay seed tất định? | ✅ **CHỐT** — **seed tất định**, cùng file → cùng 20 dòng, ghi `sampleOrdinals` vào artifact |
| **Q4** | Preview A/B cần số thật cả hai nhánh hay chỉ hình dạng? | ✅ **CHỐT** — preview A **và** B **trước** khi chốt, rồi mới freeze + làm chi tiết |
| **Q5** | File khác qua đường dẫn đĩa (đã Save) — chấp nhận? | ⛔ **CHƯA TRẢ LỜI** |
| **Q6** | Decision Record lưu ở đâu? | ✅ **CHỐT** — **Custom XML trong workbook**, theo đúng pattern Problem Chain |

### 14.6 Vì sao Q1 chọn (b) — và vì sao đây không phải việc lớn

**(a) và (b) khác nhau ở chỗ ai quyết định *cách tính*:**

| | Codex trả về | Ai quyết định cách tính | Đạt "mọi workbook"? |
|---|---|---|---|
| **(a)** | câu hỏi + nghĩa cột + định nghĩa bằng lời | **Con người viết recipe** (Python) | ❌ Không. Vẫn phải có recipe cho từng loại báo cáo |
| **(b)** | **kế hoạch thao tác có kiểu** (filter/group/aggregate/join/addColumn…) + biểu thức | **Codex đề xuất, engine validate + thi hành** | ✅ Có |

Nói gọn: **(a) chỉ làm nhãn, nên không giải phóng khỏi "mỗi báo cáo một recipe". (b) mới là thứ làm cho "mọi workbook" khả thi** — và (b) vẫn giữ "engine tính số" vì Codex chỉ *mô tả phép tính*, engine *thực thi* trên dữ liệu thật.

**Và đây là phát hiện quan trọng: dự án đã xây sẵn engine cho (b), đang chạy, đang trong gate.**

`pbip_assistant/powerquery/typed/registry.py:23-39` — **Typed v1, catalog đóng 15 thao tác:**

```
source.workbookTable · source.usedRange
table.filterRows · selectColumns · removeColumns · renameColumns · changeTypes
table.addColumn · sortRows · distinctRows · groupRows · aggregateRows
table.appendTables · mergeTables · expandTableColumn
```

**10 loại biểu thức** (`registry.py:42-45`): `literal, columnRef, compare, arithmetic, boolean, not, ifThenElse, coalesce, functionCall, safeDivide`.

Đây là một lõi Power-Query thu nhỏ — đủ cho filter / group / aggregate / join / append / cột tính toán. Và nó **đã có đủ**:

| Thành phần | File | Trạng thái |
|---|---|---|
| Validate (44 KB guard) | `powerquery/typed/validation.py` | Đang chạy |
| Compile sang M | `powerquery/typed/compiler.py` (24 KB) | Đang chạy |
| Store: history, CAS, HEAD, staging, approval, cache | `powerquery/typed/store.py` (60 KB) | Đang chạy, wired vào task pane |
| **Codex soạn plan** | `adapters/codex/typed.py:153 CodexTypedRunner` (12 KB) | **Đã có** |
| Preview → approve → apply values-only | `PQPreviewStore` + `writeTypedPrepared` | Đang chạy, có UI, trong gate |

⇒ **WL5 recipe của Assistant là một bản trùng lặp, yếu hơn, của một engine đã có.** `_FIN`/`_SALES` chỉ là 2 kế hoạch hardcode của đúng engine đó.

### 14.7 Kiến trúc v2 đề xuất — thay WL5 bằng Typed v1

```text
WL1  ingest      đọc 20 dòng (seed tất định) hoặc full     ✅ dùng lại + thêm chế độ mẫu
WL2  understand  thống kê → "điểm chưa rõ" để hỏi khách     ✅ dùng lại nguyên (đây là giá trị riêng)
WL3  Codex       khách trả lời → Codex soạn Typed v1 plan   ⚙ adapters/codex/typed.py đã có
WL4  freeze      hash snapshot + plan + quyết định A/B      ✅ dùng lại khung
WL5  execute     validate → compile → preview values-only    ✅ DÙNG LẠI Typed store (bỏ recipe)
WL6  approve     approval một lần → apply vào workbook       ✅ DÙNG LẠI Typed (bỏ apply_result)
WL7  record      Decision Record + Custom XML persist        ✅ dùng lại + MỚI: persist
```

**Hệ quả — và đây là điều làm v2 rẻ hơn vẻ ngoài của nó:**

| Phần | Số phận |
|---|---|
| `assistant_preview.py` `_FIN`/`_SALES`/`RESULT_COLUMNS`/`_supported_recipe` | ❌ bỏ khỏi v2 (giữ cho v1.x) |
| `assistant_preview.py` `build_workbook`, `preview_marker`, values-only verify | ✅ dùng lại |
| `assistant_reconcile.py` | ✅ khung dùng lại; **reconcile trở nên quan trọng hơn** vì phải kiểm plan do Codex soạn |
| `assistant_apply.py` (21 KB) | ⚠ phần lớn **dư thừa** — Typed đã apply values-only + read-back. Giữ cho v1.x |
| `assistant_execution.py` `compile_steps` | ❌ thay bằng Typed `compiler` |
| WL2 `assistant_roles/keys/understand` | ✅ **giữ — đây là thứ tạo câu hỏi, thứ Typed không có** |
| WL7 `assistant_record.py` | ✅ giữ, **và là chỗ khác biệt so với Typed**: Typed không có Assumption Ledger / provenance |

**Điểm mấu chốt:** Typed làm *thi hành*. Assistant WL1–WL4 + WL7 làm *hiểu, hỏi, chốt, ghi có nhãn*. Hai thứ **bổ sung**, không cạnh tranh. v2 = **ghép** chúng, không phải viết mới.

**Phải giải quyết trong v2:**

1. **Reconcile khi không còn recipe cố định.** Mẫu số kiểm soát (`control total`) phải suy từ plan, không từ `_FIN`. Đây là việc khó nhất của v2.
2. **A/B preview trước khi chốt (Q4).** Hai plan khác nhau → hai preview. Cần: cùng snapshot, cùng approval, hai preview hash riêng, người dùng chọn một rồi mới freeze. Mẫu đẳng thức có sẵn ở `_scenario_fx_basis` nhưng phải tổng quát hoá.
3. **Chế độ "chỉ mẫu" của WL1 (V2-4).** `add_open_workbook` đang chặn `sampleOnly`. Phải tách: `mode:"discover"` (mẫu, không được tính số cuối) vs `mode:"compute"` (đủ dữ liệu). **Một payload mẫu không bao giờ được dùng để tính số cuối** — nếu không thì "báo cáo" chỉ là báo cáo trên 20 dòng.
4. **Custom XML (Q6).** Namespace mới, không dùng chung `urn:local-data-copilot:pq-problem-chain:v1`. Lưu `record.id` + `record.hash` + `snapshotHash` + spec fingerprint; **không** lưu raw cells (record engine đã từ chối binary/đường dẫn tuyệt đối).

### 14.8 Còn lại phải chốt

| # | Việc | Chặn cái gì |
|---|---|---|
| Q2 | Số cuối tính trên 20 dòng hay toàn bộ? | Toàn bộ workflow. Nếu 20 dòng thì không được gọi là báo cáo; nếu toàn bộ thì WL1 phải đọc full (đã thiết kế ở v1.x, C6) |
| Q5 | File khác qua đường dẫn đĩa — chấp nhận? | Nếu cần "nhiều file đang mở" thì **không làm được**; phải là đường dẫn |
| Q7 | **Wire v1.x trước hay nhảy thẳng v2?** | Lịch và phạm vi. Xem 14.9 |

### 14.9 Khuyến nghị về thứ tự — đã đổi so với bản 1.3

Trước đây em đề xuất "wire v1.x trước". **Sau khi biết Q1 = (b) và Typed đã có sẵn, khuyến nghị đổi thành:**

| Phương án | Kết luận |
|---|---|
| Wire v1.x đầy đủ rồi v2 | ⚠ **Giảm ưu tiên.** WL5 + WL6 của v1.x là 48 KB sẽ bị Typed thay ⇒ làm đầy đủ là lãng phí |
| **Wire v1.x "mỏng" để đóng vòng, rồi chuyển WL5 sang Typed** ✅ **đề xuất** | Dùng v1.x để chứng minh WL1→WL4 + WL7 (phần **giữ lại**) chạy thật; **không** đầu tư vào WL5/WL6 v1.x |
| Nhảy thẳng v2 | Rủi ro: Q2/Q5 chưa chốt; reconcile-phi-recipe chưa có thiết kế |

**Cụ thể:**
- **P1–P1.5** (ingest → understand → brief, smoke) giữ nguyên — đều là phần **dùng lại**.
- **P2–P3**: làm WL4 + WL7; với WL5/WL6 chỉ làm **đủ để một đường chạy thông**, không tối ưu — vì sẽ thay bằng Typed.
- **P4** UI giữ nguyên kế hoạch.
- **P8 (mới)**: thay WL5/WL6 bằng Typed v1 + reconcile-phi-recipe + Custom XML persist. Đây là pha v2 thật sự.


---

*Mọi thay đổi hợp đồng trong spec này phải cập nhật đồng thời: mục 4 (HTTP), mục 5 (DOM), mục 7 (test ID), và `ASSISTANT_TRACEABILITY.md`. Không được nới 7 luật chống "giả kết quả" ở `ASSISTANT_FLOW_SPEC.md` §9.*
