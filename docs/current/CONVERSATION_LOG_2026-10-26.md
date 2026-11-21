# CONVERSATION_LOG — 26/10/2026

> Ghi lại ngữ cảnh & quyết định của phiên làm việc để tiếp tục ở đúng repo.
> **Lưu ý:** phiên này mở nhầm workspace `JAMA-Phan` (dự án add-in báo giá, khác repo).
> Phần đầu về `JAMA-Phan` (refactor design pattern, dọn `.local/`, script cleanup) **không thuộc repo này** — bỏ qua.
> Từ giữa phiên chuyển sang **repo `power_bi` (Local Data Copilot / Reqwise-excel-mcp)**.

---

## 1. Mục tiêu phiên

Thiết kế **feature Trợ lý AI-first** cho Excel add-in `power_bi`:
- Tab **Trợ lý** = phân tích/tư duy (storytelling).
- Tab **PQ_Code-M** = thực thi (Typed Steps).
- Yêu cầu cốt lõi: **chính xác + ổn định + không giả kết quả**.

## 2. Quyết định đã chốt

| # | Quyết định |
|---|---|
| 1 | Trợ lý = "nghĩ" (phân tách, A/B, insight); PQ_Code-M = "làm" (Typed Steps) |
| 2 | **AI-first, exception-based**: người dùng chỉ nêu bài toán, AI tự nhận diện vai/grain/quan hệ; chỉ chốt ngoại lệ |
| 3 | 3 trụ: **Chính xác** (engine tính số, AI diễn giải) · **Ổn định** (deterministic/fingerprint) · **Không giả** (provenance/ledger/A-B) |
| 4 | Get Data theo mô hình Power BI: **Workbook + Excel file + CSV + Thư mục** (DB/Web để sau) |
| 5 | Kết quả ghi ra **sheet mới** trong workbook đang mở, values-only; không ghi nguồn, không auto-save |
| 6 | **LY (Last Year) tạm bỏ** khỏi MVP |
| 7 | Nối quan hệ **bán tự động**: auto-dò + đề xuất + xác nhận chỗ mơ hồ; **không** auto N:N / fan-out |
| 8 | Không ai có tri thức ngành → **data inference + LLM prior + history + câu hỏi nhìn-data-trả-lời-được**; unknown + hậu quả cao → 2 kịch bản A/B, không ép chọn |
| 9 | Thay "Gán vai bắt buộc" bằng panel **"AI đã hiểu"** thu gọn + Assumption Ledger |
| 10 | Generic engine + Domain pack: đổi ngành chỉ nạp pack; chưa có pack → generic mode + cảnh báo |

## 3. Luồng 8 pha (đã chốt)

```
0 Get Data → 1 Hiểu → 2 Khung → 3 Brief → 4 Chốt → 5 Thực thi → 6 Ghi → 7 Verify
```
State machine:
```
new → ingested → understood → framed → briefed → frozen
    → compiled → previewed → reconciled → approved → applied → recorded
```

## 4. Kiến trúc 5 lớp

Ingest (engine) · Understand (engine cấu trúc + AI nghĩa) · Decide (AI đề xuất + người chốt) · Execute (engine) · Verify (engine).

## 5. Bài toán thực tiễn dùng test

- **TP-FIN**: P&L Actual vs Budget (GL/Budget/MasterData/FX) — có bẫy dữ liệu.
- **TP-SALES**: doanh số theo khu vực (non-finance) — chứng minh engine generic.
- **TP-UNKNOWN**: người dùng không biết nghiệp vụ → 2 kịch bản + ledger.

## 6. Bài học từ review (Gemini/Claude)

1. **Số phải do engine tính**, LLM chỉ diễn giải; tránh "kể số" gây vênh.
2. Bridge phải đóng kín: `Op + FX = Total`; có reconcile với control total.
3. Finance có bẫy: FX join theo `TransactionCurrency`; `average` vs `closing`; COGS lag; IC hai phía; dedupe key đa pháp nhân.
4. Tách **luật dữ liệu** (auto) vs **policy nghiệp vụ** (người chốt).

## 7. Artifact đã tạo

| File | Nội dung |
|---|---|
| `docs/current/ASSISTANT_FLOW_SPEC.md` | **Spec v1.1**: 3 trụ, 5 lớp, 8 pha, WL1–WL7 (FR/BR/AC), schema, 7 luật No-fake, test tăng dần, UX/UI, Glossary |

## 8. Việc tiếp theo

- Bổ sung **JSON fixture mẫu** cho `Source / SubProblem / ExecutionSpec / Reconciliation` để test.
- Chốt **DomainPack schema** (roles, signature, policy questions, metrics, recipes).
- Bắt đầu **WL1 · Get Data**.
- Mở phiên mới với working directory = `power_bi` để làm tiếp.

---

*File này chỉ là nhật ký quyết định; spec chính thức nằm ở `ASSISTANT_FLOW_SPEC.md`.*
