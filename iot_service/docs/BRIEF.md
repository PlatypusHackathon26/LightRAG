## 12. Dashboard API & Real-time SSE (Giai đoạn 4A & 4B)

Dashboard là giao diện phòng điều khiển quan sát chỉ đọc (read-only):
- Phục vụ tĩnh: `/dashboard/` (HTML/CSS/JS thuần, vendor Chart.js offline, không cần build).
- Hỗ trợ chế độ kiosk: `http://localhost:9710/dashboard/?kiosk=1` (toàn màn hình, font số lớn, ẩn thanh điều khiển và chuột khi nhàn rỗi).
- Mọi route chỉ nhận method `GET`, từ chối `POST/PUT/DELETE` với HTTP 405 Method Not Allowed.
- Trạng thái tổng máy: `critical` > `warn` > `normal`. Tự động chuyển `offline` khi không có mẫu dữ liệu trong `3 * PUBLISH_INTERVAL_S` (15 giây).
- Trạng thái can thiệp Agent: Hiển thị cờ `is_mitigated` (Đã giảm nhẹ) khi lệnh giảm tải (SET_RPM) đã được thực thi và không còn metric nào ở mức nguy hiểm (`critical`), phân biệt rõ với trạng thái `Bình thường` (vì nguyên nhân gốc còn tồn tại, phiếu sửa chữa vẫn mở).

| Route | Phương thức | Mô tả |
|---|---|---|
| `GET /api/v1/dashboard/overview` | GET | Tổng quan hệ thống (MQTT, DB, thời điểm dữ liệu mới nhất), số lượng máy theo trạng thái, danh sách máy kèm chỉ số chi tiết, xu hướng, ETA nguy hiểm, sự cố đang mở, hành động giảm nhẹ gần nhất, cờ `is_mitigated`, và tóm tắt trạng thái Agent (`agent_summary`). |
| `GET /api/v1/dashboard/agent` | GET | Thông tin trạng thái Agent: chế độ tự chủ (`autonomy_mode`), cờ bật/tắt khẩn cấp (`agent_enabled`), chế độ phân tích (`agent_mode`), đường dẫn WebUI (`webui_url`), phân loại số sự cố mở theo độ nghiêm trọng, danh sách sự cố mở và lịch sử hành động gần nhất. |
| `GET /api/v1/dashboard/agent/timeline?machine={id}&minutes=60` | GET | Mốc sự cố và hành động của một máy cụ thể (đề xuất, duyệt, ACK, hết hạn, từ chối) để đánh dấu trực quan trên biểu đồ chuỗi thời gian. |
| `GET /api/v1/dashboard/machine/{id}/series?minutes=15&step=5` | GET | Chuỗi thời gian giảm mẫu theo `step` giây (tối đa ~600 điểm) kèm ngưỡng `warn`, `critical`, danh sách lỗi PLC và mốc can thiệp của Agent trong khung giờ. |
| `GET /api/v1/dashboard/events?limit=50&machine=&severity=&since=` | GET | Danh sách sự kiện mới nhất có lọc theo máy, mức độ nghiêm trọng, thời điểm, kèm số lần lặp `repeat_count`. |
| `GET /api/v1/stream` | GET | SSE stream thời gian thực. Hỗ trợ fallback sang poll overview mỗi 3 giây nếu mạng gián đoạn. |

### Các loại bản tin SSE (`event: <type>`)
1. `snapshot`: Gửi ngay khi client kết nối, chứa dữ liệu đầy đủ tương đương `/overview`.
2. `metrics`: Dữ liệu số đo phát định kỳ (tối đa 1 bản tin/máy/`PUBLISH_INTERVAL_S`).
3. `event`: Sự kiện cảnh báo hoặc lỗi mới (kèm deduplication repeat count).
4. `machine_status`: Báo hiệu khi trạng thái tổng của máy thay đổi (bao gồm cả online <-> offline).
5. `incident`: Cập nhật sự cố (mở, đổi trạng thái, giải quyết, đóng). Không để lộ prompt hay API key.
6. `action`: Cập nhật vòng đời hành động (đề xuất, duyệt, từ chối, hết hạn, thực thi, ACK).
7. `heartbeat`: Bắn mỗi 15 giây để duy trì kết nối và phát hiện ngắt mạng.
