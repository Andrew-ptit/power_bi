# Dùng `batch.py` + DeepSeek-V4-Flash (AMD TokenLab) để chạy task 003

> **DEPRECATED 2026-11-18.** Cách này đã bỏ: API không ổn định (503, cắt token ở 8k, model lặp dòng ở file test dài) và model không có tool nên không tự chạy test được. Bàn giao cho Codex theo [CODEX_HANDOFF.md](CODEX_HANDOFF.md). Giữ tài liệu này chỉ để tra lịch sử.

## 0. Điều phải nói trước: API chat không có tay

`batch.py` hiện chỉ là client OpenAI-compatible trỏ `https://api.tokenlab.amd.com/v1`, model lấy từ `AMD_TOKENLAB_MODEL` (`DeepSeek-V4-Flash`). Model qua API **không đọc được repo, không sửa file, không chạy test**. Vì vậy "giao việc cho model" chỉ có 2 dạng trung thực:

| Chế độ | Model làm gì | Máy bạn làm gì |
|---|---|---|
| **A. Sinh file (patch)** | Trả JSON `{files:[{path, content}]}` | Script ghi ra worktree → chạy test → nếu đỏ, gửi log lại cho model (tối đa 2 vòng) |
| **B. Review/phân tích** | Trả nhận xét, rủi ro, câu hỏi | Bạn/agent khác sửa |

Muốn "model tự làm hết" thì phải có agent có tool (Codex/DSH), không phải chat completion. Còn nếu chỉ có API thì dùng **A**.

## 1. Kiến trúc runner nên có

```
task.md (T302 + Files)  ──┐
nội dung file liên quan ──┼─→ batch.py ──(HTTPS)──> TokenLab /chat/completions
                          │                              │
                     context builder                 JSON {files, notes}
                          │                              │
                          └──── apply vào worktree ←─────┘
                                     │
                              chạy test của task
                                     │
                          đỏ? → gửi log + sửa (≤2 vòng)
                          xanh? → ghi evidence + next task
```

Bốn thứ `batch.py` cần thêm so với bản "Hello":

1. **Context builder**: đọc đúng file trong mục `Files` của task (không gửi cả repo), cắt theo hạn mức ký tự, kèm `spec.md` phần liên quan.
2. **JSON mode + parse chặt**: `response_format={"type":"json_object"}`, validate `files[].path` nằm trong allowlist của task — chặn model ghi ra ngoài phạm vi.
3. **Retry + backoff**: 429/5xx/timeout, `Retry-After`, tối đa 3 lần; log token dùng.
4. **Resume**: mỗi task một file `runs/<task>.json` (prompt hash, output, trạng thái) để chạy lại không tốn tiền.

## 2. Prompt để giao việc *viết runner* (dán cho Codex/DeepSeek agent)

```text
Repo: C:\Users\COLAIG\Downloads\power_bi. Python 3.13, đã có .env với AMD_TOKENLAB_API_KEY và
AMD_TOKENLAB_MODEL=DeepSeek-V4-Flash. batch.py hiện chỉ gửi 1 câu "Hello".

NHIỆM VỤ: nâng batch.py thành batch runner cho feature 003, chế độ "model sinh file".

HỢP ĐỒNG BẮT BUỘC:
1. Endpoint/model: đọc từ env, base_url https://api.tokenlab.amd.com/v1, dùng openai SDK như hiện có.
   Không hard-code key, không in key ra log.
2. Input: đọc specs/003-source-import-redesign/tasks.md, tách từng mục "## T3xx",
   lấy "Files" + "Test bắt buộc" + "Kiểm chứng".
3. Context: chỉ gửi nội dung các file trong "Files" (nếu tồn tại) + spec.md mục §6 luật kiểu.
   Không gửi .env, .git, binary, workbook.
4. Output model: JSON đúng schema
   {"task":"T3xx","files":[{"path":"...","content":"..."}],"notes":"...","blocked":false}
   response_format json_object; parse lỗi → retry 1 lần rồi bỏ task, không ghi file.
5. Ghi file: chỉ path nằm trong allowlist "Files" của task; ghi vào worktree/branch riêng,
   KHÔNG ghi đè nếu path lạ; in unified diff ra console trước khi ghi.
6. Verify: chạy đúng lệnh "Kiểm chứng" của task bằng subprocess, timeout 300s.
   Nếu fail: gửi lại (prompt + diff + stderr ≤ 8k ký tự) tối đa 2 vòng, rồi dừng và báo fail.
7. Resume: runs/<task>.json lưu {prompt_hash, status, tokens, output_path}. Có --force để chạy lại.
8. CLI: python batch.py --task T302 [--dry-run] [--force] [--max-turns 2]
9. Không sửa file nào ngoài batch.py và runs/ trong lần này.

KIỂM CHỨNG:
  python batch.py --list
  python batch.py --task T302 --dry-run     # in prompt đầy đủ, không gọi API
  python batch.py --task T302               # gọi thật, in diff + lưu runs/T302/
DONE: --dry-run không gọi mạng; task chạy thật ra diff đúng file allowlist; log không lộ key.
```

## 3. Prompt runtime gửi cho model (mỗi task một lần)

**System**:

```text
Bạn là kỹ sư Python/JS của repo "power_bi". Bạn KHÔNG có quyền chạy lệnh hay đọc file: mọi thứ cần thiết
đã nằm trong tin nhắn. Chỉ trả về JSON, không markdown, không giải thích ngoài JSON.

Luật cứng:
- Chỉ được tạo/sửa file nằm trong danh sách ALLOWED FILES. Path khác → bỏ, ghi vào "notes".
- Không thêm dependency, không đổi version/manifest, không xoá module cũ.
- Tôn trọng spec: nếu spec không nói rõ hoặc mâu thuẫn, đặt "blocked": true và nêu câu hỏi trong "notes".
- Giữ style hiện có của repo (docstring ngắn, stdlib, không print rác).
- Mọi test phải thật, không skip, không assert yếu.

Schema trả về:
{"task":"T3xx","blocked":false,"notes":"","files":[{"path":"...","content":"<toàn bộ nội dung file>"}]}
```

**User** (runner tự dựng):

```text
TASK T302 — <mục tiêu 1 dòng>

ALLOWED FILES:
- pbip_assistant/sources/preparation/csv_typing.py (mới)
- tests/unit/test_csv_typing.py (mới)

YÊU CẦU: <copy nguyên mục "Việc phải làm" + "Test bắt buộc" từ tasks.md>

RÀNG BUỘC TỪ SPEC (trích §6): <bảng luật kiểu>

FILE HIỆN CÓ (nếu có):
--- pbip_assistant/sources/preparation/model.py ---
<toàn bộ nội dung>

TEST PHẢI PASS: py -m unittest tests.unit.test_csv_typing -v
```

## 4. Vòng lặp sửa (khi test đỏ)

```text
Lần chạy trước FAIL. Đây là bằng chứng:
<stderr, ≤ 8000 ký tự, đã cắt bớt phần lặp>

Đây là các file bạn đã sinh: <diff>
Hãy sửa tối thiểu để test pass. Trả lại JSON đầy đủ như schema. Không đổi file ngoài ALLOWED FILES.
```

## 5. Checklist an toàn & chi phí

- `.env` không bao giờ vào prompt/log; key chỉ nằm trong process env.
- Mỗi task gửi ≤ ~60k ký tự context; nếu vượt, cắt theo file ưu tiên (spec §6 + file chính) và ghi rõ "truncated".
- `--dry-run` trước mọi lần chạy thật để xem prompt và ước lượng token.
- Chạy trên branch/worktree riêng (`git worktree add ../wt-003`), không chạy thẳng trên working tree đang dirty.
- Model trả `blocked: true` → dừng, đọc "notes", không tự đoán.
- Không bật song song >2 request: TokenLab có rate limit; song song chỉ khi task khác file (T302 || T305).

## 6. Đừng kỳ vọng gì

- Model không chạy được `pytest` thay bạn; "pass" chỉ có nghĩa khi **máy bạn** chạy lệnh kiểm chứng và thấy xanh.
- Task T306/T305 sửa HTML/JS nhiều ngữ cảnh: nhồi cả `taskpane.js` (5.400 dòng) vào prompt là tốn và dễ sai — nên cắt theo hàm/đoạn liên quan, hoặc để agent có tool làm.

## 7. Đã có: `batch.py` v2 (2026-11-18)

Đã viết lại `batch.py` theo đúng hợp đồng ở §1–§2. Không đổi endpoint/model, vẫn đọc `AMD_TOKENLAB_API_KEY` và `AMD_TOKENLAB_MODEL` từ `.env`.

```text
python batch.py --list                      # liệt kê T301–T308 + allowlist + lệnh kiểm chứng
python batch.py --task T302 --dry-run       # in prompt, KHÔNG gọi mạng (≈1.1k token)
python batch.py --task T302                 # gọi API, in diff, lưu runs/T302/proposed/
python batch.py --task T302 --apply         # ghi vào repo rồi chạy lệnh kiểm chứng
python batch.py --task T302 --apply --worktree ..\wt-003 --max-turns 2
```

Đã có: parse `tasks.md` (Files → allowlist, Kiểm chứng → lệnh chạy); context chỉ gồm file trong allowlist + spec §6, cắt theo hạn mức 60k ký tự; `response_format=json_object`; retry 429/5xx 3 lần backoff; validate path (chặn `..`, path ngoài allowlist, file > 400k ký tự); in unified diff; cache `runs/<task>/run.json`; vòng sửa khi test đỏ.

Ba giới hạn còn lại:

1. `--apply` chỉ chạy lệnh kiểm chứng, không tự tạo worktree — muốn cô lập thì tự `git worktree add` rồi truyền `--worktree`.
2. T307/T308 không có lệnh kiểm chứng nên chỉ dùng chế độ propose.
3. Model vẫn có thể trả file thiếu import hoặc không chạy được — vì vậy luôn `--dry-run` trước và xem diff trước khi `--apply`.

`runs/` và `.env` đã được thêm vào `.gitignore`.
