# BRIEF: IoT + Agent cho bệ thử máy nén DENSO (kịch bản B)

> Đặt file này vào repo tại `iot_service/docs/BRIEF.md`. Mọi prompt giai đoạn đều yêu cầu AI đọc file này trước.
> Đây là **nguồn sự thật duy nhất** về hợp đồng dữ liệu, ngưỡng và quy ước. Nếu cần đổi, sửa file này trước rồi mới sửa code.

---

## 1. Mục tiêu và phạm vi

Xây dựng một hệ thống **Agent AI giám sát và ứng phó sự cố** cho bệ thử máy nén điều hòa (A/C compressor test bench) của nhà máy DENSO:

1. Máy (giả lập) gửi **log vận hành** và **mã lỗi** qua MQTT.
2. Hệ thống **đọc log, đối chiếu với ngưỡng và tài liệu kỹ thuật**, phát cảnh báo sớm.
3. **Agent** (vòng lặp ReAct) tìm nguyên nhân gốc rễ: gọi RAG (LightRAG) để tra tài liệu, gọi công cụ đọc cảm biến để kiểm tra chéo.
4. Agent **đề xuất hoặc tự thực hiện** hành động đưa máy về vùng an toàn (hạ tốc độ), tạo phiếu sửa chữa, dưới các rào chắn an toàn.

**Phần mình xây dựng:** simulator, ingest, monitor, Tool API, Agent Gateway (`/agent/*`), Agent.
**Không xây dựng:** LightRAG server (nhóm khác dùng chung, chỉ gọi qua HTTP), WebUI (đã có, chỉ sửa tối thiểu và có điều kiện).

## 2. Ràng buộc về repo

- Repo gốc là LightRAG (đã clone). Có `lightrag/` (backend), `lightrag_webui/` (React), `docker-compose.yml`, `AGENTS.md`, `CLAUDE.md`.
- **Đọc `AGENTS.md` và `CLAUDE.md` ở gốc repo và tuân theo quy ước chung.**
- **Toàn bộ code mới nằm trong `iot_service/`.** Không sửa `lightrag/`. Chỉ được sửa `lightrag_webui/` ở Giai đoạn 2 theo đúng phạm vi mô tả ở đó, mọi thay đổi phải có điều kiện (không làm hỏng chế độ demo mock).
- Máy phát triển là **Windows** (đường dẫn kiểu `E:\...`). Hướng dẫn chạy phải dùng **PowerShell + Docker Desktop**, không dùng Makefile hay script bash. Dùng CLI Python cho mọi tác vụ demo.
- Dùng virtualenv riêng `iot_service/.venv` (không dùng chung `.venv` của LightRAG ở gốc).
- Python 3.11+, FastAPI, Pydantic v2, `paho-mqtt` hoặc `aiomqtt`, `psycopg` 3 (async), pytest.
- Cổng: Mosquitto `1883`, TimescaleDB **`5433`** (tránh đụng Postgres của LightRAG), service `9700`. LightRAG server mặc định `9621`.
- Không hard-code bí mật. Mọi cấu hình đi qua `.env` (có `.env.example`).
- Ngôn ngữ: **code, tên biến, comment bằng tiếng Anh. Tài liệu (README, docs) và thông điệp hiển thị cho người vận hành bằng tiếng Việt.**

## 3. Kiến trúc

```
[Simulator bệ thử]  --MQTT-->  [Mosquitto]  --subscribe-->  [Ingest]  --> [TimescaleDB]
   ^   metrics/events                                          |  ^
   |                                                           |  |
   | commands            [Threshold Monitor] <-- đọc DB -------+  |
   |                              |                               |
   +-- acks <-- [Command Executor] <-- [Gateway: incidents/actions/HITL] <-- [Agent / RuleAnalyzer]
                                          ^   |                       |  gọi RAG: LightRAG /query
                                          |   v                       |  gọi Tool API: status/history/events
                                      [WebUI /agent/*]  <-------------+
```

Một **service FastAPI duy nhất** (`iot_service/app`) chứa: ingest, monitor, Tool API, Gateway, Agent. Simulator là tiến trình riêng.

## 4. Kịch bản B và neo tài liệu

Máy: **bệ thử chạy rà máy nén**. Hai máy mẫu: `COMP-TB-01`, `COMP-TB-02` (định dạng ID có dấu gạch ngang).

Bộ tài liệu DENSO của nhóm là catalogue hậu mãi, **không có số liệu vận hành của bệ thử**. Vì vậy:
- **Nguyên nhân và quy tắc** lấy từ tài liệu thật (bảng dưới).
- **Ngưỡng số, mã lỗi, tên máy là GIẢ LẬP** do nhóm đặt. README và UI phải ghi rõ điều này, không được trình bày như số liệu của DENSO.

Neo tài liệu (dùng cho trích dẫn ở chế độ mock RAG):

| Ý | Tài liệu | Trang |
|---|---|---|
| Quá nhiệt máy nén do thiếu môi chất lạnh (rò rỉ), thiếu dầu (sửa sai), làm mát kém (quạt dàn ngưng hỏng hoặc dàn ngưng bẩn); áp suất nén cao gây bôi trơn kém | `DENSO-Compressor-Fault-Finding-Poster-A1_English.pdf` | 1 |
| Khởi động tốc độ quá cao không đủ thời gian cho dầu hòa với môi chất và hồi về máy nén | `DENSO-Compressor-Fault-Finding-Poster-A1_English.pdf` | 1 |
| Quy trình chạy rà: để không tải, bật A/C tối thiểu 5 phút, **không tăng tốc độ** | `AC-Compressor-Installation-Manual-multilingual.pdf` | 3 và 4 |
| Chỉ dùng đúng loại dầu ghi trên nhãn, không trộn, không dùng dầu "universal"; không đổ dầu trực tiếp vào máy nén | `AC-Compressor-Installation-Manual-multilingual.pdf` | 3 |
| ND-Oil 8 và 12 là PAG, ND-Oil 11 là POE, PAG và POE không hòa trộn | `DENSO-Compressor-Fault-Finding-Poster-A1_English.pdf` | 1 |
| Vệ sinh dàn ngưng, kiểm tra quạt | `AC-Condenser-Installation-Manual-Multilingual_web.pdf` | 4 đến 6 |

## 5. Hợp đồng dữ liệu (MQTT)

Thời gian luôn là **UTC, ISO 8601 có hậu tố `Z`**. Payload là JSON UTF-8.

### Topic

| Topic | Hướng | Nội dung |
|---|---|---|
| `denso/{machine_id}/metrics` | máy -> hệ thống | log vận hành, mỗi `PUBLISH_INTERVAL_S` (mặc định 5 s) |
| `denso/{machine_id}/events` | máy -> hệ thống | sự kiện lỗi do chính máy (PLC) phát |
| `denso/{machine_id}/commands` | hệ thống -> máy | lệnh điều khiển |
| `denso/{machine_id}/acks` | máy -> hệ thống | phản hồi lệnh |
| `denso/sim/control` | CLI -> simulator | đổi kịch bản lỗi |

### Metrics

```json
{
  "timestamp": "2026-10-07T10:15:00Z",
  "machine_id": "COMP-TB-01",
  "metrics": {
    "discharge_temp": 96.4,
    "suction_pressure": 2.1,
    "discharge_pressure": 14.8,
    "compressor_rpm": 1500,
    "condenser_fan_rpm": 2400,
    "vibration": 2.2,
    "oil_level": 88
  }
}
```

### Event (từ máy hoặc từ monitor)

```json
{
  "event_id": "b3f1c2e0-...-uuid",
  "timestamp": "2026-10-07T10:15:00Z",
  "machine_id": "COMP-TB-01",
  "source": "machine",
  "event_type": "ERROR",
  "severity": "CRITICAL",
  "error_code": "ERR_COMP_OVERHEAT_402",
  "message": "Discharge temperature exceeded 120 C"
}
```

- `source`: `machine` (PLC của máy) hoặc `monitor` (bộ giám sát ngưỡng của hệ thống).
- `event_type`: `ERROR` (máy tự báo, đã chạm giới hạn bảo vệ) hoặc `WARNING` (monitor báo sớm, mã dạng `WARN_<METRIC>_<HIGH|LOW>`, kèm `trend` và `eta_to_critical_s` nếu ước tính được).

### Mã lỗi giả lập (máy phát khi chạm ngưỡng `critical` liên tiếp 2 mẫu, phát lại mỗi 15 s khi còn vi phạm để kiểm tra dedup)

| Mã | Điều kiện |
|---|---|
| `ERR_COMP_OVERHEAT_402` | `discharge_temp` >= 120 |
| `ERR_COMP_LOWPRESS_310` | `suction_pressure` <= 1.0 |
| `ERR_COMP_HIGHPRESS_325` | `discharge_pressure` >= 23 |
| `ERR_COND_FAN_217` | `condenser_fan_rpm` <= 500 khi máy đang chạy |
| `ERR_COMP_LOWOIL_118` | `oil_level` <= 40 |
| `ERR_COMP_VIB_505` | `vibration` >= 7.0 |

### Command và ACK

```json
{ "command_id": "uuid", "timestamp": "...", "machine_id": "COMP-TB-01",
  "command": "SET_RPM", "params": {"rpm": 1000},
  "issued_by": "agent", "incident_id": "INC-0001" }
```
```json
{ "command_id": "uuid", "timestamp": "...", "machine_id": "COMP-TB-01",
  "status": "OK", "code": 200, "message": "Compressor speed set to 1000 rpm" }
```
`status` là `OK` hoặc `REJECTED` (kèm `code` 4xx và lý do). Lệnh hỗ trợ: `SET_RPM` (có giới hạn, xem mục 8) và `STOP_TEST`.

## 6. Ngưỡng giả lập (`config/machines.yaml`)

| Metric | Nhãn (vi) | Đơn vị | Vùng bình thường | Cảnh báo (warn) | Nguy hiểm (critical) | Hướng xấu |
|---|---|---|---|---|---|---|
| `discharge_temp` | Nhiệt độ đầu xả | °C | 70 đến 100 | >= 105 | >= 120 | `above` |
| `suction_pressure` | Áp suất hút | bar | 1.8 đến 3.0 | <= 1.5 | <= 1.0 | `below` |
| `discharge_pressure` | Áp suất xả | bar | 12 đến 17 | >= 19 | >= 23 | `above` |
| `condenser_fan_rpm` | Tốc độ quạt dàn ngưng | rpm | 2200 đến 2600 | <= 1500 | <= 500 | `below` |
| `vibration` | Độ rung | mm/s | 1 đến 3 | >= 4.5 | >= 7.0 | `above` |
| `oil_level` | Mức dầu | % | 80 đến 100 | <= 60 | <= 40 | `below` |
| `compressor_rpm` | Tốc độ máy nén | rpm | theo setpoint | không có | không có | `info` |

Thông số điều khiển: `rpm_setpoint` mặc định 1500, `rpm_min_safe` 800, `rpm_max` 3000.

**`direction` là bắt buộc trong mọi API trả về chỉ số.** Metric kiểu "thấp là xấu" (áp suất hút, quạt, dầu) phải được đánh giá bất thường khi **thấp hơn** ngưỡng. Một lỗi đã biết trong WebUI mock là so sánh `value > threshold` cho mọi metric.

## 7. Kịch bản của simulator

Mô hình "vật lý nhẹ": mỗi metric tiến về giá trị đích theo quán tính bậc một, thêm nhiễu nhỏ. Lỗi tiến triển tuyến tính trong `ramp_s` giây mô phỏng (mặc định 180, chỉnh được; `SIM_SPEEDUP` nhân tốc độ).

Giá trị đích khi lỗi đã **đầy đủ**, ở 1500 rpm:

| Kịch bản | discharge_temp | suction | discharge_p | fan_rpm | vibration | oil |
|---|---|---|---|---|---|---|
| `normal` | 95 | 2.4 | 14.5 | 2400 | 2.2 | 88 |
| `refrigerant_leak` | 126 | 0.8 | 11.5 | 2400 | 3.8 | 86 |
| `condenser_fan_failure` | 128 | 2.6 | 24 | 0 | 3.2 | 88 |
| `condenser_fouled` | 112 | 2.9 | 21.5 | 2300 | 2.6 | 88 |
| `low_oil` | 122 | 2.3 | 15 | 2400 | 7.5 | 35 |

**Đáp ứng với tốc độ (vòng điều khiển kín, rất quan trọng cho demo):** hạ `compressor_rpm` 500 vòng làm mục tiêu `discharge_temp` giảm khoảng 20 °C, `discharge_pressure` giảm khoảng 3 bar, `vibration` giảm khoảng 1 mm/s, ở mọi kịch bản. Hệ quả mong muốn:
- `condenser_fouled` hạ xuống 1000 rpm: trở lại vùng bình thường (đóng được sự cố).
- `condenser_fan_failure`, `refrigerant_leak`, `low_oil` hạ xuống 1000 rpm: tụt khỏi `critical` nhưng **vẫn ở mức `warn`**. Nguyên nhân gốc còn đó, nên sự cố chuyển sang trạng thái "đã giảm nhẹ" và **phiếu sửa chữa vẫn mở cho người xử lý**.

Simulator còn phải: nhận lệnh trên `commands`, kiểm tra giới hạn, đổi tốc độ, trả ACK; đổi kịch bản qua `denso/sim/control`; chạy nhiều máy cùng lúc.

## 8. Kịch bản chẩn đoán (playbook) và hành động

Đây là phần **nhóm biên soạn dựa trên poster và manual**, không phải số liệu DENSO. README phải nói rõ như vậy.

| Dấu hiệu (kết hợp) | Kết luận nghi ngờ | Hành động đề xuất |
|---|---|---|
| Quá nhiệt + áp suất hút thấp, quạt bình thường | Thiếu môi chất lạnh (rò rỉ) | Hạ rpm; phiếu: kiểm tra rò rỉ và lượng môi chất |
| Quá nhiệt + áp suất xả cao + quạt rpm thấp hoặc 0 | Quạt dàn ngưng hỏng | Hạ rpm; phiếu: kiểm tra, thay quạt |
| Quá nhiệt + áp suất xả cao + quạt bình thường | Dàn ngưng bẩn, tắc | Hạ rpm; phiếu: vệ sinh dàn ngưng |
| Quá nhiệt + mức dầu thấp + rung cao | Thiếu dầu bôi trơn | Hạ rpm, **đề xuất dừng test (cần người duyệt)**; phiếu: kiểm tra loại và lượng dầu theo nhãn, không trộn dầu |

## 9. Chế độ tự chủ và rào chắn an toàn

`AUTONOMY_MODE` (mặc định `hitl`):
- `advisory`: chỉ cảnh báo và đề xuất, không bao giờ gửi lệnh.
- `hitl`: tạo thẻ đề xuất chờ người duyệt (hết hạn sau `ACTION_TTL_S`, mặc định 60 s, hết hạn thì **không** thực thi).
- `auto_safe`: được **tự thực thi** hành động nằm trong nhóm an toàn (bên dưới), mọi hành động khác vẫn cần người duyệt.

**Rào chắn bắt buộc (nằm trong code, độc lập với LLM, LLM không thể vượt qua):**
1. Whitelist lệnh: chỉ `SET_RPM` và `STOP_TEST`. Lệnh khác bị từ chối.
2. `SET_RPM`: chỉ được **giảm** so với tốc độ hiện tại, và `rpm >= rpm_min_safe`. Không bao giờ tăng, không vượt `rpm_max`.
3. `STOP_TEST` **luôn cần người duyệt**, kể cả ở `auto_safe`.
4. `auto_safe`: tối đa 2 lệnh tự động mỗi sự cố, cách nhau tối thiểu 120 s; chỉ khi có metric ở mức `critical` hoặc `warn` kéo dài; mọi lệnh tự động phải gửi thông báo và có thể hoàn tác bởi người.
5. Mọi đề xuất, duyệt, từ chối, thực thi, ACK ghi vào `audit_log` (ai, lúc nào, tham số, kết quả).
6. Có công tắc dừng khẩn cấp `AGENT_ENABLED=false`: Agent ngừng đề xuất và thực thi, hệ thống vẫn thu log và cảnh báo.
7. Văn bản lấy từ RAG hoặc tool là **dữ liệu không tin cậy**: không được làm thay đổi tham số lệnh, tham số luôn do code kiểm tra lại theo hồ sơ máy.

## 10. Hợp đồng với WebUI

**Nguồn sự thật cho giao diện là hai file:** `lightrag_webui/src/api/agent.ts` và `lightrag_webui/src/features/agentic/types/agentic.ts`. AI phải **đọc hai file này** và khớp đúng tên trường, kiểu và đường dẫn. Nếu thiếu trường (ví dụ `direction`), **thêm có điều kiện** chứ không đổi nghĩa trường cũ.

Các endpoint Gateway đã khai báo cho Phase 2: `/agent/incidents`, `/agent/chat`, `/agent/actions/{id}/approve`, `/agent/actions/{id}/reject`, `/agent/telemetry/{deviceId}`. Kiểm tra lại bằng cách đọc `agent.ts`.

Ánh xạ mức độ: `ERROR`/`CRITICAL` -> `critical`; `WARNING` kèm metric ở `critical` sắp tới (`eta_to_critical_s` < 300) -> `high`; `WARNING` còn lại -> `medium`. Điều chỉnh theo các giá trị mà `types/agentic.ts` thực sự cho phép.

## 11. Tool API cho Agent (Giai đoạn 1)

Mọi route yêu cầu header `X-API-Key`. Phản hồi gồm JSON có cấu trúc **và** trường `summary` bằng tiếng Việt cho LLM đọc.

| Route | Mục đích |
|---|---|
| `GET /api/v1/machines` | danh sách máy và trạng thái tổng quát |
| `GET /api/v1/machine/{id}/current-status` | giá trị mới nhất mỗi metric kèm `unit`, `status` (normal/warn/critical), `direction`, ngưỡng, `summary` |
| `GET /api/v1/machine/{id}/status?at=<ISO>` | giá trị gần nhất với thời điểm `at` (đối chiếu tại lúc lỗi) |
| `GET /api/v1/machine/{id}/history?minutes=10` | min/max/avg, độ dốc mỗi phút, `trend` (rising/falling/stable), `eta_to_critical_s` |
| `GET /api/v1/machine/{id}/events?minutes=60` | các sự kiện gần đây |
| `GET /health` | kiểm tra sống |

## 12. Cơ sở dữ liệu (TimescaleDB)

- `metrics(time timestamptz, machine_id text, metric text, value double precision)`: hypertable, index `(machine_id, metric, time desc)`.
- `events`: `event_id` (khóa chính, dùng để chống trùng), `ts`, `machine_id`, `source`, `event_type`, `severity`, `error_code`, `message`, `payload jsonb`, `incident_id`.
- Giai đoạn 2 thêm: `incidents`, `actions`, `audit_log`. Giai đoạn 3 thêm: `work_orders`, `agent_steps`.
- Giữ dữ liệu `metrics` theo chính sách retention cấu hình được (mặc định 7 ngày).

## 13. Biến môi trường (`.env.example`)

`IOT_API_KEY`, `IOT_ADMIN_KEY`, `MQTT_HOST`, `MQTT_PORT`, `DB_DSN`, `GATEWAY_PORT=9700`, `PUBLISH_INTERVAL_S=5`, `SIM_SPEEDUP=1`, `DEDUP_WINDOW_S=600`, `ACTION_TTL_S=60`, `AUTONOMY_MODE=hitl`, `AGENT_ENABLED=true`, `AGENT_MODE=rules`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `RAG_BASE_URL=http://localhost:9621`, `RAG_API_KEY`, `RAG_MODE=auto`.

## 14. Quy ước chất lượng

- Mỗi giai đoạn kết thúc bằng: test chạy xanh, README cập nhật, danh sách việc đã kiểm tra thực tế (có lệnh và kết quả), và danh sách những gì **chưa** kiểm tra được.
- Không báo "xong" nếu chưa chạy thật. Nếu một phần không chạy được trong môi trường của AI, nói rõ.
- Không mở rộng phạm vi sang giai đoạn sau.
- Chống trùng lặp: cùng `machine_id` + `error_code` trong `DEDUP_WINDOW_S` chỉ tạo một sự kiện xử lý (đếm số lần lặp).
- Mọi nhật ký (log) có cấu trúc, không in khóa API.
