# Feature specification: Excel data preparation with review

**Feature**: `002-data-preparation`. **Created**: 2026-11-14 (Asia/Saigon).
**Status**: Implemented for user manual acceptance; native qualification remains pending.
**Input**: [Thiết kế tổng thể](../../docs/superpowers/specs/2026-11-13-supply-chain-assistant-design.md), prototype đã duyệt và lựa chọn làm nền trước, domain business sau.
**Git**: giữ branch main và công việc hiện có. Không thay baseline 001. DP/US/S/SC dưới đây là alias feature-local, không cấp lại FR/AC/BPMN IDs. Canonical docs/current sở hữu hợp đồng và CURRENT_STATUS sở hữu release evidence.

## Approved supersession - 2026-11-16

The user removed backup across the entire preparation flow. This decision supersedes US4/S12-S18 and DP09's backup/reopen/Undo/Redo promises. Their IDs below remain for traceability only and are cancelled for the active product. SC05 now requires no recovery journal/images/XML/Undo/Redo in active preparation; session authority TTL still applies. DP10 session limits and non-preparation history policies remain unchanged. References to backup prerequisites elsewhere in earlier requirements are superseded by this section.

Import and cleaning use transient semantic reads and native sheet identities, exact approval, one-use direct write permission and deterministic read-back. The composed application retains no recoverable before/after target images. Partial/unknown is not replayable; an explicit fresh native attachment retires unresolved authority and requires review again. It inherits no imported ownership, answers or approval. Native source-file validation/insertion remains; current-target full package comparison is removed. Personal-sheet result copies still protect the original. This does not promise destination style/structure diff coverage or Excel Ctrl+Z. See [implementation batches](backup-removal-plan.md).

## User Scenarios & Testing

### US1 — Nhập folder thành sheet riêng (P1)

Người dùng rà soát rồi nhập CSV/XLSX vào workbook đang mở. CSV nào sheet đó; XLSX nhập toàn bộ sheet cùng lượt, giữ công thức và định dạng. File nguồn và sheet có sẵn giữ nguyên.

**Independent test**: folder synthetic có CSV, XLSX hai sheet tham chiếu nhau và XLSX trùng tên sheet; đích có sheet cá nhân. Oracle độc lập về số sheet, dữ liệu, formula, format, kết quả tính và hash file nguồn.

- **S01** Rà soát ánh xạ file/sheet→tên đích, tạo đúng số sheet; không append CSV và không đè sheet.
- **S02** Formula chéo, defined names và Table names không đổi nghĩa sau collision handling; không âm thầm đổi thành values-only hoặc tạo link về file nguồn.
- **S03** CSV mơ hồ, source thay đổi, workbook protected hoặc preservation không được hỗ trợ: chặn phần liên quan trước ghi, giải thích cách xử lý.
- **S04** Import lỗi giữa lượt: ghi nhận chính xác sheet đã tạo/trạng thái partial hoặc unknown, không retry hay tuyên bố rollback tự động.

### US2 — Quét, hỏi từng câu theo nhóm và xem trước (P1)

Người dùng nhận đề xuất làm sạch cơ bản, đi qua nhóm tab và xem/sửa câu trả lời. Quét và đề xuất chưa thay đổi dữ liệu, chưa cần KPI hoặc Codex.

**Independent test**: `" KH01 "`, `"00123"`, ngày `03/04/2026`, ngày sai, số `1.234,50`, ô trống, formula error và dòng trùng.

- **S05** Hiện vấn đề, lý do, phạm vi, số ô ảnh hưởng và ví dụ trước/sau, không tự ghi.
- **S06** Ngày/số mơ hồ: hỏi format/locale theo cột, chưa rõ thì chặn chuyển đổi phụ thuộc. Mã 0 đầu giữ text.
- **S07** Back/Next và sổ câu trả lời giữ trạng thái; sửa câu trước đánh dấu phần phụ thuộc và vô hiệu preview/approval cũ.
- **S08** Missing values, formula errors, duplicates chỉ phát hiện/hỏi; không tự điền/xóa. Không thay formula bằng cleaned values.

### US3 — Áp dụng đúng nơi (P1)

Sheet do import của phiên được clean trực tiếp sau duyệt/backup. Sheet có sẵn trong workbook cá nhân phải tạo result sheet riêng; không bắt buộc nhập folder.

**Independent test**: cùng dữ liệu trên imported sheet và personal sheet, assert khác target và source cá nhân nguyên vẹn.

- **S09** Apply đúng exact preview trên sheet import có ownership được chứng thực, giữ công thức/format ngoài thay đổi được duyệt.
- **S10** Sheet có sẵn: tạo tên kết quả không trùng, giữ nguyên nguồn; tên/marker đơn lẻ không chứng minh quyền ghi tại chỗ.
- **S11** Source/answer/workbook thay đổi hoặc backup thiếu: chặn trước ghi. Write/read-back failure sau consume: partial/unknown, không auto retry.

### US4 [Cancelled by the 2026-11-16 decision] — Undo/Redo và mở lại task pane (P1)

↶/↷ cho thao tác ghi của preparation, không thay Undo Excel cho sửa tay. Đóng/mở task pane còn lịch sử khi logical preparation session chưa hết hạn.

**Independent test**: import→clean→undo→redo→undo→new edit; reopen; TTL; quota; manual conflict; fault sau ghi; oracle formula/format/structure độc lập.

- **S12** Undo/Redo khôi phục đầy đủ affected data/formulas/formats/structure, read-back rồi mới đổi cursor; không hứa thay toàn bộ workbook.
- **S13** Reopen cùng workbook: giữ journal, tái xác thực binding và cấp authority mới; không phục hồi token/approval cũ, không lẫn workbook clone.
- **S14** Idle 1.800 giây hoặc absolute 28.800 giây: hết hạn backup, workbook data giữ nguyên. Không hứa qua crash/coordinator restart.
- **S15** Quota đầy: loại điểm cũ nhất, thông báo nhẹ và giữ chuỗi còn lại dùng được. Backup đơn lẻ quá lớn/tạo thất bại: chặn ghi.
- **S16** Thay đổi mới sau Undo bỏ Redo cũ. Sửa tay vùng liên quan: hỏi và kiểm tra, không tự ghi đè hoặc override hard blocker.
- **S17** Restore/write unknown: giữ receipt/evidence, chặn replay; không giả định backup đồng nghĩa rollback đã thành công.
- **S18** Restore point cũ/khác phiên/bị eviction: từ chối, không đọc path tùy ý hoặc restore truncated payload.

### Edge Cases

Collision tên khác hoa/thường/Unicode, hidden sheet, named ranges và structured references; external links; protected structures; ZIP bomb; CSV formula-like text; date systems/locales; source đổi trong lúc đọc; pane đóng lúc ghi; unsaved books/clone cùng marker; manual edits; hai click đồng thời; quota khi đang có pending write và TTL khi job đang chạy.

## Requirements

### Functional Requirements

- **DP01** Folder CSV/XLSX tách sheet, nguyên file nguồn và sheet không liên quan; connector append cũ vẫn tương thích.
- **DP02** XLSX preservation là điều kiện bật capability, unsupported bị chặn, không downgrade thầm lặng.
- **DP03** Scope/phép ghi/target cần duyệt, không tự Save, không tự refresh file đè sheet.
- **DP04** Imported ownership dựa vào binding của phiên và receipt, không chỉ tên/path/marker có thể copy.
- **DP05** Preview/review/approval bind exact source, answers, changes, target và revision. Full affected-scope read-back; partial/unknown không replay.
- **DP06** Trim ở đầu/cuối ô; date/number theo format rõ; mã 0 đầu giữ text; formulas giữ nguyên.
- **DP07** Wizard nhóm ngắn, một câu/lần, xem/sửa, dirty review, keyboard/accessibility và pane hẹp.
- **DP08** Imported sheet clean tại chỗ; personal existing sheet có result copy riêng.
- **DP09** Backup trước ghi; bounded FIFO undo/redo, giữ lịch sử khi pane reopen, phân biệt điều hướng với restore.
- **DP10** 30 phút idle/8 giờ absolute, auth/slot/lock/job pin giữ nguyên; không hồi sinh session hết hạn.
- **DP11** Manual conflicts phải hỏi và verify; user không thể override failure kỹ thuật.
- **DP12** Preparation hoạt động local, không gửi raw data/paths/whole workbook sang AI. Disclosure luồng cũ giữ nguyên.
- **DP13** KPI, supply-chain packs, business advice, persistent business-rule import/export để giai đoạn sau. Lựa chọn locale trong phiên không phải bộ quy tắc nghiệp vụ lâu dài.
- **DP14** Không mở Typed catalog, sửa Problem Chain semantics, cancelled fields hoặc Advanced no-backup exception; Advanced live vẫn Deferred.
- **DP15** Synthetic automated + actual Office runtime success/recovery trước công bố capability; release metadata giữ nguyên.

### Key Entities

WorkbookBinding, PreparationSession, ImportedSheetOwnership, SourceInventory, ScanFinding, Question, AnswerRevision, CleanupPreview, MutationAttempt, RestorePoint và Evidence; xem data-model.md.

## Success Criteria

- **SC01** Fixture hỗn hợp tạo đúng mapping/count, source file hashes không đổi.
- **SC02** Mọi fixture preservation được hỗ trợ đúng data/formula/format/semantics sau import/apply/undo/redo; unsupported chặn trước ghi.
- **SC03** 100% fixture ambiguous/stale/expired/ownership giả/backup failure/manual conflict không tự ghi.
- **SC04** Đi trọn wizard ở 360px và bằng keyboard; câu trả lời và các trạng thái review/reopen đúng S05–S18.
- **SC05** Journal không vượt giới hạn bytes/entries và 1.800/28.800 giây; nút restore không hiển thị điểm không dùng được.
- **SC06** Từng gate có command/revision/layer/status/time/error/dimensions/fingerprints; fake/HTTP không được gắn nhãn live.

## Assumptions

- Windows Excel Desktop là target đầu tiên. Host capability gate thực tế quyết định hỗ trợ; không tự nâng manifest floor.
- Hai tab Trợ lý/PQ_Code-M giữ nguyên; preparation là controller nhỏ trong Trợ lý.
- Không hỗ trợ mọi cấu trúc Excel ngay. Phạm vi phải được gate xác định công khai, không bỏ mất metadata để báo pass.
- Privacy và source preservation bao gồm nội dung nguồn, không cấm metadata binding riêng được giải thích rõ; không auto Save để lưu metadata.


## Approved journey refinement - 2026-11-15

The open workbook is always the destination, whether new or existing. Source selection opens the native folder browser, then a per-file selection list with Select all. One CSV becomes one sheet; every sheet of a chosen XLSX is selected as a single group. Confirming selection starts actual conversion/import with progress and advances only after verified native read-back. Directory inventory alone never unlocks cleaning.

After import, scan every data-bearing sheet in the destination, reporting empty/non-tabular or unsupported sheets explicitly. Missing date/number interpretation pauses for the relevant question; no locale inference. Loading indicates inspection, not automatic destructive cleaning. Show exact changes before approval, then apply only the approved diff. A verified no-change review can advance to the existing business prompt. Existing personal sheets produce separate results; verified session-owned imports may be cleaned in place.

Add source is available during cleaning and at the business prompt. It returns to the same browser/selection flow and appends sheets. Navigation/cancellation preserves answers and data; verified source changes invalidate dependent previews, approvals and business analysis. Keep independent answers whose source/question identity remains valid.

Execution is delegated at the user's explicit request, with the controller reviewing contracts, integrating and running automated checks. Manual whole-flow testing remains user-owned by their earlier instruction; native gates remain Not run/Blocked until evidence exists. No sample/demo service is introduced.
