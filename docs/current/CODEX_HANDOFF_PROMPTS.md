# CODEX_HANDOFF_PROMPTS — Bàn giao thi công v2 cho Codex

| Trường | Giá trị |
|---|---|
| Phiên bản | 1.0 — 30/10/2026 |
| Dùng cho | Codex (hoặc bất kỳ agent có khả năng chia subagent) thi công `ASSISTANT_V2_BUILD_SPEC.md` |
| Cách dùng | Dán **§1 (MASTER PROMPT)** vào agent điều phối. Nó tự chia sóng và dán prompt ở §2 cho từng subagent |

> **Nguyên tắc của bộ prompt này:** mỗi subagent chỉ chạm **file của mình**. Nếu hai agent cùng sửa `taskpane.js` hoặc `server.py`, kết quả sẽ hỏng và không ai biết vì sao. Mọi ràng buộc file nằm trong từng prompt.

---

## §0. Bản đồ sóng (dùng khi điều phối)

```text
Wave A  (3 agent song song, không phụ thuộc nhau)
  A1  P0-1  guard cardinality          sources/assistant_brief.py
  A2  P0-2  Total Row                  excel_addin/taskpane.js + fake host + 1 test JS
  A3  P3a   executor typed_local       powerquery/typed_local/  (gói mới, độc lập hoàn toàn)

Wave B  (2 agent song song, sau khi Wave A xanh)
  B1  P1a   store + 11 route (registrar) sources/assistant_session.py,
                                          coordinator/endpoints/assistant*.py,
                                          coordinator/server.py            ← MỘT LẦN DUY NHẤT
  B2  P1b   Office.js đọc + UI card 01–04  excel_addin/taskpane.{html,js} + test JS

Wave C  (1 agent, sau B)
  C1  P2    Codex sinh 2 nhánh          adapters/codex/assistant_plan.py (tái dùng runner Typed),
                                         endpoints/assistant_plan.py

Wave D  (1 agent, sau C + A3)
  D1  P3b   reconcile + /branches        sources/assistant_reconcile_v2.py,
                                         endpoints/assistant_exec.py

Wave E  (2 agent song song, sau D)
  E1  P4    freeze + duyệt + ghi         sources/assistant_freeze.py,
                                         endpoints/assistant_freeze.py
  E2  P5a   Custom XML helper            excel_addin/assistant_custom_xml.js

Wave F  (1 agent, sau E)
  F1  P5b   record + persist             endpoints/assistant_record.py,
                                         sources/assistant_record_v2.py

Wave G  (1 agent, sau F)
  G1  P6    UI hoàn chỉnh + tài liệu      excel_addin/taskpane.*, docs/current/*,
                                         tests/required_cases.json
```

**Vì sao chia như vậy:** A3 (executor) là khối Python lớn nhất và **không phụ thuộc** HTTP/UI ⇒ chạy song song ngay từ đầu. B1 giữ độc quyền `server.py` để đăng ký **toàn bộ 11 route một lần**, nhờ đó các sóng sau không tranh chấp file trung tâm.

---

## §1. MASTER PROMPT — dán vào agent điều phối

```text
Bạn là agent điều phối thi công một tính năng lớn trong repo C:\Users\COLAIG\Downloads\power_bi
(Excel add-in "Local Data Copilot", Python 3.13 stdlib + Office.js task pane, không thêm dependency).

NHIỆM VỤ: thi công docs/current/ASSISTANT_V2_BUILD_SPEC.md từ P0 tới P6, chia thành các sóng
và giao cho subagent theo đúng file ownership. Mục tiêu: sau P6 có một sản phẩm chạy được
(mọi workbook → hiểu → hỏi → Codex sinh kế hoạch → xem A/B có số → chốt → ghi → record bền).

TRƯỚC KHI LÀM BẤT CỨ GÌ, hãy tự đọc:
  1. docs/current/ASSISTANT_V2_BUILD_SPEC.md   ← kế hoạch thi công. ĐÂY là nguồn sự thật.
  2. AGENTS.md                                 ← luật dự án, bắt buộc
  3. docs/current/ASSISTANT_INTEGRATION_SPEC.md  ← chỉ để tra chi tiết (§4.4 lỗi HTTP, §5 DOM,
                                                  §6 Office.js, §12 smoke script). KHÔNG implement
                                                  các mục WL5/WL6 recipe của tài liệu này.
  4. docs/current/CODEX_HANDOFF_PROMPTS.md     ← chính file này (§0 sóng, §2 prompt từng agent)

SAU KHI ĐỌC, làm theo thứ tự:

BƯỚC 1 — BASELINE (tự làm, không giao agent)
  - Chạy: py tools/run_checks.py fast
  - Ghi lại dòng tổng kết (gate=fast run=… failed=… elapsed=…). Nếu gate đã ĐỎ, ghi lại
    tên test đỏ và mã lỗi — đó là baseline, không phải do bạn gây ra.
  - Không sửa gì ở bước này.

BƯỚC 2 — SÓNG A (3 subagent song song, dán đúng prompt §2.1, §2.2, §2.3)
  Giao cùng lúc. Chờ cả 3 báo xong. Không gộp báo cáo, đọc từng báo cáo.

BƯỚC 3 — CỔNG SAU SÓNG A
  - py tools/run_checks.py fast   → phải XANH (trừ những test đỏ đã có từ baseline và không
    liên quan tới 3 agent vừa rồi)
  - Nếu một agent báo BLOCKED hoặc gate đỏ do nó: dừng, báo lại người dùng, KHÔNG tự chữa
    bằng cách hạ assertion.

BƯỚC 4 — SÓNG B (2 subagent song song, §2.4 và §2.5). Cổng: gate xanh + smoke dừng ở understand.
BƯỚC 5 — SÓNG C (1 agent, §2.6). Cổng: gate xanh + smoke dừng ở plan.
BƯỚC 6 — SÓNG D (1 agent, §2.7). Cổng: gate xanh + smoke dừng ở branches.
BƯỚC 7 — SÓNG E (2 agent song song, §2.8 và §2.9). Cổng: gate xanh + smoke dừng ở apply.
BƯỚC 8 — SÓNG F (1 agent, §2.10). Cổng: smoke đủ 11 route logic, 13 POST gồm ingest compute và receipt /apply, PASS.
BƯỚC 9 — SÓNG G (1 agent, §2.11). Cổng: gate xanh + 14 case JS xanh + tài liệu cập nhật.

BƯỚC 10 — BÁO CÁO CUỐI cho người dùng, gồm đúng những mục này:
  - Bảng: sóng | agent | trạng thái | file tạo/sửa | test thêm | ghi chú lệch spec
  - Dòng tổng kết gate fast cuối cùng (dán nguyên văn)
  - Danh sách việc CHƯA làm được và lý do cụ thể
  - Những gì CHƯA có bằng chứng live (Office.js/Excel thật, Codex thật) — phải nói rõ là "chưa chạy"

LUẬT BẤT BIẾN (áp cho cả bạn và mọi subagent):
  1. Một file = một chủ. Không sửa file ngoài danh sách ownership của mình. Nếu thấy cần sửa
     file của agent khác → DỪNG và báo, để agent điều phối xếp lịch.
  2. Không bao giờ làm yếu test cho xanh. Xoá test chỉ được khi có test thay thế giữ hành vi
     (AGENTS.md), và phải ghi rõ test nào thay test nào.
  3. Không bao giờ tuyên bố đã chạy Office.js/Excel/Codex thật nếu chưa chạy. Gate fake-host
     không phải bằng chứng live.
  4. Không đổi version application/npm/HTTP (1.2.0) hay manifest (1.2.0.0).
  5. Không thêm dependency Python/js mới. Chỉ standard library + những gì repo đang có.
  6. Nguồn Excel/PBIP là read-only. Không ghi vào file người dùng.
  7. AI không bao giờ sinh số. Codex chỉ trả kế hoạch; engine tính.
  8. Không dùng PowerShell để đọc/ghi nội dung file (.md, .py, .js).
     PowerShell 5.1 trong môi trường này đọc UTF-8 thành ANSI và SẼ làm hỏng tiếng Việt.
     Luôn dùng công cụ đọc/ghi file của agent.

ĐỊNH DẠNG BÁO CÁO của mỗi subagent (yêu cầu đúng, đừng nhận báo cáo lan man):
  PHASE: <A1|A2|…>
  STATUS: DONE | BLOCKED | PARTIAL
  CREATED: <path>[, …]
  MODIFIED: <path>[, …]
  TESTS_ADDED: <case id>[, …]
  GATE: <dòng tổng kết nguyên văn của py tools/run_checks.py fast>
  DEVIATIONS: <chỗ phải làm khác spec + lý do> hoặc NONE
  BLOCKERS: <cụ thể> hoặc NONE
```

---

## §2. Prompt cho từng subagent

Mỗi prompt dưới đây **tự đứng được** — subagent không đọc được hội thoại của bạn.

### §2.1 — A1 · P0-1 Guard cardinality

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

BỐI CẢNH: repo này có một lỗi đang làm gate đỏ. Test
tests.contracts.test_assistant_behavior_guards.AssistantBehaviorGuardTests.test_invalid_relationship_cardinality_is_rejected_before_brief
set relationships[0].cardinality = "INVALID_CARDINALITY", tính lại understandHash (nên hash vẫn khớp),
rồi gọi build_brief(...) và kỳ vọng nó NÉM lỗi (InputError hoặc ValueError).
Hiện tại build_brief chấp nhận, nên test đỏ.

NHIỆM VỤ: sửa để cardinality không hợp lệ bị từ chối tại biên WL2→WL3, TRƯỚC khi hash được coi là
đủ điều kiện.

FILE BẠN ĐƯỢC SỬA (chỉ những file này):
  - pbip_assistant/sources/assistant_brief.py
  - pbip_assistant/sources/assistant_understand.py   (chỉ nếu bạn đặt guard ở understand_hash)
KHÔNG được sửa:
  - file nào khác, kể cả test (test đang đỏ là bằng chứng, phải giữ nguyên ID và nội dung)
  - pbip_assistant/excel_addin/*, coordinator/*

HƯỚNG LÀM:
  1. Đọc pbip_assistant/sources/assistant_keys.py:244-258 để biết catalog cardinality thực tế
     được sinh ra. Đọc assistant_roles.py:106-108 để biết giá trị nào được dùng.
  2. Đọc assistant_understand.py:86-95 (understand_hash) và assistant_brief.py:95-118 (_build).
  3. Thêm kiểm tra: mọi phần tử relationships[].cardinality phải thuộc tập hợp lệ
     {"1:1","1:N","N:1","N:N"}. Tập này phải khai báo một lần thành hằng số có tên, không rải rác.
  4. Đặt guard ở nơi chạy TRƯỚC khi _build dùng understand — tốt nhất trong understand_hash hoặc
     ở đầu _build ngay sau khi kiểm hash. Lỗi phải là InputError với mã AF_BRIEF_INVALID
     (đi theo tiền lệ _invalid() sẵn có trong assistant_brief.py).
  5. Guard phải chấp nhận cả 4 giá trị hợp lệ (không được quá tay chặn nhầm).

ACCEPTANCE:
  - Test đỏ ở trên XANH.
  - Thêm 1 test mới: cả 4 cardinality hợp lệ đều đi qua được boundary (đặt trong cùng file test
    guards hoặc file test hiện có của WL2/WL3 — nếu bạn chọn file test nào thì ghi vào báo cáo).
  - py tools/run_checks.py fast  → dán nguyên văn dòng tổng kết.
  - py -m unittest tests.contracts.test_assistant_behavior_guards -v  → xanh.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.2 — A2 · P0-2 Total Row

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

BỐI CẢNH: Excel table có thể có "Total Row". Hàm readWorkbook() trong
pbip_assistant/excel_addin/taskpane.js:334-438 dùng table.getRange() — trả CẢ header VÀ totals row —
nhưng code chỉ trừ 1 dòng header (dòng 392 và 430). Hệ quả: totalRows cao hơn thực tế 1, và dòng
tổng cộng bị lấy mẫu như dòng dữ liệu (deterministicCheckRowOffsets ghim các offset cuối nên dòng
cuối luôn bị lấy). Đây là finding 3 của audit.

NHIỆM VỤ: sửa để header và data body được đọc riêng, totals row không bao giờ trở thành dữ liệu.

FILE BẠN ĐƯỢC SỬA (chỉ những file này):
  - pbip_assistant/excel_addin/taskpane.js   (chỉ trong readWorkbook, khoảng dòng 334-438)
  - tests/taskpane/taskpane_usedrange.js
  - tests/taskpane/taskpane_live_analyze.js
  - tests/taskpane/taskpane_pq.js            (chỉ phần fake host table, nếu cần)
  - tests/taskpane/taskpane_totals_row.js    (TẠO MỚI)
  - tests/taskpane/test_taskpane_js.py       (thêm đúng 1 method để chạy file test mới)
KHÔNG được sửa:
  - function nào khác trong taskpane.js ngoài readWorkbook
  - taskpane.html, taskpane.css
  - server, endpoint, python engine

HƯỚNG LÀM:
  1. Thay table.getRange() bằng table.getDataBodyRange() cho dữ liệu và
     table.getHeaderRowRange() cho header (ExcelApi 1.1 có cả hai; pane đã yêu cầu >= 1.4).
  2. totalRows cho table = dataBodyRange.rowCount (KHÔNG trừ header nữa).
     Số dòng mẫu tính từ dataBodyRange, và getCell(offset,0) KHÔNG cộng 1.
  3. Giữ nguyên hành vi cho sheet không có table (usedRange): dòng đầu là header, vẫn trừ 1.
  4. Giữ nguyên tên field trong snapshot (tables[].totalRows, tables[].rows, sampleOrdinals …)
     để không phá core/workbook_snapshot.py và server.
  5. Cập nhật fake host trong các file test được liệt kê: object table giả phải có
     getDataBodyRange() và getHeaderRowRange(); nếu không, test cũ sẽ chết.

TEST MỚI (tests/taskpane/taskpane_totals_row.js) — bắt buộc có 3 case:
  a) table có totals row: header 3 cột, 2 dòng dữ liệu + 1 dòng tổng ⇒ totalRows === 2,
     và rows KHÔNG chứa dòng tổng.
  b) table KHÔNG có totals row ⇒ totalRows === số dòng dữ liệu.
  c) table chỉ có header, không có dòng dữ liệu ⇒ totalRows === 0, rows rỗng.
Theo đúng pattern fake-host hiện có: vm.runInNewContext + export globalThis.__readWorkbook,
console.log("… passed") ở cuối, process.exitCode = 1 khi lỗi.

ACCEPTANCE:
  - 3 case mới xanh; 12 script JS cũ vẫn xanh.
  - Thêm 1 method vào tests/taskpane/test_taskpane_js.py chạy file mới (timeout 15,
    assert returncode 0 và "passed" in stdout).
  - py tools/run_checks.py fast → dán nguyên văn dòng tổng kết.
  - node --check pbip_assistant/excel_addin/taskpane.js → không lỗi.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.3 — A3 · P3a Executor `typed_local`

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

BỐI CẢNH: dự án có catalog đóng 15 thao tác Power Query kiểu (Typed v1) với validate + compile sang M,
nhưng việc THI HÀNH hiện phải chạy M trong Excel qua COM (chậm, cần Excel). Theo
docs/current/ASSISTANT_V2_BUILD_SPEC.md §6 — quyết định G đã chốt: viết executor PYTHON THUẦN để
thi hành cùng plan đó, không dùng Excel.

NHIỆM VỤ: tạo gói mới pbip_assistant/powerquery/typed_local/ thi hành được plan Typed v1 trên
bảng trong bộ nhớ, tất định, dùng Decimal cho số.

ĐỌC TRƯỚC:
  - pbip_assistant/powerquery/typed/registry.py       ← 15 thao tác + 10 loại biểu thức (catalog đóng)
  - pbip_assistant/powerquery/typed/model.py          ← OPERATION_ARITY, PARAMETER_KEYS, EXPRESSION_KEYS
  - pbip_assistant/powerquery/typed/validation.py:95-510  ← chuẩn hoá biểu thức và tham số
  - pbip_assistant/powerquery/typed/compiler.py       ← đọc để hiểu NGỮ NGHĨA của từng thao tác theo M
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §6.1–§6.5 ← hợp đồng + 4 tầng test bắt buộc

FILE BẠN ĐƯỢC TẠO/SỬA (chỉ những file này):
  - pbip_assistant/powerquery/typed_local/__init__.py
  - pbip_assistant/powerquery/typed_local/executor.py
  - pbip_assistant/powerquery/typed_local/expressions.py   (nếu bạn tách)
  - tests/unit/test_typed_local.py
  - tests/unit/test_typed_local_parity.py  (chỉ khung, skipUnless powershell.exe)
KHÔNG được sửa:
  - bất kỳ file nào trong pbip_assistant/powerquery/typed/   (catalog là ĐÓNG, chỉ đọc)
  - coordinator/*, excel_addin/*, sources/*
  - tests/required_cases.json (agent điều phối lo)

HỢP ĐỒNG PUBLIC (giữ đúng chữ ký này):
  def execute_plan(plan: dict, tables: list[dict]) -> dict
  Trả {"columns":[{"name","type"}], "rows":[[cell]], "rowCount": int, "fanOut": {...}|None}
  - plan đã được validate trước đó; nếu plan sai shape thì ném InputError("AF_EXECUTOR_INVALID").
  - Số dùng Decimal; ra JSON thì chuyển thành string.
  - Không đọc đĩa, không mạng, không gọi thời gian hệ thống.
  - Giới hạn MAX_ROWS=100_000, MAX_COLUMNS=256, vượt ⇒ InputError("AF_EXECUTOR_LIMIT").

PHẢI PHỦ ĐỦ 15 THAO TÁC:
  source.workbookTable, source.usedRange, table.filterRows, table.selectColumns,
  table.removeColumns, table.renameColumns, table.changeTypes, table.addColumn,
  table.sortRows, table.distinctRows, table.groupRows, table.aggregateRows,
  table.appendTables, table.mergeTables, table.expandTableColumn

VÀ 10 LOẠI BIỂU THỨC:
  literal, columnRef, compare, arithmetic, boolean, not, ifThenElse, coalesce,
  functionCall, safeDivide

NGỮ NGHĨA PHẢI TẤT ĐỊNH (ghi rõ trong docstring):
  - distinctRows giữ dòng ĐẦU TIÊN
  - sortRows ổn định (stable sort), nhiều khoá
  - groupRows/aggregateRows sắp theo khoá nhóm tăng dần
  - Quyết định người dùng 30/10/2026: mergeTables giữ đủ 6 joinKind theo catalog và cột bảng lồng của Typed; expandTableColumn mở rộng dòng. Không ép các joinKind khác thành inner; giữ thứ tự tất định và báo fan-out khi mở rộng.
  - average trên tập rỗng ⇒ None (KHÔNG phải 0); min/max toàn null ⇒ None
  - text so sánh phân biệt hoa thường, byte-wise (không phụ thuộc locale)
  - mergeTables phải đếm fan-out (số dòng sau / trước) và trả trong "fanOut"

TEST BẮT BUỘC (tests/unit/test_typed_local.py):
  - Mỗi thao tác trong 15 có ít nhất 1 case, KẾT QUẢ KỲ VỌNG VIẾT TAY trong test,
    không suy ra từ chính executor.
  - Mỗi thao tác có thêm case biên: null, rỗng, trùng khoá (nơi áp dụng). Tổng ~40 case.
  - 1 case: chạy 2 lần cùng input ⇒ output giống hệt.
  - 1 case: tổng tiền dùng Decimal, không sai số float.
  - 1 case: vượt giới hạn dòng ⇒ AF_EXECUTOR_LIMIT.
  - 1 case: join gây nhân dòng ⇒ fanOut có số đúng.

PARITY (tests/unit/test_typed_local_parity.py):
  - Viết KHUNG: một plan phủ cả 15 thao tác, hàm run_m_in_excel(...) để trống có
    raise unittest.SkipTest, và test skipUnless(shutil.which("powershell.exe")).
  - Agent sau sẽ nối dây thật; bạn chỉ cần khung + ghi chú rõ.

ACCEPTANCE:
  - py -m unittest tests.unit.test_typed_local -v  → xanh, đếm số case.
  - py tools/run_checks.py fast → dán nguyên văn dòng tổng kết.
  - Không import gì ngoài standard library và package hiện có.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.4 — B1 · P1a Store + router (registrar)

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §1, §4.1, §4.2, §5   ← kiến trúc, ingest 2 chế độ, HTTP
  - docs/current/ASSISTANT_INTEGRATION_SPEC.md §4.4–§4.5          ← CÁCH MAP LỖI HTTP và wire shape
  - pbip_assistant/coordinator/server.py (dòng 147-172, 396-428, 430-490, 616-621)
  - pbip_assistant/coordinator/endpoints/analysis.py              ← mẫu endpoint mỏng
  - pbip_assistant/sources/assistant_ingest.py                    ← resolve/add_open_workbook
  - pbip_assistant/sources/assistant_understand.py                ← build_understand
  - pbip_assistant/sources/assistant_profile.py                   ← build_snapshot

NHIỆM VỤ: (1) store giữ state WL1+WL2, (2) đăng ký TOÀN BỘ 11 route cho v2 MỘT LẦN, (3) hiện thực
route của sóng này, (4) tạo file stub cho các sóng sau.

FILE BẠN ĐƯỢC TẠO/SỬA:
  TẠO:
  - pbip_assistant/sources/assistant_session.py
  - pbip_assistant/coordinator/endpoints/assistant.py          (router mỏng, không logic)
  - pbip_assistant/coordinator/endpoints/assistant_source.py   (session, ingest, understand, state, reset)
  - pbip_assistant/coordinator/endpoints/assistant_plan.py     (STUB)
  - pbip_assistant/coordinator/endpoints/assistant_exec.py     (STUB)
  - pbip_assistant/coordinator/endpoints/assistant_freeze.py   (STUB)
  - pbip_assistant/coordinator/endpoints/assistant_record.py   (STUB)
  - tests/integration/test_assistant_flow_api.py
  SỬA:
  - pbip_assistant/coordinator/server.py      ← DUY NHẤT sóng này được sửa; các sóng sau KHÔNG
  - pbip_assistant/sources/assistant_ingest.py ← CHỈ THÊM hàm mới, không đổi hàm cũ
Nếu bạn thấy cần sửa file khác → DỪNG, báo BLOCKED.

YÊU CẦU CHI TIẾT:

A) pbip_assistant/sources/assistant_session.py — AssistantSessionStore
   - RLock; method public đều giữ lock.
   - Giữ: _session (dict cho ingest.resolve, giữ "_assistant_ingest"), _root (Path tuyệt đối, KHÔNG
     trả về client), _ingested, _raw_tables, _snapshot, _understand, _stage.
   - Method: reset(), close(), bind_root(root), ingest(requests), understand(), state().
   - _STAGES = ("new","ingested","understood","planning","branched","frozen","approved","applied","recorded")
   - Điều kiện sai thứ tự ⇒ InputError("AF_STAGE_INVALID").
   - close() phải gọi ingest.close(session) và xoá artifact; không xoá file, không Save.
   - Ghi chú rõ trong docstring: store này CHƯA giữ approval; sóng E sẽ thêm.

B) pbip_assistant/sources/assistant_ingest.py — THÊM add_workbook_selection(payload)
   - Hàm mới, KHÔNG sửa add_open_workbook cũ (caller khác còn dùng).
   - Chấp nhận mode ∈ {"discover","compute"}.
   - Validate theo đúng bảng ở ASSISTANT_V2_BUILD_SPEC §4.1:
     sampleOrdinals là int tăng dần không trùng trong [0,totalRows);
     discover: len(rows)==len(sampleOrdinals) và <= 20;
     compute: len(rows)==totalRows;
     mọi dòng cùng độ rộng header.
   - Raw table trả về có thêm "mode", "sampleOrdinals", "totalRows".
   - Sai ⇒ trả result lỗi theo đúng pattern _fail() sẵn có (WL1 trả lỗi, không raise), mã AF_INGEST_FAILED.
   - Thêm hằng MODE_DISCOVER = "discover", MODE_COMPUTE = "compute".

C) coordinator/endpoints/assistant.py — router mỏng
   - Một mixin AssistantEndpoints ghép 5 mixin con vừa tạo (source/plan/exec/freeze/record).
   - Chỉ chứa _assistant_error(exc, *, consumed=None) map mã lỗi engine → HTTP theo bảng
     ASSISTANT_INTEGRATION_SPEC §4.4; nhớ bảng mã adapter mới §4.5.
   - Không giữ state, không tính số.

D) coordinator/server.py — SỬA MỘT LẦN, đủ cho mọi sóng
   - import AssistantEndpoints, thêm vào danh sách base class của ExcelAddinRequestHandler.
   - Thêm ASSISTANT_PATHS (11 route) vào STATE_PATHS; thêm "/api/assistant/plan-draft" vào
     CODEX_JOB_PATHS.
   - Thêm 11 dòng vào POST_ENDPOINTS:
       /api/assistant/session      _post_assistant_session
       /api/assistant/ingest       _post_assistant_ingest
       /api/assistant/understand   _post_assistant_understand
       /api/assistant/plan-draft   _post_assistant_plan_draft
       /api/assistant/branches     _post_assistant_branches
       /api/assistant/freeze       _post_assistant_freeze
       /api/assistant/approvals    _post_assistant_approvals
       /api/assistant/apply        _post_assistant_apply
       /api/assistant/record       _post_assistant_record
       /api/assistant/state        _post_assistant_state
       /api/assistant/reset        _post_assistant_reset
     Mọi method PHẢI tồn tại (stub trong file tương ứng) để server không chết lúc import.
   - Thêm _error(..., extra=None) theo ASSISTANT_INTEGRATION_SPEC §4.4 (giữ tương thích caller cũ).
   - ExcelAddinApp: thêm self.assistant = AssistantSessionStore(); gọi reset() trong
     _clear_session_state(); gọi close() trong close().
   - Bootstrap capabilities: thêm "assistantFlowV2": True và "assistantFlowStages": [...].

E) Endpoint hiện thực ở sóng này (assistant_source.py):
   - /session: nhận {root}. Validate tuyệt đối/tồn tại/là thư mục/reparse point ⇒
     InputError("ASSISTANT_ROOT_INVALID"). Trả stage, rootLabel (chỉ tên thư mục cuối), limits.
   - /ingest: nhận {requests}. Trả 200 với stage "ingested" hoặc "ingest_blocked" kèm
     errors/requiresRename/csvOptions/warnings (theo §4.3 doc v1.x). Body limit:
     MAX_ASSISTANT_INGEST_JSON_BYTES = 72 MiB cho ingest, 8 MiB cho các route khác — thêm
     2 hằng này vào coordinator/endpoints/__init__.py (được phép sửa file đó).
   - /understand: trả understand + questions[] + snapshot summary. Sinh questions theo
     ASSISTANT_V2_BUILD_SPEC §4.2 (từ warnings, relationships needs_confirm/fanOutRisk,
     roles confidence thấp, nullRate cao, assumptions). Câu hỏi TẤT ĐỊNH, mỗi câu có evidence.
   - /state và /reset theo spec.

F) tests/integration/test_assistant_flow_api.py — dùng harness của
   tests/integration/test_excel_addin_server.py (server thật, port thật, token thật).
   Case tối thiểu: session+ingest+understand trên fixture tests/fixtures/assistant/tp-fin/source,
   stage đi đúng, questions không rỗng; ingest blocked khi trùng tên; root tương đối ⇒ 400;
   thiếu sampleOrdinals ⇒ lỗi; discover vượt 20 dòng ⇒ lỗi.

ACCEPTANCE:
  - py tools/run_checks.py fast → xanh, dán nguyên văn dòng tổng kết.
  - Không sửa test nào đang xanh.
  - Ghi rõ trong báo cáo: danh sách 11 route đã đăng ký và file stub nào còn trống.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.5 — B2 · P1b Office.js đọc full + UI card 01–04

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_INTEGRATION_SPEC.md §5.1–§5.6 (DOM, máy trạng thái, quy tắc copy)
  - docs/current/ASSISTANT_INTEGRATION_SPEC.md §6.1–§6.4 (đọc Office.js full values, bẫy ngày)
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §4.1, §4.2, §8
  - pbip_assistant/excel_addin/taskpane.html (dòng 40-135) và taskpane.js (dòng 1-60 state,
    dòng 160-225 api(), dòng 334-438 readWorkbook, dòng 3484-3492 switchTab, dòng 3930-4093 init)

NHIỆM VỤ: đưa tab Trợ lý sang luồng v2 — thêm cách đọc full values và 4 card đầu. KHÔNG sửa
pipeline advice đang có (sóng G sẽ dọn).

FILE BẠN ĐƯỢC SỬA (chỉ những file này):
  - pbip_assistant/excel_addin/taskpane.html
  - pbip_assistant/excel_addin/taskpane.js
  - pbip_assistant/excel_addin/taskpane.css       (chỉ thêm class mới nếu cần)
  - tests/taskpane/taskpane_assistant_flow.js     (TẠO MỚI)
  - tests/taskpane/test_taskpane_js.py            (thêm đúng 1 method)
KHÔNG được sửa:
  - server.py, endpoint, engine python
  - readWorkbook() — agent A2 đã/đang sửa hàm này; bạn viết hàm MỚI riêng
  - các hàm analyze()/renderPlan()/… của advice flow

PHẢI LÀM:

1) state.flow = { stage:"new", v2Capability:false, rootLabel:"", snapshot:null, sources:[],
   tables:[], selectedTableIds:new Set(), csvOptions:[], requiresRename:[], errors:[],
   warnings:[], questions:[], answers:{}, understand:null, busy:false }
   Không dùng state.busy toàn cục cho luồng; luồng có nhịp riêng.

2) flowNowIso() → new Date().toISOString() cho các trường *At.
   isoDateLocal(date) → dùng getFullYear/getMonth+1/getDate, TUYỆT ĐỐI KHÔNG toISOString
   (UTC+7 sẽ lệch 1 ngày — đây là bug đã ghi trong spec).

3) flowReadOpenWorkbook() — Excel.run; với mỗi worksheet:
   - có table: dùng table.getDataBodyRange() cho dữ liệu + table.getHeaderRowRange() cho header
   - không có table: getUsedRangeOrNullObject(true), dòng đầu là header
   - flowHeaderCell(value,index): rỗng ⇒ columnLetter(index); String(value).trim() nếu không
   - flowCell(value): Date ⇒ isoDateLocal; number ⇒ String(value); boolean ⇒ "TRUE"/"FALSE";
     null/undefined ⇒ ""
   - Trả [{sheet,name,table,header,rows,totalRows,totalColumns}]
   - Guard phía client: FLOW_MAX_ROWS=100000, FLOW_MAX_COLUMNS=512, FLOW_MAX_CELLS=400000;
     vượt ⇒ lỗi rõ ràng, KHÔNG gửi request.

4) flowSampleOrdinals(header, rows, totalRows) — mẫu 20 dòng TẤT ĐỊNH theo
   ASSISTANT_V2_BUILD_SPEC §4.1: ghim dòng 0 và dòng cuối, 18 dòng còn lại chọn bằng PRNG có seed
   suy từ (header JSON, totalRows, totalColumns, hash dòng đầu, hash dòng cuối). Ghi chú rõ
   "cùng bảng ⇒ cùng mẫu". Không dùng Math.random.
   (Hash có thể dùng hàm ĐƠN GIẢN tự viết, miễn tất định — không cần SHA-256 trong JS.)

5) Hàm gọi API: flowBindRoot, flowIngest(mode, source), flowUnderstand, flowLoadState, flowReset
   — tất cả đi qua api() sẵn có (đã gắn X-Local-Token, đã map lỗi).

6) DOM: thêm 4 card vào #tab-assistant theo ASSISTANT_V2_BUILD_SPEC §8 + danh sách id ở
   ASSISTANT_INTEGRATION_SPEC §5.2:
   02 Nguồn (flow-source-section, flow-root-input, flow-root-button, flow-add-csv,
     flow-add-xlsx, flow-add-folder, flow-add-workbook, flow-path-input, flow-source-status,
     flow-source-list, flow-navigator, flow-rename-list, flow-csv-options,
     flow-mode-badge, flow-sample-info, flow-ingest-sample, flow-ingest-full)
   03 Đề bài (flow-prompt-section, dùng lại #prompt + #prompt-count, flow-analyze-button,
     flow-disclosure checkbox, flow-questions, flow-answers)
   04 Cách hiểu (flow-understand-section, flow-understand-toggle, flow-understand-summary,
     flow-understand-body, flow-role-list, flow-relationship-list, flow-assumption-list)
   Mọi card bắt đầu class="card hidden"; mỗi card có data-state.
   Card 01 (Workbook) GIỮ NGUYÊN.

7) updateFlowButtons() gọi từ setBusy(); thêm setHidden("flow-*") vào
   invalidateSessionBoundState(). Không dùng innerHTML cho dữ liệu.

8) Feature gate: nếu bootstrap trả capabilities.assistantFlowV2 !== true thì khoá toàn bộ nút luồng
   và hiện thông báo "coordinator cũ — chạy lại server".

9) Nút "Nạp 20 dòng để hiểu" và "Đọc toàn bộ để tính" là HAI nút riêng, gọi flowIngest với
   mode "discover" và "compute".

TEST (tests/taskpane/taskpane_assistant_flow.js), tối thiểu:
  - isoDateLocal(new Date(2026,8,1)) === "2026-09-01", và với TZ=Asia/Saigon khác
    toISOString().slice(0,10) — đặt process.env.TZ nếu cần, hoặc dựng Date theo local.
  - flowReadOpenWorkbook gọi getDataBodyRange/getHeaderRowRange và KHÔNG gọi getRange.
  - header rỗng ⇒ chữ cái cột; totalColumns === header.length.
  - flowSampleOrdinals: cùng input ⇒ cùng output (chạy 2 lần so sánh); luôn chứa 0 và totalRows-1;
    không trùng; tất cả trong [0,totalRows).
  - assistantFlowV2 false ⇒ không có request nào được gửi khi bấm nút.
Dùng đúng pattern fake-host hiện có (vm.runInNewContext + globalThis.__x + fetch recorder +
console.log("… passed")).

ACCEPTANCE:
  - node --check pbip_assistant/excel_addin/taskpane.js sạch.
  - node tests/taskpane/taskpane_assistant_flow.js in "passed".
  - 12 script JS cũ vẫn xanh (py tools/run_checks.py fast dán nguyên văn dòng tổng kết).
  - Không tuyên bố đã thử trong Excel thật.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.6 — C1 · P2 Codex sinh 2 nhánh

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §4.3 (hợp đồng Codex plan draft, 7 bước validate,
    disclosure) và §0.1 (chốt A)
  - pbip_assistant/adapters/codex/typed.py   ← CodexTypedRunner, _codex_failure_code, cách gọi codex
  - pbip_assistant/adapters/codex/excel.py   ← MẪU validate response chặt (dòng 135-226). Bắt chước
  - pbip_assistant/powerquery/typed/validation.py:510-620  ← _validate_draft_shape, _normalize_steps
  - pbip_assistant/powerquery/typed/validation.py:34       ← build_source_catalog
  - pbip_assistant/coordinator/endpoints/assistant_plan.py ← stub B1 để lại

NHIỆM VỤ: thêm đường Codex sinh 2 kế hoạch (A/B) từ mẫu + câu hỏi + câu trả lời, và validate nghiêm.

FILE BẠN ĐƯỢC SỬA:
  TẠO:
  - pbip_assistant/adapters/codex/assistant_plan.py   (draft_branch_plans + validate response)
  - tests/unit/test_assistant_plan_draft.py
  SỬA:
  - pbip_assistant/coordinator/endpoints/assistant_plan.py   (hiện thực _post_assistant_plan_draft)
  - pbip_assistant/sources/assistant_session.py              (thêm stage "planning" + lưu 2 plan)
  - pbip_assistant/excel_addin/taskpane.js                   (chỉ card 05 skeleton: hiện 2 nhánh
                                                              dạng danh sách bước, CHƯA có số)
  - tests/taskpane/taskpane_assistant_flow.js                (thêm case cho card 05)
KHÔNG được sửa:
  - coordinator/server.py (B1 đã đăng ký route xong)
  - pbip_assistant/powerquery/typed/* (catalog đóng, chỉ đọc)
  - các hàm advice flow trong taskpane.js

PHẢI LÀM:

1) draft_branch_plans(prompt, snapshot, understand, answers, acknowledged, runner) -> dict
   - ack="acknowledged" phải là True, nếu không ⇒ InputError("AF_DISCLOSURE_REQUIRED").
   - Request gửi Codex theo đúng shape ASSISTANT_V2_BUILD_SPEC §4.3: goal, sources (chỉ schema
     + thống kê, KHÔNG gửi toàn bộ dữ liệu), sampleRows (20 dòng), sampleOrdinals, understand,
     answers, catalog (15 tên operation + 10 expression kind), limits.
   - Response mong đợi: summary, questions[], assumptions[], branches[2] với
     {id:"A"|"B", label, rationale, controlTotal{resultColumn,sourceColumn,aggregation}, plan}.
   - Validate response theo ĐÚNG 7 bước ở §4.3, dừng ở lỗi đầu tiên, dùng InputError với mã
     AF_PLAN_INVALID và path chỉ rõ bước/field sai.
   - Import _validate_draft_shape, _normalize_steps, build_source_catalog từ
     pbip_assistant.powerquery.typed.validation (tiền lệ: typed/store.py:77-88 cũng import private).
   - Chặn Codex "gài số": nếu một literal xuất hiện ở vị trí được dùng như measure tổng
     (vd addColumn tạo cột tổng mà không có columnRef nguồn) ⇒ AF_PLAN_INVALID.
   - Không tự sửa plan của Codex. Không retry tự động.

2) Endpoint /api/assistant/plan-draft: body {answers:[{questionId,answer}], acknowledged:true}.
   Trả {stage:"planning", summary, questions, assumptions, branches:[{id,label,rationale,
   controlTotal, steps:[{id,operationType,label}], planHash}]}.
   Lưu 2 plan vào store (KHÔNG trả plan thô đầy đủ nếu > 64KB — cắt theo giới hạn và ghi rõ).

3) UI card 05 (skeleton): hiện 2 nhánh, mỗi nhánh label + rationale + danh sách bước + badge
   "chưa tính số". Nút "Chọn nhánh" disabled ở sóng này.

4) Disclosure: checkbox #flow-disclosure với nội dung đúng ASSISTANT_V2_BUILD_SPEC §4.3.1.
   Nút gọi Codex chỉ bật khi đã tick.

TEST:
  - plan thiếu/thừa nhánh ⇒ AF_PLAN_INVALID
  - plan tham chiếu cột không tồn tại ⇒ AF_PLAN_INVALID
  - operation ngoài 15 ⇒ PQV2_OPERATION_UNSUPPORTED
  - literal gài làm tổng ⇒ AF_PLAN_INVALID
  - acknowledged không true ⇒ AF_DISCLOSURE_REQUIRED
  - request gửi Codex KHÔNG chứa toàn bộ dữ liệu (chỉ schema + 20 dòng) — assert trên request đã bắt

ACCEPTANCE:
  - py tools/run_checks.py fast xanh (dán dòng tổng kết).
  - Không có test nào cần Codex thật trong fast gate (dùng fake runner).

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.7 — D1 · P3b Reconcile + /branches

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §4.4 (ba bước: đọc full, chạy A/B, trả số) và §7
    (reconcile không recipe — 4 tầng R1–R4, và luật "không khai controlTotal thì phải ack")
  - pbip_assistant/powerquery/typed_local/  ← executor agent A3 vừa làm; execute_plan(plan, tables)
  - pbip_assistant/sources/assistant_reconcile.py ← đọc để biết phần nào tái dùng được
    (_BASIS, assert_approvable) và phần nào gắn FIN (_controls, _bridge) thì bỏ
  - pbip_assistant/coordinator/endpoints/assistant_exec.py ← stub B1

NHIỆM VỤ: chạy cả hai nhánh trên snapshot compute, đối soát, trả số cho UI.

FILE BẠN ĐƯỢC SỬA:
  TẠO:
  - pbip_assistant/sources/assistant_reconcile_v2.py
  - tests/unit/test_assistant_reconcile_v2.py
  SỬA:
  - pbip_assistant/coordinator/endpoints/assistant_exec.py  (_post_assistant_branches)
  - pbip_assistant/sources/assistant_session.py             (stage "branched", lưu result/preview)
  - pbip_assistant/excel_addin/taskpane.js                  (card 05 hiện số + radio chọn nhánh)
  - tests/taskpane/taskpane_assistant_flow.js               (case cho card 05 có số)
KHÔNG được sửa:
  - server.py, powerquery/typed/*, powerquery/typed_local/* (nếu thấy executor sai ⇒ báo BLOCKED,
    đừng tự sửa)

PHẢI LÀM:

1) reconcile_v2(preview_of_branch, plan, source_tables, result) -> dict với 4 tầng:
   R1 hình dạng: rowsOut == len(rows), colsOut == len(columns), không cột trùng tên, không dòng rỗng
   R2 control total: sum(result[controlTotal.resultColumn]) so sum(source[sourceColumn]) sau filter,
      |sai số| <= tolerance (Decimal). Không khai được ⇒ controlTotalApplicable = False
      (KHÔNG được coi là pass), kèm lý do.
   R3 fan-out: nếu plan có mergeTables, rowsAfter <= rowsBefore * khai báo; vượt ⇒ blocker
      AF_FANOUT_RISK.
   R4 A/B: A.total - B.total == delta (delta do engine tính, không lấy từ Codex).
   Trả {schemaVersion, planHash, rowsIn, rowsOut, colsIn, colsOut, controlTotalApplicable,
        controlTotalSource, controlTotalResult, controlTotalTolerance, controlTotalPassed,
        checks:[{id,passed,detail}], blockers[], warnings[], passed, reconcileHash, hashBasis}.
   Hash canonical theo pattern canonical_hash + hashBasis (đi theo tiền lệ assistant_reconcile.py).

2) Endpoint /api/assistant/branches:
   - Yêu cầu store đang ở stage "planning" và snapshot mode == "compute";
     nếu mode discover ⇒ InputError("AF_SAMPLE_ONLY") với thông điệp nói rõ phải "Đọc toàn bộ".
   - Chạy execute_plan cho A và B trên CÙNG snapshot; đo elapsedMs từng nhánh.
   - Cache theo (snapshotHash, planHash) để không tính lại vô ích; ghi rõ trong response.
   - Trả {stage:"branched", branches:[{id, label, resultDigest, columns, rows (tối đa 200 dòng,
     truncated, totalRows), reconciliation:{...}, elapsedMs}], delta, abIdentityPassed}.
   - Nhánh reconcile fail KHÔNG bị xoá — trả về với passed:false để UI khoá radio.

3) UI card 05: hiện bảng before/after của từng nhánh (renderTable sẵn có), banner reconcile
   (role=status), delta giữa A/B, radio chọn nhánh (disable nhánh fail), nút "Chốt nhánh" disabled
   ở sóng này.
   Khi controlTotalApplicable === false phải hiện rõ: "Chưa có đối soát tổng kiểm soát cho nhánh này."

TEST (tests/unit/test_assistant_reconcile_v2.py):
  - control total khớp sau filter ⇒ pass; lệch ⇒ AF_RECONCILE_FAILED
  - không khai controlTotal ⇒ applicable=False và passed=False (không được true)
  - fan-out vượt ⇒ AF_FANOUT_RISK
  - A.total - B.total == delta
  - cùng input ⇒ cùng reconcileHash; đổi 1 ô ⇒ hash đổi
  - execute trên snapshot discover ⇒ AF_SAMPLE_ONLY

ACCEPTANCE:
  - py tools/run_checks.py fast xanh (dán dòng tổng kết).
  - pwsh -NoProfile -File tools/assistant_flow_smoke.ps1 -StopAfter branches → nếu smoke script
    chưa có (P1.5 thuộc agent khác) thì ghi vào BLOCKERS, không tự sửa script.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.8 — E1 · P4 Freeze + duyệt + ghi

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §4.5, §4.6
  - docs/current/ASSISTANT_INTEGRATION_SPEC.md §4.3 (mục /approvals và /apply), và C2/C9/C10/C11
    ở §2 (approval process-affine; AF_WRITE_PARTIAL nhập nhằng; marker; tên sheet)
  - pbip_assistant/sources/assistant_decisions.py  (build_decisions, freeze_blocked, validate_decisions)
  - pbip_assistant/sources/assistant_spec.py       (build_spec, spec_fingerprint)
  - pbip_assistant/sources/assistant_approval.py   (issue_approval, consume_approval, approval_state)
  - pbip_assistant/sources/assistant_apply.py:137  (verify_values_only — GIỮ, hàm này generic)
  - pbip_assistant/excel_addin/taskpane.js:3581    (applyPQValuesToOpenWorkbook — ghi worksheet)
  - pbip_assistant/excel_addin/taskpane.js:761     (exportWorkbookBase64)

NHIỆM VỤ: chọn nhánh → freeze Spec → duyệt → ghi values-only vào workbook đang mở.

FILE BẠN ĐƯỢC SỬA:
  TẠO:
  - pbip_assistant/sources/assistant_freeze.py
  - tests/unit/test_assistant_freeze_v2.py
  SỬA:
  - pbip_assistant/coordinator/endpoints/assistant_freeze.py  (/freeze, /approvals, /apply)
  - pbip_assistant/sources/assistant_session.py               (stage frozen/approved/applied;
                                                               GIỮ STRONG REF tới _Approval)
  - pbip_assistant/excel_addin/taskpane.js                    (card 06/07 + flowApply)
  - tests/taskpane/taskpane_assistant_flow.js                 (case duyệt/ghi/partial)
KHÔNG được sửa:
  - server.py, powerquery/*, assistant_apply.py (chỉ import verify_values_only)

PHẢI LÀM:

1) assistant_freeze.py: build_frozen_spec(snapshot, understand, branch) → spec
   - Dùng lại build_decisions/build_spec nhưng: decisions chốt NHÁNH (thêm branchId), steps =
     plan của nhánh đã chọn (đã normalize), KHÔNG dùng compile_steps.
   - Freeze CHỈ khi: snapshot.mode == "compute" (nếu không ⇒ AF_SAMPLE_ONLY) VÀ nhánh đã chọn có
     reconciliation.passed == true (nếu không ⇒ AF_RECONCILE_FAILED) VÀ nếu
     controlTotalApplicable == false thì cần acknowledgement tường minh (nếu không ⇒ AF_MISSING_DATA).
   - spec.fingerprint bind snapshotHash + decisionsHash + planHash.

2) /approvals: assert_approvable tương đương (nhánh đã qua reconcile), rồi issue_approval.
   Store PHẢI giữ strong ref tới object _Approval (C2). Trả bản copy CHỈ để hiển thị.

3) /apply: body {workbookBase64, appliedAt}
   - Validate approval qua validate_approval; consume; nếu approvalConsumed=false ⇒ chưa ghi gì.
   - verify_values_only trên bytes; đối chiếu digest của result đã chốt.
   - Trả {result:{columns,rows,totalRows,truncated:false}, marker, labels, resultDigest,
     apply:{target:{sheet}, written:{rowCount,columnCount}, workbookSaved:false, approval:{consumed:true}}}
   - Lỗi: AF_WRITE_PARTIAL với approvalConsumed + written + retryable trong phần error (dùng
     _error(extra=...) của B1).
   - Tên sheet do SERVER quyết định (không cho client đặt); nếu sheet đã tồn tại ⇒ AF_WRITE_PARTIAL
     với approvalConsumed=false (chưa tiêu token).

4) UI card 06/07 + flowApply:
   - flow-approve-check + flow-approve-button (chỉ bật khi reconciled)
   - flowApply: exportWorkbookBase64 → /apply → tạo worksheet mới → ghi values + marker vào ô cuối
     → đọc lại → so resultDigest. Lệch ⇒ báo partial, KHÔNG hiện "Đã ghi".
   - Không gọi workbook.save(); không ghi sheet nguồn.
   - Khi AF_WRITE_PARTIAL + approvalConsumed:true ⇒ hiện cảnh báo partial/unknown, không cho retry.

TEST:
  - freeze khi snapshot discover ⇒ AF_SAMPLE_ONLY
  - freeze khi nhánh fail ⇒ AF_RECONCILE_FAILED
  - freeze khi controlTotalApplicable false và không ack ⇒ AF_MISSING_DATA
  - đổi 1 bước plan ⇒ spec.fingerprint đổi
  - approval dùng 2 lần ⇒ lần 2 AF_SPEC_STALE
  - apply khi sheet đích đã tồn tại ⇒ AF_WRITE_PARTIAL, approvalConsumed false
  - JS: AF_WRITE_PARTIAL + approvalConsumed:true ⇒ không hiện "Đã ghi", hiện cảnh báo, không retry

ACCEPTANCE:
  - py tools/run_checks.py fast xanh (dán dòng tổng kết).
  - Không tuyên bố đã ghi vào Excel thật (đó là runtime gate, người dùng chạy sau).

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.9 — E2 · P5a Custom XML helper

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §4.7 (namespace, CAS, read-back, giới hạn 32KB)
  - pbip_assistant/excel_addin/taskpane.js dòng 931-1000 và 1932-2110  ← pattern đọc/ghi Custom XML
    của Problem Chain (readProblemChainXml, persistProblemChainCandidate)
  - docs/current/PROBLEM_CHAIN_SPEC.md (nếu cần ngữ nghĩa CAS/HEAD)

NHIỆM VỤ: tách phần Custom XML thành helper dùng lại được cho Assistant Record, theo đúng pattern
Problem Chain nhưng NAMESPACE RIÊNG.

FILE BẠN ĐƯỢC TẠO/SỬA:
  TẠO:
  - pbip_assistant/excel_addin/assistant_custom_xml.js  (helper JS, export qua globalThis để test)
  - tests/taskpane/taskpane_assistant_custom_xml.js
  SỬA:
  - tests/taskpane/test_taskpane_js.py  (thêm đúng 1 method chạy file test mới)
KHÔNG được sửa:
  - taskpane.js, taskpane.html (agent F1 sẽ nối dây)
  - bất kỳ file python nào
  - namespace của Problem Chain

HỢP ĐỒNG HELPER:
  ASSISTANT_RECORD_NAMESPACE = "urn:local-data-copilot:assistant-record:v1"
  readAssistantRecord()            -> {id, hash, snapshot, spec, branch, createdAt, labels} | null
  writeAssistantRecord(node, expectedHash) -> {written:true, hash} | throw
  clearAssistantRecord()           -> {cleared:true}
  verifyAssistantRecordHash(node)  -> true|false

LUẬT:
  - Ghi không được gọi workbook.save().
  - CAS: expectedHash phải khớp hash đọc được; khác ⇒ throw lỗi mã PQPC_HISTORY_CONFLICT.
  - Sau khi ghi, đọc lại và so hash; lệch ⇒ throw AF_WRITE_PARTIAL.
  - Chỉ lưu hash + metadata; TUYỆT ĐỐI không lưu mảng cell, không lưu đường dẫn tuyệt đối.
    Helper phải tự kiểm và từ chối nếu node chứa chuỗi khớp /^[A-Za-z]:\\/ hoặc mảng lồng.
  - Giới hạn 32 KB; vượt ⇒ throw, không cắt.
  - Không dùng chung namespace với urn:local-data-copilot:pq-problem-chain:v1.

TEST (fake host Custom XML giống tests/taskpane/taskpane_problem_chain.js đang dùng):
  - ghi → đọc lại → hash khớp
  - ghi 2 lần với expectedHash cũ ⇒ conflict
  - node chứa đường dẫn tuyệt đối ⇒ bị từ chối
  - node > 32KB ⇒ bị từ chối
  - namespace khác với Problem Chain

ACCEPTANCE:
  - node tests/taskpane/taskpane_assistant_custom_xml.js in "passed".
  - py tools/run_checks.py fast xanh (dán dòng tổng kết).

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.10 — F1 · P5b Record + persist

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md §4.7
  - pbip_assistant/sources/assistant_record.py   (build_record, record_hash, detect_stale, mark_stale)
  - pbip_assistant/sources/assistant_delta.py    (compute_delta — bỏ phần _FIN)
  - pbip_assistant/excel_addin/assistant_custom_xml.js  (agent E2 vừa làm)
  - pbip_assistant/coordinator/endpoints/assistant_record.py (stub B1)

NHIỆM VỤ: dựng Decision Record cho v2 và lưu/đọc nó qua Custom XML.

FILE BẠN ĐƯỢC SỬA:
  TẠO:
  - pbip_assistant/sources/assistant_record_v2.py
  - tests/unit/test_assistant_record_v2.py
  SỬA:
  - pbip_assistant/coordinator/endpoints/assistant_record.py  (_post_assistant_record)
  - pbip_assistant/sources/assistant_session.py               (stage "recorded", recordHash)
  - pbip_assistant/excel_addin/taskpane.js                    (card 08 + nối helper Custom XML)
  - tests/taskpane/taskpane_assistant_flow.js                 (case record persist + stale)
KHÔNG được sửa:
  - server.py, powerquery/*, taskpane_* helper của E2 (chỉ gọi)

PHẢI LÀM:
1) assistant_record_v2.py: build_v2_record(snapshot, plan, branch, spec, reconciliation, delta,
   created_at, source_evidence=None) -> record
   - Dùng lại build_record nếu shape khớp; nếu buộc phải viết mới thì giữ NGUYÊN tên field và
     hashBasis để không phá hash chain.
   - delta: compute_delta nhưng bỏ nhánh _FIN; chỉ giữ rowsIn/rowsOut/nulls/dupes/changedColumns
     tính từ plan.
   - Record phải ghi: executor {version, parityChecked, knownDifferences} theo
     ASSISTANT_V2_BUILD_SPEC §6.5 tầng 4.
   - Không lưu raw cell, không đường dẫn tuyệt đối (record engine đã từ chối; giữ nguyên).

2) Endpoint /api/assistant/record: body {} (dùng state đã có). Trả {stage:"recorded",
   recordId, recordHash, node, staleCheck}. Ghi QUA Custom XML bằng Office.js ở phía client —
   server chỉ trả node + hash, KHÔNG tự ghi file.

3) UI card 08: hiện delta, nhãn, record id/hash, nút "Lưu vào workbook" (gọi
   writeAssistantRecord với expectedHash), nút "Tải Decision Record" (Blob JSON), banner stale
   khi mở lại pane và nguồn đã đổi.
   Hiện dòng "Workbook đã lưu: Chưa" vì không gọi save().

TEST:
  - record round-trip: ghi node → đọc lại → recordHash khớp
  - đổi 1 byte CSV nguồn ⇒ mở lại thấy stale
  - record không chứa mảng cell / đường dẫn tuyệt đối
  - executor.knownDifferences có mặt trong record

ACCEPTANCE:
  - py tools/run_checks.py fast xanh (dán dòng tổng kết).
  - Không tuyên bố đã thử trong Excel thật.

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

### §2.11 — G1 · P6 UI hoàn chỉnh + tài liệu

```text
Repo: C:\Users\COLAIG\Downloads\power_bi

ĐỌC TRƯỚC:
  - docs/current/ASSISTANT_V2_BUILD_SPEC.md toàn bộ (đặc biệt §8, §9 P6, §11)
  - docs/current/ASSISTANT_INTEGRATION_SPEC.md §5.1 (danh sách id phải BỎ), §7.3.1
    (bảng ánh xạ 4 case JS bị đỏ), §12 (smoke script)
  - trạng thái hiện tại của taskpane.js / taskpane.html sau các sóng trước

NHIỆM VỤ: (1) dọn advice UI đã bị thay, (2) hoàn thiện 8 card, (3) đồng bộ tài liệu + test registry.

FILE BẠN ĐƯỢC SỬA:
  - pbip_assistant/excel_addin/taskpane.html
  - pbip_assistant/excel_addin/taskpane.js
  - pbip_assistant/excel_addin/taskpane.css
  - tests/taskpane/*.js  (các file test cần sửa/xoá theo bảng ánh xạ)
  - tests/taskpane/test_taskpane_js.py
  - tests/required_cases.json
  - docs/current/ASSISTANT_TRACEABILITY.md
  - docs/current/CURRENT_STATUS.md
  - docs/current/TASKPANE_UI.md
  - tools/excel_addin/README.md
  - tools/assistant_flow_smoke.ps1   (nếu chưa có thì TẠO theo ASSISTANT_INTEGRATION_SPEC §12)
KHÔNG được sửa:
  - server.py, endpoint, engine python (đã xong ở các sóng trước)

PHẢI LÀM:

1) Dọn advice UI theo bảng "Giữ / bỏ / thêm" ở ASSISTANT_INTEGRATION_SPEC §5.1:
   BỎ các id: plan-section, plan-title, plan-status, plan-summary, analysis-notes, warning-list,
   code-section, operation-list, code-list, preview-section, preview-title, preview-label,
   before-table, approval-section, approval-title, approval-check, apply-button, apply-progress,
   result-section, result-title, runtime-badge, copy-path, excel-version, reconcile-status,
   runtime-table, formula-list-separator, codex-status, analyze-button.
   BỎ các hàm: analyze(), applyPlan(), renderPlan(), renderOperations(), renderCodeBlocks(),
   renderCodeCard(), renderRuntime(), updateApplyState(), invalidatePlan().
   GIỮ: card 01 Workbook, #prompt/#prompt-count, #error-panel #error-code #error-detail.
   Chuyển state.plan và state.codexAvailable ra khỏi state; sửa setBusy() và bootstrap().

2) Áp bảng ánh xạ 4 case JS bị đỏ (ASSISTANT_INTEGRATION_SPEC §7.3.1):
   - xoá tests/taskpane/taskpane_live_analyze.js, taskpane_shortcut.js, taskpane_code_blocks.js
     (hành vi đã được F-JS-11/12/13 trong taskpane_assistant_flow.js giữ)
   - xoá 3 dòng assertion về applyPlan trong tests/taskpane/taskpane_pq.js (F-JS-14 giữ)
   - cập nhật tests/required_cases.json đúng theo bảng: xoá 3 ID, thêm ID mới
   - chạy: py tools/run_checks.py fast --list, đối chiếu số case, ghi con số thực tế vào báo cáo

3) Hoàn thiện 8 card theo ASSISTANT_V2_BUILD_SPEC §8 + máy trạng thái
   (ASSISTANT_INTEGRATION_SPEC §5.5) + quy tắc copy §5.6 (cấm mọi câu nói AI đã phân tích số).
   Mỗi card có data-state; chip status có icon + chữ + màu.

4) tools/assistant_flow_smoke.ps1: nếu chưa có, tạo đúng đặc tả ASSISTANT_INTEGRATION_SPEC §12.
   Nếu đã có thì cập nhật cho khớp route v2 (/plan-draft, /branches, /freeze, /record).

5) Tài liệu:
   - ASSISTANT_TRACEABILITY.md: cập nhật trạng thái các dòng partial theo
     ASSISTANT_INTEGRATION_SPEC §10, thêm ghi chú "engine synthetic + HTTP fake host, không phải
     Office live".
   - CURRENT_STATUS.md: thêm dòng cho luồng v2 + gate thực tế + "chưa có live evidence".
   - TASKPANE_UI.md: viết lại theo 8 card; bỏ yêu cầu về khối code sao chép được.
   - tools/excel_addin/README.md (finding 7): bỏ hướng dẫn "Analyze → SIMULATED → EXCEL VERIFIED";
     tách rõ 3 đường: Codex advice / Typed-Problem Chain / luồng Trợ lý v2.

ACCEPTANCE:
  - node --check pbip_assistant/excel_addin/taskpane.js sạch.
  - node tests/taskpane/taskpane_assistant_flow.js in "passed".
  - py tools/run_checks.py fast xanh, dán nguyên văn dòng tổng kết VÀ số case thực tế.
  - grep xác nhận không còn id/function advice trong taskpane.html/js (đưa lệnh grep vào báo cáo).

BÁO CÁO theo đúng định dạng ở MASTER PROMPT (§1). Không dùng PowerShell để sửa file.
```

---

## §3. Prompt sửa khi agent báo BLOCKED

```text
Một subagent báo BLOCKED. Nhiệm vụ của bạn là gỡ, KHÔNG phải làm cho xanh bằng mọi giá.

Bước 1 — Xác định loại blocker, chọn đúng cách xử:
  (a) Thiếu file/hàm mà agent khác chưa làm
      ⇒ giao việc đó cho agent sở hữu đúng file, hoặc hoãn tính năng lại sau nó.
      Không cho agent vượt quyền sửa file người khác.
  (b) Spec mâu thuẫn hoặc thiếu
      ⇒ DỪNG toàn bộ sóng. Hỏi người dùng đúng một câu, kèm 2 phương án và hệ quả mỗi phương án.
      Không tự chọn thay người dùng.
  (c) Test cũ đỏ vì thay đổi là CỐ Ý
      ⇒ Kiểm xem có case thay thế giữ hành vi chưa (AGENTS.md). Chưa có ⇒ viết case thay thế
        TRƯỚC, rồi mới đổi. Có rồi ⇒ ghi rõ test nào thay test nào vào báo cáo.
  (d) Không đạt được acceptance vì môi trường (thiếu Excel/Codex/quyền)
      ⇒ đánh dấu "NOT RUN — <lý do>" trong báo cáo. Không được coi là pass, không được tự
        hạ assertion.

Bước 2 — Báo lại người dùng:
  - 1 dòng mô tả blocker thực sự là gì (không phải triệu chứng)
  - phương án đề xuất + hệ quả
  - việc gì vẫn đang bị chặn phía sau nó (danh sách sóng)
```

---

## §4. Những cạm bẫy đã biết (truyền cho mọi agent)

| Cạm bẫy | Cách tránh |
|---|---|
| **PowerShell 5.1 đọc UTF-8 thành ANSI** | Không dùng `Get-Content`/`Set-Content` để sửa `.md/.py/.js`. Chỉ dùng công cụ đọc/ghi file của agent. Một lần round-trip là hỏng toàn bộ tiếng Việt |
| Sửa `server.py` ở nhiều sóng | Chỉ B1 được sửa; B1 đăng ký **cả 11 route** và tạo stub để import không chết |
| Hai agent cùng sửa `taskpane.js` | Mỗi sóng chỉ định một chủ; nếu cần thêm, xếp sóng mới |
| `readWorkbook()` bị sửa bởi 2 agent | A2 sửa hàm này; các sóng sau viết hàm MỚI riêng (`flowReadOpenWorkbook`) |
| `required_cases.json` bị sửa rải rác | Chỉ G1 sửa; các sóng khác khai ID trong báo cáo |
| Catalog Typed bị "tiện tay" mở rộng | Catalog là ĐÓNG. Thiếu thao tác ⇒ báo, không tự thêm |
| Codex trả về con số | Từ chối ngay. Codex chỉ trả kế hoạch |
| Dùng payload mẫu để tính số | Chặn bằng `AF_SAMPLE_ONLY`; mẫu chỉ để hiểu |
| Approval bị copy qua JSON | Store phải giữ strong ref tới object `_Approval` |
| `AF_WRITE_PARTIAL` hiểu sai | Phân biệt bằng `approval_state(...)["consumed"]`: false ⇒ chưa ghi; true ⇒ không retry |
| Tuyên bố đã test live | Fake host ≠ Office.js thật. Ghi "chưa chạy" |

---

## §5. Điều người dùng phải tự làm sau khi Codex xong

| Việc | Lệnh / cách |
|---|---|
| Xác nhận gate | `py tools/run_checks.py fast` — đọc dòng tổng kết |
| Smoke backend không cần Excel | Bật coordinator rồi `pwsh -NoProfile -File tools/assistant_flow_smoke.ps1` |
| Gate runtime (Excel thật) | `py tools/run_checks.py runtime` |
| Codex thật | `PQPC_LIVE_CODEX=1` rồi `py tools/run_checks.py codex` |
| Test tay trong Excel | Runbook ở `docs/current/ASSISTANT_INTEGRATION_SPEC.md` §7.4 |
| Parity executor ↔ Power Query | `py -m unittest tests.runtime.test_typed_local_parity -v` (cần Excel; scaffold trong unit không cấp bằng chứng runtime) |

**Không agent nào được tự ghi vào workbook người dùng.** Mọi test dùng fixture synthetic.
