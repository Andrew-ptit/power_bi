# Data model — feature 004

Hình dạng JSON chính thức ở [contracts/model-view.md](contracts/model-view.md). File này mô tả thực thể, nơi sở hữu và vòng đời.

## Thực thể

| Thực thể | Nơi tạo | Nơi giữ | Vòng đời |
|---|---|---|---|
| `ModelView` | Hàm thuần trong `sources` (T402) từ `raw_tables`, `snapshot`, `understand`, `questions` | `AssistantSessionStore`, cùng lock với `_understand` | Tạo cùng lúc với `understand`; xóa ở mọi nơi `_understand` bị xóa |
| `ModelTable`, `ModelColumn`, `ModelRelationship` | Thành phần của `ModelView` | — | Như trên |
| `GrainEvidence` | Luật spec §6 | Trong `ModelTable` và trong `evidence` của câu hỏi `grain` | Như trên |
| Câu hỏi `grain` | `_questions` | `AssistantSessionStore._questions` | Như các câu hỏi khác |
| Câu trả lời | Task pane | Trạng thái câu trả lời hiện có của luồng Trợ lý (`flow.answers`) | Như hiện có; gửi tới server chỉ khi lập kế hoạch |
| `DiagramLayout` | Hàm thuần JS (T405) từ `ModelView` + bảng trung tâm (hoặc toàn bộ) | Bộ nhớ trang | Tính lại khi `modelViewHash`, bảng trung tâm hoặc bề rộng đổi |
| `DialogMessage` | Task pane / hộp thoại | Không lưu | Một lần gửi |

## Quan hệ và ràng buộc

- `ModelView.understandHash` phải bằng `understand.understandHash` trả cùng phản hồi.
- Mỗi `ModelRelationship.id` tồn tại trong `understand.relationships`; không có quan hệ nào bị thêm hoặc bớt.
- Mỗi `*QuestionId` khác `null` phải tồn tại trong `questions` trả cùng phản hồi.
- `ModelView` không có quyền: không cấp approval, không là đầu vào của hash nào khác, không ghi vào workbook hay Custom XML.

## `DiagramLayout` (JS, không qua mạng)

```text
{ width, height,
  nodes: [{tableId, x, y, width, height, rows: [{column, y, isKey, isLink}], hiddenColumns}],
  wires: [{relationshipId, wireState, fromTableId, fromColumn, toTableId, toColumn,
           x1, y1, x2, y2, fromSide, toSide, fromMark: "many"|"one", toMark: "many"|"one"}] }
```

- Chế độ `focus`: một node trung tâm hiện mọi cột (tối đa 12, phần còn lại gộp), các node hàng xóm chỉ hiện cột khóa và cột nối.
- Chế độ `full`: mọi bảng; xếp cột theo vai trò (danh mục, giao dịch, phần còn lại), trong mỗi cột theo `tableId`.
- Quan hệ nhiều cột: một dây cho mỗi cặp cột tương ứng, cùng `relationshipId`.
- `fromMark`/`toMark` suy từ `cardinality`: `N:1` → many/one; `1:N` → one/many; `1:1` → one/one; `N:N` → many/many.

## Trạng thái UI

```text
source ──(nguồn xác minh)──► understand:loading ──► understand:ready ──(Tiếp tục)──► problem
                                   │                      │
                                   └─(lỗi)─► understand:error (Đo lại / Về Nguồn)
mọi trạng thái ──(nguồn đổi / phiên mới / workbook đổi)──► source
```

`understand:ready` tương ứng stage `understood` của server và `modelView` khác `null`.
