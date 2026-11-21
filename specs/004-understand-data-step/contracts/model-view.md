# Contract — `modelView` và giao thức hộp thoại (feature 004)

Mọi object đóng: key lạ là lỗi. Mọi mảng có thứ tự tất định như ghi dưới đây.

## 1. Vị trí

`POST /api/assistant/understand` và `POST /api/assistant/state` trả thêm khóa cấp trên `modelView`.

- Khi chưa có kết quả hiểu: `modelView: null`.
- `modelView` **không** nằm trong object `understand`, không tham gia `understandHash`, `planningHash`, `specFingerprint`, Record.
- Không thêm route mới. Request của hai route không đổi.

## 2. Hình dạng

```json
{
  "schemaVersion": "1.0",
  "understandHash": "sha256:…",
  "mode": "model",
  "measuredOn": "full",
  "counts": {"tables": 8, "fact": 1, "dim": 4, "lookup": 2, "bridge": 0, "unclassified": 1,
             "relationships": 7, "needsConfirm": 2, "warnings": 3},
  "tables": [
    {
      "tableId": "t_…", "name": "orders", "rowCount": 12480, "measuredRows": 12480,
      "structural": "fact", "confidence": 0.75, "roleQuestionId": null,
      "grainKind": "event", "grainEvidence": {"dateColumn": "order_date", "entityColumns": [],
                                               "distinctDates": 181, "repeatedEntities": 0, "entities": 0},
      "grainQuestionId": null,
      "keys": [["order_id"]],
      "dateRange": {"column": "order_date", "min": "2026-01-02", "max": "2026-06-30"},
      "columnCount": 5,
      "columns": [
        {"name": "order_id", "type": "text", "role": "key", "isKey": true, "isLink": true,
         "nullRate": 0, "distinctCount": 12480}
      ]
    }
  ],
  "relationships": [
    {"id": "rel_…", "fromTable": "t_…", "fromColumns": ["order_id"],
     "toTable": "t_…", "toColumns": ["order_id"],
     "cardinality": "N:1", "status": "auto", "fanOutRisk": "none",
     "overlap": 1.0, "orphan": 0, "rowsBefore": null, "rowsAfter": null,
     "wireState": "safe", "questionId": null}
  ],
  "warnings": [{"code": "…", "severity": "…", "questionId": "q_…"}],
  "modelViewHash": "sha256:…"
}
```

## 3. Quy tắc trường

| Trường | Quy tắc |
|---|---|
| `mode` | `model` nếu `understand.roles` khác rỗng; ngược lại `per_sheet` |
| `measuredOn` | `full` nếu mọi bảng được nạp ở chế độ `compute`; `sample` nếu ở `discover` |
| `rowCount` | Tổng số dòng dữ liệu của nguồn (`totalRows` của bảng) |
| `measuredRows` | Số dòng engine thực đo (số dòng trong `raw_tables`); bằng `rowCount` khi `measuredOn = full` |
| `tables` | Mọi bảng của snapshot, sắp theo `tableId` |
| `structural` | Lấy từ `understand.roles` (`fact`/`dim`/`lookup`/`bridge`); `unclassified` khi không có role cho bảng đó |
| `confidence` | Từ role; `null` khi `unclassified` |
| `roleQuestionId` | `id` của câu hỏi `topic: "role"` ứng với bảng, nếu có; ngược lại `null` |
| `grainKind`, `grainEvidence` | Theo spec §6 |
| `grainQuestionId` | `id` của câu hỏi `topic: "grain"` ứng với bảng, nếu có |
| `keys` | Tối đa 3 khóa ứng viên duy nhất, không null, từ `key_report`; mỗi khóa là danh sách tên cột theo thứ tự của `key_report`; sắp theo (số cột, tên cột) |
| `dateRange` | Từ cột ngày đầu tiên theo thứ tự cột; `null` nếu không có cột ngày |
| `columnCount` | Tổng số cột thật của bảng |
| `columns` | Tối đa 200 cột đầu theo thứ tự cột nguồn |
| `columns[].type` | Trường `type` của cột trong snapshot WL1 (cùng giá trị planner đang dùng) |
| `columns[].role` | Từ `column_roles`: `key`/`date`/`amount`/`percent`/`currency`/`text`/`unknown` |
| `isKey` | Cột thuộc ít nhất một khóa trong `keys` |
| `isLink` | Cột thuộc `fromColumns` hoặc `toColumns` của ít nhất một quan hệ trong `relationships` |
| `relationships` | Đúng các quan hệ của `understand.relationships`, cùng thứ tự; `overlap`, `orphan` lấy từ `evidence`; `rowsBefore`/`rowsAfter` từ `fanOutEvidence` hoặc `null` |
| `wireState` | `fanout` nếu `fanOutRisk = "high"`; ngược lại `orphan` nếu `orphan > 0`; ngược lại `safe` |
| `questionId` (quan hệ) | `id` của câu hỏi `topic: "relationship"` có `evidence[].ref` bằng `id` quan hệ; ngược lại `null` |
| `warnings` | Mỗi cảnh báo của `understand.warnings`: chỉ `code`, `severity` và `questionId` của câu hỏi `topic: "warning"` tương ứng. Lời nhắn hiển thị lấy từ câu hỏi, không sao chép vào đây |
| `counts.needsConfirm` | Số câu hỏi thuộc topic `relationship`, `role`, `grain` |
| `modelViewHash` | `canonical_hash` của toàn bộ object trừ chính trường này |

## 4. Nội dung nhạy cảm

- Không có `sample`, giá trị ô, `evidence` thô, đường dẫn, tên file gốc.
- Ngoại lệ duy nhất: `dateRange.min`/`max` là hai giá trị ngày ISO lấy từ dữ liệu. Chúng chỉ dùng để hiển thị local. Không được log, không được đưa vào bất cứ request nào tới Codex.
- Contract test phải chứng minh: fixture có giá trị ô đánh dấu (chuỗi sentinel) không xuất hiện ở bất cứ đâu trong `modelView` đã serialize.

## 5. Câu hỏi `grain`

Thêm vào `_questions`, dùng đúng hàm `add` hiện có:

| Trường | Giá trị |
|---|---|
| `topic` | `"grain"` |
| `question` | `"Bảng <tên bảng> là ảnh chụp theo ngày (không cộng dồn số liệu qua các ngày)?"` |
| `options` | `["Đúng, là ảnh chụp", "Không, là sự kiện", "Chưa rõ"]` |
| `evidence` | `[{"kind": "grain", "ref": <tableId>, "value": <grainEvidence>}]` |
| Điều kiện | `grainKind = "snapshot"` và `structural ∉ {"dim", "lookup"}` |

`id` các câu hỏi khác không đổi. Thứ tự danh sách vẫn sắp theo `id`.

## 6. Lỗi

Một mã lỗi mới: `AF_UNDERSTAND_LIMIT` (HTTP 409). Trả khi `understand` gặp `ValueError` giới hạn tính toán của WL2 (các thông báo "exceeds the bounded …" trong `assistant_keys`). Thông báo cho người dùng: "Dữ liệu vượt giới hạn đo cấu trúc trên toàn bộ dòng." Trạng thái store sau lỗi giống như sau `AF_UNDERSTAND_INVALID` hiện nay: không có kết quả hiểu nửa vời. Mọi `ValueError` khác vẫn là `AF_UNDERSTAND_INVALID`.

Lỗi dựng `modelView` (dữ liệu không nhất quán với snapshot) ánh xạ về `AF_UNDERSTAND_INVALID`; không trả `understand` mà thiếu `modelView`.

Task pane chỉ được nạp lại ở `discover` khi nhận `AF_UNDERSTAND_LIMIT` hoặc `REQUEST_LIMIT` từ lần nạp/đo `compute`, và chỉ một lần.

## 7. Giao thức hộp thoại

Trang: asset tĩnh cùng origin với task pane, đăng ký trong danh sách asset của coordinator. URL không có query chứa dữ liệu hay token.

Message là JSON, object đóng, trường `type` bắt buộc.

| Hướng | `type` | Nội dung | Ghi chú |
|---|---|---|---|
| hộp thoại → task pane | `ready` | — | Gửi khi trang nạp xong |
| task pane → hộp thoại | `model` | `modelView`, `answers` (map `questionId → chuỗi lựa chọn`), `questions` (chỉ `id`, `topic`, `question`, `options`) | Gửi sau `ready` và mỗi khi câu trả lời đổi |
| hộp thoại → task pane | `answer` | `questionId`, `answer`, `modelViewHash` | Task pane từ chối nếu hash khác hiện hành, hoặc `answer` không thuộc `options` |
| task pane → hộp thoại | `stale` | — | Nguồn/phiên/`modelViewHash` đổi; hộp thoại khóa mọi nút trả lời |
| hộp thoại → task pane | `close` | — | Người dùng bấm Thu gọn |

- Hộp thoại không gọi `fetch` tới coordinator, không đọc/ghi workbook, không giữ token.
- Message lạ, sai kiểu, hoặc quá giới hạn bị bỏ qua và không làm đổi trạng thái.
- Task pane không gửi `model` khi payload serialize vượt giới hạn message đã đo ở T406; thay vào đó hiện thông báo trong task pane.
