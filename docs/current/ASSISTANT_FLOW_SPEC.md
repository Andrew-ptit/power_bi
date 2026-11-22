# ASSISTANT_FLOW_SPEC — Luồng Trợ lý AI-first, Exception-based, No-fake

| Trường | Giá trị |
|---|---|
| Phiên bản | 1.1 — 26/10/2026 |
| Status | Draft chốt luồng + UX/UI; chờ implement |
| Changelog | 1.1: soát ngữ nghĩa; đổi `AF-BR`→`AF-BF` (tránh trùng Business Rule); sửa "Engine tính"; thêm UX/UI (mục 16) + Glossary (mục 17) |
| Phạm vi | Trợ lý (tab Assistant) + Thực thi (tab PQ_Code-M) của Excel add-in |
| Nguồn | `SPEC.md`, `PQ_CODE_M_SPEC.md`, `TYPED_STEP_DIAGNOSTICS_SPEC.md`, `UI_RAW_DATA.md`, `CURRENT_STATUS.md`, `TASKPANE_UI.md` |
| Ngoài phạm vi | LY (tạm bỏ), PBIP patch, DAX/TMDL generation, publish Power BI Service |

> **Một câu:** Người nêu bài toán → **AI hiểu + dựng mô hình** → **engine tính + đề xuất có bằng chứng** → người **chỉ chốt ngoại lệ** → engine **thi hành + đối soát** → ghi kết quả **có nhãn độ tin cậy**. Không con số nào do AI tự nghĩ ra.

---

## 1. Mục tiêu & định vị

1. **Không cấu hình mặc định.** Người dùng chỉ nêu bài toán + thêm nguồn; AI tự nhận diện vai, grain, khoá, quan hệ, định nghĩa cơ bản.
2. **Chính xác & ổn định là điều kiện tiên quyết.** Mọi số do engine tất định tính; mọi artifact có fingerprint; cùng input → cùng output.
3. **Không giả kết quả.** Mọi giả định nghiệp vụ có nguồn + nhãn; bất định + hậu quả cao thì đưa 2 kịch bản hoặc dừng, không chọn hộ.
4. **Khác chat:** add-in có dữ liệu thật + engine tất định + lịch sử revision. Giá trị là "chứng minh & nhớ", không phải "sinh code".

## 2. Phạm vi

**Trong phạm vi:**
- Get Data: Workbook đang mở, Excel file, CSV, Thư mục.
- AI hiểu cấu trúc + nghĩa cơ bản; Decision Brief; Exception-based confirmation.
- Thực thi Typed Steps (Recipe/Lookup/Join/Group/Calc), preview workbook tạm, reconcile, ghi values-only, delta + Decision Record.
- Generic mode khi không có domain pack.

**Ngoài phạm vi:**
- LY / Last Year (tạm bỏ khỏi MVP).
- PBIP patching, DAX/TMDL generation, publish Power BI Service.
- Connector DB/Web (để sau).
- Tự Save workbook, rollback/Ctrl+Z.

## 3. Nguyên tắc bất biến (3 trụ)

| ID | Trụ | Cam kết | Cách bảo đảm |
|---|---|---|---|
| AF-PR-001 | Chính xác | Mọi con số có công thức + nguồn | **Engine tính**; AI chỉ diễn giải; có `formula_id` truy vết |
| AF-PR-002 | Ổn định | Cùng input → cùng output | Deterministic ops, seed cố định, bounded input, fingerprint mọi artifact |
| AF-PR-003 | Không giả | Không bịa kết quả/định nghĩa | Provenance bắt buộc; Assumption Ledger; nhãn `inferred/assumed/unverified`; A/B hoặc dừng khi rủi ro cao |

## 4. Kiến trúc 5 lớp — ai sở hữu

| Lớp | Sở hữu | Làm gì | Không được làm |
|---|---|---|---|
| Ingest | Engine | Đọc nguồn, schema, mẫu, hash | Không diễn giải nghiệp vụ |
| Understand | Engine (cấu trúc) + AI (nghĩa) | Dò vai/khoá/quan hệ; diễn giải cột + đề xuất định nghĩa | Không gắn `Verified` cho suy luận |
| Decide | AI đề xuất + **Người chốt** | Decision Brief, giả định, ngoại lệ | Không tự chốt policy |
| Execute | Engine | Steps → preview → reconcile → ghi | Không dùng raw M tự do |
| Verify | Engine | Delta, control total, Record | Không suy diễn "đúng nghiệp vụ" |

## 5. Luồng 8 pha + state machine

| Pha | Ai | Đầu vào | Đầu ra | Cổng |
|---|---|---|---|---|
| 0 · Get Data | Người + Engine | file/thư mục/workbook | bảng + schema + mẫu + hash | Đọc được, không lỗi |
| 1 · Hiểu | AI + Engine | bảng | "AI đã hiểu": vai, grain, khoá, quan hệ, nghĩa cột | Cấu trúc qua check số học |
| 2 · Khung | AI | bài toán người dùng | Output contract (grain/measure/filter/kỳ) | Đủ để phân tách |
| 3 · Brief | Engine (số) + AI (kể) | model + contract | Decision Brief + insight cases + ledger | Người đọc được |
| 4 · Chốt | **Người** | Brief | Execution Spec đóng băng | Snapshot + quyết định khớp |
| 5 · Thực thi | Engine | Spec | step list → preview (workbook tạm) → reconcile | Reconcile đạt |
| 6 · Ghi | Người duyệt | preview | sheet kết quả values-only | Duyệt tường minh |
| 7 · Verify | Engine | kết quả | Delta + Decision Record | Đóng |

**State machine:**
```
new → ingested → understood → framed → briefed → frozen
    → compiled → previewed → reconciled → approved → applied → recorded
```
Mỗi mũi tên = một cổng. Sai cổng thì **không đi tiếp** (vd chưa `reconciled` thì không `approved`).

---

## 6. Đặc tả theo WL (Workflow Layer)

### WL1 · Get Data (Pha 0)

**Mục tiêu:** nạp nhiều nguồn thành tập bảng có schema + mẫu + hash, chưa diễn giải.

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-GD-001 | Connector: Workbook đang mở, Excel file, CSV, Thư mục | Mỗi loại thêm được ≥1 nguồn |
| AF-GD-002 | Navigator: chọn sheet/table/range (Excel) hoặc file (thư mục) | Bảng bỏ chọn không được nạp |
| AF-GD-003 | CSV: hiện encoding/delimiter/header; mơ hồ thì yêu cầu chọn | Đổi option → profile đổi, không tạo file rác |
| AF-GD-004 | Thư mục: append nhiều file thành một bảng, theo thứ tự tên | 3 file tháng → 1 bảng, số dòng = tổng |
| AF-GD-005 | Mỗi bảng có `fingerprint` (schema + header + sample hash) | Cùng file → cùng fingerprint |
| AF-GD-006 | Snapshot gồm danh sách bảng + hash + thời điểm | Snapshot tái lập được |
| AF-GD-007 | File loại khác / path traversal / file > giới hạn → chặn | Không tạo temp, có mã lỗi |

**Business rules:**
- AF-GD-BR-001: Không ghi/không sửa nguồn.
- AF-GD-BR-002: Tên bảng trùng → yêu cầu đổi tên (không tự đè).
- AF-GD-BR-003: Giới hạn 64 MiB/file, 128 MiB/phiên, preview 20 dòng.

### WL2 · Hiểu (Pha 1) — AI-first

**Mục tiêu:** tự dựng mô hình hiểu (vai, grain, khoá, quan hệ, nghĩa cột) + ledger giả định.

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-UN-001 | Dò vai cấu trúc fact/dim/bridge/lookup bằng thống kê (số dòng, distinct ratio, null) | Đúng trên TP-FIN và TP-SALES |
| AF-UN-002 | Dò khoá ứng viên (PK ≈ 100% distinct, no null; FK có overlap với PK khác) | Báo đúng cặp khoá + overlap % |
| AF-UN-003 | Dựng đồ thị quan hệ, chấm điểm (tên+kiểu+overlap+orphan+fan-out) | Mỗi dây có score + evidence |
| AF-UN-004 | Fan-out: mô phỏng nối; dây gây nhân dòng → `needs_confirm` + `fanOutRisk=high` | Nối GL×Budget sai grain bị chặn |
| AF-UN-005 | Diễn giải nghĩa cột (date/amount/key/text/percent/currency) + đề xuất định nghĩa | Mỗi đề xuất có evidence |
| AF-UN-006 | Assumption Ledger: statement, source(pack/data/history/llm/user), confidence, risk | Mọi giả định nghiệp vụ có nguồn |
| AF-UN-007 | Không có pack → generic mode, ghi rõ "kém chính xác hơn" | Vẫn dựng được cấu trúc |
| AF-UN-008 | Không suy ra được → `unknown`, không đoán | Không có giá trị bịa |
| AF-UN-009 | Determinism: cùng snapshot → cùng mô hình hiểu (cùng hash) | Chạy 2 lần khớp |

**Business rules:**
- AF-UN-BR-001: Cấu trúc tự áp chỉ khi qua check số học; ngược lại `needs_confirm`.
- AF-UN-BR-002: Nghĩa nghiệp vụ không bao giờ `verified` do AI tự gán.

### WL3 · Khung + Brief (Pha 2–3)

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-BF-001 | Chuyển bài toán người dùng → Output contract (grain/measure/filter/kỳ) | Contract hiển thị, sửa được |
| AF-BF-002 | Findings: mỗi phát hiện có `value` (engine tính) + `evidence` | Không có số do AI sinh |
| AF-BF-003 | Mổ xẻ 1 tầng thành ≥3 sub-problems (TP-FIN ≥5), mỗi cái A/B + hệ quả | Mỗi SP có options + consequence |
| AF-BF-004 | Insight cases đủ cả hai loại: giả thuyết/câu hỏi + cảnh cắt dữ liệu | Danh sách có cả hai |
| AF-BF-005 | Status mỗi SP ∈ {verified, inferred, assumed, unknown, missing_data, conflict} | Mỗi SP có đúng 1 status |
| AF-BF-006 | Thiếu dữ liệu → `missing_data` + tuyên bố out-of-scope, không bịa | VD LY bỏ → hiện "chưa có nguồn" |
| AF-BF-007 | Bất định + hậu quả cao → 2 kịch bản A/B + chênh lệch | Có số chênh lệch (engine tính) |
| AF-BF-008 | Brief hash ổn định theo snapshot + bài toán | Chạy 2 lần khớp |

**Business rules:**
- AF-BF-BR-001: Mọi con số trong Brief phải trích từ engine + `formula_id`; AI không được tự viết số.

### WL4 · Chốt + Compile (Pha 4–5a)

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-FZ-001 | Người chốt ngoại lệ (assumed/unknown/conflict) → Execution Spec | Spec có `snapshotHash` + `decisionsHash` |
| AF-FZ-002 | Mỗi quyết định map 1:1 thành step (Recipe/Lookup/Join/Group/Calc) | Số step = số quyết định thực thi + step dữ liệu |
| AF-FZ-003 | Steps xếp theo dependency, khai báo input/output | Không có step mồ côi |
| AF-FZ-004 | Đổi quyết định sau freeze → invalidate Spec cũ | Spec cũ không dùng được |
| AF-FZ-005 | Compile idempotent: cùng Spec → cùng steps (hash) | Chạy 2 lần khớp |
| AF-FZ-006 | Spec còn assumption chưa chốt → đánh dấu `unverified` | Nhãn hiện ở kết quả |

### WL5 · Preview + Reconcile (Pha 5b)

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-EX-001 | Preview trên workbook tạm; source không đổi | Source byte-identical |
| AF-EX-002 | Preview values-only, sheet có marker | Không formula/query/connection |
| AF-EX-003 | **Reconcile (a)**: row/col count trước–sau ghi lại | Delta có số |
| AF-EX-004 | **Reconcile (b)**: control total kết quả = tổng nguồn | Khớp trong sai số cho phép |
| AF-EX-005 | **Reconcile (c)**: bridge identity `Op + FX = Total` (nếu có tính FX) | Đúng đại số |
| AF-EX-006 | Reconcile fail → block approve, quay lại Pha 1/3 | Nút duyệt bị khoá |
| AF-EX-007 | Determinism: cùng Spec → cùng preview hash | Chạy 2 lần khớp |

### WL6 · Duyệt + Ghi (Pha 6)

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-AP-001 | Duyệt tường minh gắn Spec/preview hash | Duyệt cũ mất hiệu lực khi đổi |
| AF-AP-002 | Ghi sheet kết quả (VD `PnL_Result` cho TP-FIN) values-only vào workbook đang mở | Đúng giá trị preview |
| AF-AP-003 | Không ghi sheet nguồn, không tự Save | Source không đổi |
| AF-AP-004 | Approval dùng một lần | Duyệt lại phải preview lại |
| AF-AP-005 | Kết quả có marker + nhãn provenance | Nhãn hiển thị |

### WL7 · Verify + Record (Pha 7)

| ID | Yêu cầu | Điều kiện đạt |
|---|---|---|
| AF-VF-001 | Delta sheet: rows in/out, null/dupe trước–sau, cột thay đổi | Có số engine tính |
| AF-VF-002 | Decision Record: snapshot, brief, decisions, assumptions, steps, reconcile, labels | Đủ trường, tái lập được |
| AF-VF-003 | Không gắn `Verified` cho phần chưa có bằng chứng runtime/nghiệp vụ | Chỉ nhãn `unverified`/`assumed` |
| AF-VF-004 | Record hash khớp; audit mở lại được | Hash kiểm chứng |
| AF-VF-005 | Nguồn đổi → Record/ Spec đánh dấu stale | Không dùng kết quả cũ |

---

## 7. Data model / Schema

```
Source      { id, name, type: workbook|xlsx|csv|folder, origin, hash, addedAt }
Table       { id, sourceId, name, locator(sheet|range|file), rowCount, columnCount,
              headerHash, sampleHash, fingerprint, columns[] }
Column      { name, type, nullRate, distinctCount, distinctRatio, sample[],
              role: date|amount|key|text|percent|currency }
Role        { structural: fact|dim|bridge|lookup, domainLabel?, confidence }
Relationship{ id, fromTable, toTable, fromColumns[], toColumns[],
              cardinality: 1:1|1:N|N:1|N:N, score, evidence{name,type,overlap,orphan},
              status: auto|needs_confirm|confirmed|rejected, fanOutRisk: none|low|high }
SubProblem  { id, question, evidence[], options[{id,label,consequence}],
              status, provenance, proposed, chosen }
Assumption  { id, statement, source: pack|data|history|llm|user, confidence, risk }
ExecutionSpec{ id, snapshotHash, decisionsHash, steps[], fingerprint, createdAt }
Step        { id, kind: recipe|lookup|join|group|calc|filter|sort|output,
              inputs[], params, output, dependsOn[] }
Reconciliation{ rowsIn, rowsOut, colsIn, colsOut, controlTotalSource,
              controlTotalResult, bridge{op,fx,total}, passed }
DecisionRecord{ id, snapshot, brief, decisions[], assumptions[], steps[],
              reconciliation[], labels[], hash, createdAt }
```

## 8. Enum & nhãn

- **Status:** `verified · inferred · assumed · unknown · missing_data · conflict`.
- **Provenance:** `pack · data · history · llm · user`.
- **Nhãn kết quả:** `unverified`, `assumed`, `out_of_scope`, `stale`.
- **`Verified` chỉ dùng khi** có bằng chứng runtime/nghiệp vụ; **không bao giờ** cho suy luận AI.

## 9. 7 luật chống "giả kết quả"

1. **AI không sinh số** — mọi số lấy từ engine + `formula_id`.
2. **Không `Verified` cho suy luận/lời AI.**
3. **Assumption Ledger bắt buộc.**
4. **Nhãn provenance hiển thị** — không ẩn `assumed/unknown/unverified`.
5. **Bất định + hậu quả cao → 2 kịch bản A/B hoặc dừng**, không chọn hộ.
6. **Reconciliation là cổng cứng.**
7. **Fingerprint/snapshot** — nguồn đổi → invalidate.

## 10. Stability checklist
- Thứ tự xử lý tất định; seed cố định khi lấy mẫu.
- Compile idempotent; preview idempotent.
- Bounded: mẫu 20 dòng, cap dòng/cột/byte.
- Error taxonomy **blocker vs warning** (vd thiếu `average rate` = blocker P&L; thiếu `closing` = warning).
- Không tự Save; values-only; approval dùng một lần.

## 11. Error taxonomy & loop-back

| Mã | Loại | Hành vi |
|---|---|---|
| `AF_INGEST_FAILED` | blocker | Dừng Pha 0, không có snapshot |
| `AF_SOURCE_LOST` | blocker | Dừng, yêu cầu nạp lại |
| `AF_FANOUT_RISK` | blocker | Chặn nối, yêu cầu xác nhận/bridge |
| `AF_MISSING_DATA` | warning | `missing_data`, out-of-scope, không bịa |
| `AF_RECONCILE_FAILED` | blocker | Khoá duyệt, quay Pha 1/3 |
| `AF_SPEC_STALE` | blocker | Invalidate, chốt lại |
| `AF_WRITE_PARTIAL` | blocker | Báo partial, không retry tự động |

## 12. Bài toán thực tiễn dùng để test

### TP-FIN · Báo cáo P&L Actual vs Budget (finance)
- **Nguồn:** `GL_Actuals_2026-09` (GL), `Budget_2026` (Budget), `MasterData` (CoA/CostCenter/Entity), `FX_Rates_2026` (FX). *Bỏ LY.*
- **Đề bài:** "Doanh thu thuần & lợi nhuận gộp T9 giảm do giá/chủng loại hay tỷ giá? Làm P&L theo cost center, quy VND, tách FX."
- **Bẫy fixture:** sign lẫn; dòng trùng; 3 tài khoản chưa map; 7 mã CC lạc; thiếu 1 `average rate`.
- **Kỳ vọng:** Brief ≥5 SP có A/B; reconcile `Op+FX=Total`; control total = tổng GL; kết quả có nhãn.

### TP-SALES · Báo cáo doanh số theo khu vực (non-finance)
- **Nguồn:** `Orders`, `OrderItems`, `Customers`, `Products`, `Territory`.
- **Đề bài:** "Doanh thu theo khu vực quý 3 giảm vì đơn huỷ hay thiếu khách?"
- **Mục đích:** chứng minh engine generic chạy không cần finance pack; structural detection + relationship vẫn đúng.

### TP-UNKNOWN · Người dùng không biết nghiệp vụ
- Dùng TP-FIN nhưng user bấm "tôi không chắc" cho 3 policy.
- **Kỳ vọng:** 2 kịch bản A/B + Assumption Ledger + checklist câu hỏi; không ép chọn; kết quả `unverified`.

## 13. Kế hoạch test tăng dần (bắt buộc)

**Nguyên tắc:** hoàn thiện **WL_k** thì chạy toàn bộ test **WL1..WL_k** (cộng dồn), đến khi hết WL7 thì chạy thêm E2E.

| Sau khi xong | Bộ test chạy | Điều kiện đạt |
|---|---|---|
| WL1 | T-WL1-* | Tất cả pass |
| WL2 | T-WL1-* + T-WL2-* | Tất cả pass, không hồi quy WL1 |
| WL3 | … + T-WL3-* | Tất cả pass |
| WL4 | … + T-WL4-* | Tất cả pass |
| WL5 | … + T-WL5-* | Tất cả pass |
| WL6 | … + T-WL6-* | Tất cả pass |
| WL7 | … + T-WL7-* + T-E2E-* | Tất cả pass |

### WL1 — Get Data
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL1-01 | Nạp nhiều nguồn | Thêm workbook + 2 Excel + 1 CSV + 1 thư mục | Đủ bảng, có schema/mẫu/hash |
| T-WL1-02 | CSV mơ hồ | CSV delimiter lẫn | Warning + chọn lại → profile đổi |
| T-WL1-03 | Thư mục append | 3 file tháng | 1 bảng, dòng = tổng |
| T-WL1-04 | Fingerprint ổn định | Nạp 2 lần | Cùng fingerprint |
| T-WL1-05 | Chặn file lạ | File `.exe`/path traversal | Blocker, không temp |
| T-WL1-06 | Trùng tên | 2 bảng cùng tên | Yêu cầu đổi tên |
| T-WL1-07 | Snapshot tái lập | Tạo 2 snapshot | Hash khớp |

### WL2 — Hiểu
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL2-01 | Vai cấu trúc | TP-FIN | Fact=GL, dim=CoA/CC/Entity |
| T-WL2-02 | Khoá + quan hệ | TP-FIN | Cặp khoá + overlap%, score |
| T-WL2-03 | Fan-out chặn | Nối GL×Budget sai grain | `needs_confirm` + `fanOutRisk=high` |
| T-WL2-04 | Non-finance | TP-SALES | Vẫn dựng đúng, không cần pack |
| T-WL2-05 | Ledger | TP-FIN | Giả định có nguồn + risk |
| T-WL2-06 | Unknown | Cột mơ hồ | `unknown`, không đoán |
| T-WL2-07 | Determinism | Chạy 2 lần | Hash hiểu khớp |

### WL3 — Brief
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL3-01 | Output contract | TP-FIN | Đủ grain/measure/filter |
| T-WL3-02 | SP + A/B | TP-FIN | ≥5 SP, mỗi SP ≥2 option + hệ quả |
| T-WL3-03 | Số từ engine | So khớp value với formula | Không lệch |
| T-WL3-04 | Insight 2 loại | TP-FIN | Có câu hỏi + cảnh cắt |
| T-WL3-05 | Thiếu LY | TP-FIN | `missing_data`, không bịa |
| T-WL3-06 | Brief hash | 2 lần | Khớp |

### WL4 — Freeze + Compile
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL4-01 | Freeze | Chốt hết ngoại lệ | Spec có snapshotHash+decisionsHash |
| T-WL4-02 | Step mapping | Xem steps | Mỗi quyết định → step, đúng dependency |
| T-WL4-03 | Invalidate | Đổi 1 quyết định | Spec cũ stale |
| T-WL4-04 | Unverified | Còn assumption | Nhãn `unverified` |
| T-WL4-05 | Idempotent | Compile 2 lần | Cùng hash |

### WL5 — Preview + Reconcile
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL5-01 | Preview không ghi nguồn | Chạy preview | Source byte-identical |
| T-WL5-02 | Values-only | Kiểm package | Không formula/query/connection |
| T-WL5-03 | Control total | So tổng | Khớp nguồn |
| T-WL5-04 | Bridge | Kiểm `Op+FX=Total` | Đúng đại số |
| T-WL5-05 | Reconcile fail | Inject lệch | Khoá duyệt |
| T-WL5-06 | Determinism | Chạy 2 lần | Cùng preview hash |

### WL6 — Duyệt + Ghi
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL6-01 | Ghi kết quả | Duyệt | Sheet kết quả đúng values |
| T-WL6-02 | Source bất biến | So hash nguồn | Không đổi |
| T-WL6-03 | Không auto-save | Kiểm trạng thái | Chưa save |
| T-WL6-04 | Approval 1 lần | Duyệt lại | Bị chặn, cần preview mới |
| T-WL6-05 | Nhãn | Kiểm sheet kết quả | Có marker + provenance |

### WL7 — Verify + Record
| ID | Mục tiêu | Bước | Kỳ vọng |
|---|---|---|---|
| T-WL7-01 | Delta | Xem delta sheet | rows/nulls/dupes trước–sau |
| T-WL7-02 | Record đầy đủ | Xuất record | Đủ snapshot/brief/decisions/steps/reconcile |
| T-WL7-03 | Không Verified cho AI | Kiểm nhãn | Chỉ `unverified`/`assumed` |
| T-WL7-04 | Record hash | Kiểm | Khớp |
| T-WL7-05 | Stale | Đổi nguồn | Record stale |

### E2E (sau WL7)
| ID | Mục tiêu | Kỳ vọng |
|---|---|---|
| T-E2E-FIN | TP-FIN đầy đủ | Brief→Spec→Preview→Reconcile→Ghi→Record pass |
| T-E2E-SALES | TP-SALES | Chạy generic không cần pack |
| T-E2E-UNKNOWN | TP-UNKNOWN | 2 kịch bản + ledger, không ép chọn |
| T-E2E-NOPACK | Không pack | Generic mode + cảnh báo rõ |

## 14. Definition of Done theo WL

| WL | DoD tối thiểu |
|---|---|
| WL1 | Nạp 4 connector, snapshot + fingerprint ổn định, chặn file lạ |
| WL2 | Vai/khoá/quan hệ + ledger; fan-out chặn; determinism |
| WL3 | Contract + ≥5 SP A/B (TP-FIN) + insight 2 loại + số từ engine |
| WL4 | Freeze + step mapping + idempotent + invalidate |
| WL5 | Preview values-only + 3 reconcile + block khi lệch |
| WL6 | Ghi values-only + source bất biến + approval 1 lần |
| WL7 | Delta + Record đầy đủ + nhãn đúng + stale |

## 15. Traceability (rút gọn)

| Nhóm | Liên hệ |
|---|---|
| Get Data | `SPEC.md` FR-001/003/023 |
| Hiểu/mapping | `SPEC.md` FR-004/005 |
| Brief/AI phản biện | `SPEC.md` FR-024/025/026/027/028 |
| Thực thi Typed | `PQ_CODE_M_SPEC.md` Typed Steps v2 |
| Preview/apply | `PQ_CODE_M_SPEC.md` PQ-FR-004..008 |
| Profile | `TYPED_STEP_DIAGNOSTICS_SPEC.md` TSD-FR-001/BR-003 |
| Nguồn read-only | `UI_RAW_DATA.md` §Ranh giới an toàn |
| UI/icon/a11y | `TASKPANE_UI.md` UI-001, UI-006, UI-007 |

---

## 16. UX/UI Specification (bàn giao implement)

### 16.1 Ràng buộc & nguyên tắc

- Task pane **dọc**, rộng hiệu dụng ~300–320px, cuộn dọc; không cuộn ngang.
- **AI-first:** mặc định 3 khối mở: **Nguồn** + **Hiểu dữ liệu** + **Đề bài** (feature 004, 2026-11-22). Các khối khác thu gọn.
- **Exception-based:** người dùng chỉ mở "AI đã hiểu" / giả định **khi cần sửa**.
- **Không giấu nhãn:** status chip luôn có **icon + chữ + màu** (không chỉ màu).
- **Không nhảy layout:** slot trạng thái cố định chiều cao; không đẩy thẻ khi đổi trạng thái.
- Theo `TASKPANE_UI.md` UI-001: dùng **Lucide allowlist** + license; icon-button phải có `aria-label` tiếng Việt + `title`/tooltip + focus visible + disabled state; **không CDN**; **không SVG người dùng**.
- Mọi hành động **ghi** phải qua nút bấm tường minh; **không auto**; không `window.confirm`.
- Nút/badge không được là nơi duy nhất chứa thông tin (phải có text/aria).

### 16.2 Bản đồ màn hình

| Màn | Tab | Kích hoạt khi | Mục đích |
|---|---|---|---|
| S0 · Get Data | Trợ lý | mở pane | thêm nguồn, chọn bảng |
| S1 · Hiểu dữ liệu | Trợ lý | sau snapshot (bước 2 của hành trình) | tổng quan, danh sách sheet (vai trò, khóa, `grainKind`), quan hệ (danh sách | sơ đồ), cảnh báo, xác nhận tại chỗ |
| S2 · Decision Brief | Trợ lý | sau S1 | phát hiện + SP A/B + insight + ledger + chốt |
| S3 · Sơ đồ quan hệ | Trợ lý (panel/modal) | từ S1 | xem dây nối; nút `Mở rộng` mở cửa sổ 1 : 3 (mọi sheet) khi `DialogApi 1.2` được hỗ trợ |
| S4 · Execution | PQ_Code-M | sau freeze | step list |
| S5 · Preview | PQ_Code-M | sau compile | before/after + reconcile |
| S6 · Result | PQ_Code-M | sau apply | delta + Decision Record |

Ghi chú 2026-11-22 (feature 004): thẻ cấu trúc và nút đo cấu trúc đứng sau thẻ đề bài (S1/S3 cũ) được thay bởi bước `2. Hiểu dữ liệu` của hành trình; state machine (`new → ingested → understood → …`) không đổi — bước Hiểu tương ứng stage `understood`. Chi tiết: `specs/004-understand-data-step/spec.md`.

### 16.3 Wireframe từng màn

**S0 · Get Data**
```text
┌──────────────────────────────────────────────────────┐
│ TRỢ LÝ · PnL 2026-09                     [↻]         │
├──────────────────────────────────────────────────────┤
│ 01 · NGUỒN DỮ LIỆU                                    │
│ [+ Workbook] [+ Excel] [+ CSV] [+ Thư mục]            │
│                                                      │
│ Nguồn đã thêm                                        │
│  ● Finance_PnL.xlsx   Excel   7 bảng     ✓           │
│  ● Returns_09.csv     CSV     1 bảng     ⚠ delimiter │
│                                                      │
│ Navigator: Finance_PnL.xlsx                          │
│  [x] GL_Sep      42.318 dòng · 9 cột                 │
│  [x] Budget       1.240 dòng · 5 cột                 │
│  [x] CoA            312 dòng · 6 cột                 │
│  [ ] Q1_old                    (bỏ chọn)             │
│  [Thêm vào phiên]                                    │
├──────────────────────────────────────────────────────┤
│ 02 · ĐỀ BÀI                                          │
│ [Ví dụ: DT thuần & LN gộp T9 giảm do giá hay tỷ giá?]│
│ [Phân tích →]                                        │
└──────────────────────────────────────────────────────┘
```

**S1 · AI đã hiểu (thu gọn mặc định)**
```text
┌──────────────────────────────────────────────────────┐
│ 🤖 TÔI HIỂU                                        ▾ │
│  Nguồn: 7 bảng · Fact=GL_Sep · Dim=CoA/CC/Entity     │
│  Grain: account × CC × month                          │
│  Nối: GL↔CoA (98%) · GL↔CC (99%) · GL↔FX (62% ⚠)     │
│  [Sửa cách hiểu]  [Sơ đồ quan hệ]                    │
├──────────────────────────────────────────────────────┤
│ 🤖 GIẢ ĐỊNH (sửa 1 click)                            │
│  • Net = Gross−Returns−Discount    [Sửa]             │
│  • FX dùng average rate            [Sửa]             │
│  • Loại intercompany               [Sửa]             │
└──────────────────────────────────────────────────────┘
```

**S2 · Decision Brief**
```text
┌──────────────────────────────────────────────────────┐
│ TRỢ LÝ · 03 · PHÂN TÍCH                    [i]       │
├──────────────────────────────────────────────────────┤
│ PHÁT HIỆN                                             │
│  • Doanh thu VND −6,6% · USD −2,1% → FX là chính    │
│  • 1.240 dòng trùng · 3 TK chưa map                 │
│  • 7 mã CC lạc · thiếu 1 average rate               │
├──────────────────────────────────────────────────────┤
│ MỔ XẺ                                                 │
│ ┌ SP-1 Net revenue gồm rebate?           ❓ ───────┐│
│ │ A: Gross−Returns−Discount                       ││
│ │ B: như A + Rebates                              ││
│ │ Hệ quả: gross margin khác ~X pp                 ││
│ │ [A] [B]                                          ││
│ └──────────────────────────────────────────────────┘│
│ ┌ SP-2 FX basis                          ❓ ───────┐│
│ │ A: budget rate  ·  B: actual rate               ││
│ │ [A] [B]                                          ││
│ └──────────────────────────────────────────────────┘│
│ ┌ SP-6 Nối bảng                     ✅ tự động ───┐│
│ │ GL ↔ CoA ↔ CC ↔ Entity ↔ FX                     ││
│ │ 4 dây 98–99% · 1 dây cần xác nhận (62%)         ││
│ │ [Sơ đồ quan hệ]                                  ││
│ └──────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────┤
│ CẦN CHỐT: ○ Rebate  ○ IC/accrual  ○ FX basis         │
│ [Tạo Execution Spec →]                                │
└──────────────────────────────────────────────────────┘
```

**S3 · Sơ đồ quan hệ**
```text
┌──────────────────────────────────────────────────────┐
│ SƠ ĐỒ QUAN HỆ            [Dò lại]  [+ Thêm tay]      │
├──────────────────────────────────────────────────────┤
│ GL_Sep ──98%──► CoA          ✓ 1:1                   │
│ GL_Sep ──99%──► CostCenter   ✓ N:1                   │
│ GL_Sep ──97%──► Entity       ✓ N:1                   │
│ CostCenter ──95%──► Entity   ✓ N:1                   │
│ GL_Sep ──62%──► FX(Curr×Month)  [Xác nhận ⚠]         │
│ Budget ──96%──► CoA          ✓ 1:1                   │
├──────────────────────────────────────────────────────┤
│ Bấm dây để đổi khoá/loại · xoá dây · xem bằng chứng  │
└──────────────────────────────────────────────────────┘
```

**S4 · Execution**
```text
┌──────────────────────────────────────────────────────┐
│ PQ_Code-M · THỰC THI                     [Spec v3]    │
├──────────────────────────────────────────────────────┤
│ 01 · STEP LIST (12)                                   │
│  1 ✓ Dedupe GL (Entity+Ledger+DocNo+Line)            │
│  2 ✓ Chuẩn hoá sign                                   │
│  3 ✓ Chuẩn hoá CostCenter                             │
│  4 ✓ Map tài khoản lạc                                │
│  5 ✓ Join CoA (đệ quy)                                │
│  …                                                    │
│ 11 ⏸ Variance (chờ SP-7)                              │
├──────────────────────────────────────────────────────┤
│ [Chạy preview]                                        │
└──────────────────────────────────────────────────────┘
```

**S5 · Preview + Reconcile**
```text
┌──────────────────────────────────────────────────────┐
│ 02 · PREVIEW (workbook tạm)                           │
│ Trước 42.318 → Sau 40.906 dòng                        │
│ Control total GL ✓    Bridge FX+Op=Total ✓            │
│ [Xem before/after]                                    │
├──────────────────────────────────────────────────────┤
│ [Duyệt & ghi kết quả]   (khoá nếu reconcile fail)     │
└──────────────────────────────────────────────────────┘
```

**S6 · Result**
```text
┌──────────────────────────────────────────────────────┐
│ 03 · KẾT QUẢ                                          │
│ Đã ghi PnL_Result · nhãn: unverified                 │
│ Δ: rows −1.412 · null +0 · dupe −1.240               │
│ [Tải Decision Record]                                 │
└──────────────────────────────────────────────────────┘
```

### 16.4 Component spec

| Component | Dữ liệu | States | Hành động | A11y |
|---|---|---|---|---|
| `ConnectorButtons` | loại nguồn | enabled/disabled | thêm nguồn | `aria-label` từng nút |
| `SourceList` | Source[] | empty/loading/error | xoá nguồn, xem lỗi | list role |
| `Navigator` | Table[] | — | tick/bỏ bảng | checkbox + label |
| `CsvOptions` | encoding/delimiter/header | auto/manual/warning | chọn lại | select có label |
| `TablePreview` | Table | — | — | table + caption |
| `UnderstandPanel` | model hiểu | collapsed/expanded | sửa, mở sơ đồ | `aria-expanded` |
| `SubProblemCard` | SubProblem | status | chọn A/B, sửa | radio group + `aria-checked` |
| `StatusChip` | status | — | — | icon + text |
| `AssumptionLedger` | Assumption[] | — | sửa nguồn | list |
| `InsightCases` | case[] | — | — | list |
| `FreezeBar` | blockers | enabled/disabled | freeze | `aria-disabled` |
| `StepCard` | Step | ok/pending/blocked | edit | listitem |
| `PreviewPanel` | Reconciliation | loading/pass/fail | xem before/after | — |
| `ReconcileBanner` | Reconciliation | pass/fail | — | `role=status` |
| `ApproveBar` | preview hash | enabled/disabled | approve | `aria-disabled` |
| `ResultPanel` | labels, delta | — | tải record | — |

### 16.5 Trạng thái UI ↔ state machine

| State | UI hiển thị | Nút bị khoá |
|---|---|---|
| `ingested` | S0 xong → S1 | Phân tích |
| `understood` | S1 + S2 nháp | Freeze |
| `briefed` | S2 đầy đủ | Freeze nếu còn blocker |
| `frozen` | S4 step list | Chạy preview nếu step lỗi |
| `compiled` | S4 + nút preview | Approve |
| `previewed` | S5 before/after | Approve nếu reconcile fail |
| `reconciled` | S5 pass banner | — |
| `approved/applied` | S6 | — |
| `recorded` | S6 + record | — |

### 16.6 Copy & nhãn

- **Status chip:** `✅ Đã xác nhận` · `🔎 Suy ra` · `🤖 Giả định` · `❔ Chưa rõ` · `⚠ Thiếu dữ liệu` · `⛔ Xung đột`.
- **Nút:** `Thêm nguồn` · `Phân tích` · `Sửa cách hiểu` · `Sơ đồ quan hệ` · `Tạo Execution Spec` · `Chạy preview` · `Duyệt & ghi kết quả` · `Tải Decision Record`.
- **Thông điệp lỗi:** ngắn, nêu nguyên nhân + cách sửa; không lộ raw data.
- **Không dùng:** "AI nghĩ rằng", "có thể đúng" — thay bằng nhãn trạng thái tương ứng.

### 16.7 Interaction rules

- Panel "AI đã hiểu" **thu gọn mặc định**, chỉ mở khi người dùng bấm — đến đây được thay bởi bước `2. Hiểu dữ liệu` (feature 004, 2026-11-22): bước này là bước chính của hành trình (không thu gọn), hiện tổng quan/sheet/quan hệ/cảnh báo và cho trả lời tại chỗ; sơ đồ quan hệ nằm trong bước này.
- Mỗi giả định sửa **1 click**, không mở form dài.
- `Freeze` chỉ bật khi **không còn** blocker (unknown/conflict chưa xử lý).
- `Approve` chỉ bật khi **reconcile pass**; fail thì hiện banner + lý do.
- Đổi bất kỳ quyết định nào sau freeze → **invalidate** + banner `Spec stale`.
- Không `window.confirm`; dùng overlay trong pane nếu cần xác nhận.
- Giữ focus hợp lý sau mỗi hành động; không nhảy scroll.

### 16.8 Handoff cho GPT (thứ tự build)

1. **WL1 → S0**: `ConnectorButtons` + `Navigator` + `SourceList` + snapshot hash. Dùng mock data theo `Source/Table` trong mục 7.
2. **WL2 → S1/S3**: `UnderstandPanel` + `StatusChip` + graph. Render từ `Role/Relationship`.
3. **WL3 → S2**: `SubProblemCard` + `AssumptionLedger` + `InsightCases`. **Số lấy từ field `value`, không tự tính.**
4. **WL4 → S4**: `StepCard` list + nút freeze.
5. **WL5 → S5**: `PreviewPanel` + `ReconcileBanner`; khoá approve khi fail.
6. **WL6 → S5**: `ApproveBar` + ghi values-only.
7. **WL7 → S6**: `ResultPanel` + delta + record.

**Do / Don't:**
- DO: hiển thị mọi nhãn trạng thái; khoá nút theo state; giữ layout ổn định.
- DON'T: tự sinh số/label "Verified" cho AI; auto-write; ẩn nhãn `assumed/unknown`.
- Test hook: mỗi component gắn `data-state` để test theo mục 13.

### 16.9 Accessibility

- Mọi icon-button có `aria-label` tiếng Việt; tooltip `title`.
- Focus visible rõ; disabled dùng `aria-disabled` + style.
- Không chỉ dùng màu để báo lỗi (kèm icon + text).
- Thứ tự tab hợp lý; overlay có `role="dialog"`, `aria-modal`, focus trap.

---

## 17. Glossary

| Thuật ngữ | Nghĩa |
|---|---|
| WL | Workflow Layer — một tầng luồng (WL1..WL7) |
| Decision Brief | Báo cáo quyết định: phát hiện + sub-problem A/B + insight + ledger |
| Sub-problem (SP) | Bài toán con 1 tầng, có A/B + hệ quả |
| Provenance | Nguồn của một khẳng định (pack/data/history/llm/user) |
| Assumption Ledger | Danh sách giả định + nguồn + rủi ro |
| fan-out | Nối bảng làm nhân số dòng (sai grain/N:N) |
| values-only | Kết quả chỉ chứa giá trị, không formula/query/connection |
| Reconcile | Đối soát: row/col count, control total, bridge identity |
| control total | Tổng kiểm soát phải khớp nguồn |
| bridge identity | `Op + FX = Total` |
| Execution Spec | Bản đặc tả thi hành đã đóng băng (snapshot+decisions) |
| stale | Artifact cũ không còn hợp lệ do nguồn/giả định đổi |

---

*Mọi thay đổi luồng phải cập nhật đồng bộ `AF-*`, test tăng dần (mục 13), UX/UI (mục 16) và không được nới lỏng 7 luật ở mục 9.*
