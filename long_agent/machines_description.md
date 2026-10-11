# ĐẶC THẢU MÔ PHỎNG 5 MÁY (machines_description.md)

> Tài liệu mô tả hành vi mô phỏng của 5 thiết bị trong dự án **Long-agent / Denso Hackathon 2026**.
> Đối tượng đọc: kỹ sư viết test, người vận hành demo, và bất kỳ ai cần hiểu vì sao
> chỉ số biến đổi trên Dashboard.

---

## 1. Tổng quan kiến trúc mô phỏng

### 1.1. Ba lớp trong `generate_telemetry()` (vòng lặp gọi cả 5 máy rồi nghỉ 1 giây ≈ 1 chu kỳ/s)

```
① ĐỘNG HỌC VẬT LÝ   x += (heat_in − heat_out) × dt     ← chỉ số lao về ĐIỂM CÂN BẰNG
② SỰ CỐ (fault)      làm đổi heat_in/heat_out/target     ← đổi điểm cân bằng mới
③ NOISE              random.uniform(±ε) trộn vào output   ← dao động nhỏ quanh mức
```

**Nguyên tắc cốt lõi — vì sao chỉ số "dao động quanh mức":**
Mỗi chỉ số có một **điểm cân bằng** (equilibrium) — giá trị mà tại đó `heat_in = heat_out`.
Khi không có sự cố, chỉ số hội tụ về điểm cân bằng này và **dao động ±noise quanh nó**
(làm tròn + nhiễu ngẫu nhiên nên đồ thị luôn "rung" nhẹ, không bao giờ là đường thẳng chết).

**Quy tắc thiết kế (đã hiệu chỉnh):** điểm cân bằng bình thường **trùng với giá trị khởi tạo**,
nên máy chạy bình thường thì chỉ số **nằm yên quanh mức**, không trôi.

| Máy | Chỉ số | Khởi tạo = điểm cân bằng | Hệ số đã sửa |
|---|---|---|---|
| CNC | `Spindle_Temp_C` | **38 °C** | `cool_coeff = 0.045 × (áp tưới/20)`: 0.54/0.045 = +12°C → 38°C |
| Robot | `Motor_Temp_C` | **40 °C** | `cool_coeff = (9.25/10)² × 1.5 / 14 ≈ 0.091674`: cân bằng chính xác ở 40°C |
| AMR | `Battery_Temp_C` | **33.6 °C** | điểm cân bằng pin đầy tải khi di chuyển |
| AOI | `Optics_Cleanliness_Pct` | **99 %** | hồi phục bằng `ramp` về trần 99 (0.1%/s thường, 0.5%/s sau hiệu chuẩn) |

Khi **có sự cố**, heat_in nhảy vọt → điểm cân bằng mới cao/thấp hơn hẳn →
chỉ số **trồi/tụt sang mức mới**; áp suất/tải có thể đổi trong vài giây, nhiệt cần hàng chục giây đến vài phút. Lỗi nhẹ không nhất thiết vượt ngưỡng tĩnh.

Các mức cân bằng dưới đây ứng với thiết lập vận hành mặc định. CNC có mòn dao tích lũy nên tải và nhiệt cũng tăng nhẹ về lâu dài; thay dao hoặc thay đổi tốc độ/tải làm thay đổi điểm cân bằng. `dt` hiện được giới hạn trong 0.1–2.5 giây, nên không mô phỏng bù toàn bộ thời gian nếu chương trình bị treo lâu.

Mức danh nghĩa, đơn vị, nhiễu và ngưỡng cảnh báo được định nghĩa chung trong `machines/specifications.py`. Model dùng mức danh nghĩa này để khởi tạo; API cung cấp cùng định nghĩa cho Dashboard. Dashboard hiển thị đầy đủ các chỉ số trong bảng, giá trị cảm biến thực và mức tham chiếu. Dữ liệu chưa có hiển thị `—`, không thay bằng 0 hay 100.

### 1.1.1. Quy luật chuyển tiếp theo thời gian

Chỉ thay **giá trị đích** khi chọn/hủy lỗi, không gán trực tiếp chỉ số vật lý sang đích. Các đại lượng đáp ứng theo hai quy luật:

- Hội tụ bậc nhất: `x(t+dt) = target + (x(t) − target) × exp(−dt/τ)`. Sau `τ` giây đi được khoảng 63% quãng đường, sau `3τ` giây khoảng 95%. Công thức không nhảy về đích khi chu kỳ telemetry là 1 hoặc 2.5 giây.
- Giới hạn tốc độ: `x(t+dt) = x(t) + clamp(target − x(t), −rate×dt, +rate×dt)`. Chạm đích thì dừng, không vượt đích.

Các thông số chuyển tiếp cụ thể:

- CNC: tải `τ=5s`, rung `τ=4s`, RPM khi tăng/khôi phục `τ=3s`; áp làm mát mất **8 Bar/s**, phục hồi **3 Bar/s**. Nhiệt tuân theo sinh nhiệt và tỏa nhiệt, tích phân bậc nhất với `τ=1/cool_coeff` (khoảng 22.2s khi áp 20 Bar). Nhiệt chỉ tích phân khi trục chính quay trên 500 RPM; khi RPM ≤ 1000, mục tiêu rung hạ về 0.05 mm/s.
- Robot: dòng điện `τ=4s`; áp kẹp rò/khôi phục **1.2 Bar/s**; nhiệt có `τ≈10.9s` và vẫn phụ thuộc dòng điện thực đang biến đổi, cộng sinh nhiệt do lỗi.
- AMR: vận tốc `τ=4s`; LiDAR giảm/tăng **2%/s**; nhiệt pin `τ≈33.3s` khi di chuyển. Pin tiếp tục xả theo thời gian, không nhảy xuống mức thấp khi bật lỗi chai pin.
- AOI: độ sạch giảm **0.5%/s**, tự hồi phục **0.1%/s** sau hủy lỗi, hoặc **0.5%/s** sau lệnh hiệu chuẩn; LED giảm/tăng **350 Lux/s**; FRR hội tụ theo độ sạch/ánh sáng với `τ=4s`. Băng chuyền giảm/tăng **0.2 m/phút mỗi giây** (1.2→0 trong 6s), chỉ số chu kỳ giảm/tăng **0.7s mỗi giây**. Khi kẹt, bộ đếm bo dừng ngay dù tốc độ đang giảm dần.
- Máy ép: áp kẹp và áp phun `τ=5s`; lỗi nhiệt tăng **1.2°C/s** tới trần 280°C. Sau hủy lỗi, nhiệt hội tụ về setpoint với `τ=15s`, tốc độ hồi phục tối đa **1.2°C/s**. Áp phun đồng thời giảm theo nhiệt tăng qua `viscosity_offset = (220 − T)×0.35`. Áp phun chỉ được tạo khi áp kẹp khuôn >80 Bar; dưới mức đó (hoặc khi máy không chạy) áp phun giảm về 0.

Nhiễu chỉ cộng vào **giá trị xuất ra**, không tích lũy vào trạng thái vật lý. Vì vậy số đọc vẫn rung nhẹ quanh đường tăng/giảm; tính đơn điệu được kiểm tra trên trạng thái không nhiễu, không yêu cầu mọi mẫu có nhiễu phải cùng chiều.

### 1.2. Chọn lỗi thủ công trên từng máy (`BaseMachine`)

- Máy khởi động không có lỗi; không còn sinh lỗi tự động hoặc bộ đếm tần suất.
- Bấm thẻ máy để mở danh sách lỗi riêng của máy đó. Các lỗi đang bật được đánh dấu sẵn.
- Chọn hoặc bỏ chọn một hay nhiều lỗi, rồi bấm **Áp dụng**. **Bỏ chọn tất cả** rồi **Áp dụng** hủy toàn bộ lỗi trên máy; **Đóng** bỏ thay đổi chưa áp dụng.
- `GET /api/machines/{machine_id}/faults` trả `available_faults` và `active_faults`.
- `POST /api/machines/{machine_id}/faults` nhận `{"active_faults": ["FAULT_CODE", ...]}` để thay toàn bộ lựa chọn của máy đó. Danh sách rỗng hủy tất cả; mã lỗi không hợp lệ bị từ chối mà không thay đổi máy.
- Nhiều lỗi có thể cùng hoạt động; tác động cộng hoặc nhân theo công thức của mỗi máy (ví dụ mòn dao ×7×3 khi đồng thời hỏng bơm và mẻ dao).
- Hủy lỗi chỉ tắt cờ, không đặt lại nhiệt độ, mòn dao hay pin. Các chỉ số hồi phục theo động học hiện tại; muốn đặt lại mòn dao/pin cần lệnh bảo trì tương ứng.
- Có thể cấu hình lỗi khi máy đang dừng; tác động chỉ số vẫn phụ thuộc trạng thái vận hành. Dashboard kiểm chứng khởi chạy từ `main.py` dùng Agent để phân tích và đề xuất, không tự thực thi lệnh làm thay đổi setpoint hay xóa lỗi người dùng đang thử. Lệnh PLC do kỹ sư gửi vẫn có thể thực thi qua luồng duyệt hiện có.

### 1.3. Tách bạch dữ liệu

- Telemetry gửi AI (`TelemetryReceiver`) **không bao giờ** chứa `Simulated_Active_Faults`.
- Fault chỉ xuất hiện trong snapshot Dashboard (dữ liệu gốc của Tester) để đối chiếu.

---

## 2. Bảng 5 máy — chỉ số, mức bình thường, sự cố

### 2.1. MC-MILL-01 — Máy phay CNC (`CNC_MILLING`)

**Chỉ số khi bình thường (± noise):**

| Chỉ số | Mức bình thường | Noise |
|---|---|---|
| `Spindle_RotaryVelocity_RPM` | 12000 | ±15 |
| `Spindle_Load_Pct` | ~45 % | ±0.3 |
| `Spindle_Temp_C` | **38 °C** lúc mòn dao 12%; tăng nhẹ theo mòn dao | ±0.06 |
| `Vibration_RMS_mm_s` | ~1.2 mm/s | ±0.03 |
| `Coolant_Pressure_Bar` | 20 Bar | ±0.2 |
| `Tool_Wear_Pct` | 12 %, **trôi cố ý** +0.005 %/s | — |

**4 sự cố → tác động:**

| Sự cố (code → tiếng Việt) | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `SPINDLE_BEARING_LACK_OF_LUBE` — Thiếu dầu bôi trơn ổ bi trục chính | Load **+20**, sinh nhiệt thêm **+4.5°C/s**, Vib **+3.2** | Load ~65%, Temp đạt trần **140°C**; Vib từ 4.4 tăng tới ~14.9 do nhiệt trên 70°C | `REFILL_SPINDLE_LUBRICANT` |
| `COOLANT_PUMP_FAILURE` — Hỏng bơm làm mát | Áp tưới **−8 Bar/s về 0**, Temp **↑** (toả chỉ 30%), Mòn dao **×7** | Áp →0 (mất áp <5), Temp →~66°C, Wear tăng nhanh | `REPAIR_COOLANT_SYSTEM` |
| `TOOL_CHIPPING_OR_WEAR` — Dao phay mẻ/mòn | Load **+35**, Vib **+4.5**, Mòn dao **×3** | Load →80%, Vib →5.7 (vượt 4.5) | `REPLACE_TOOL` (reset mòn 0%) |
| `GUIDEWAY_LUBRICATION_ISSUE` — Thiếu dầu trượt | Load **+8**, Vib **+1.5** | Biểu hiện nhẹ | `LUBRICATE_GUIDEWAYS` |

**Ngưỡng cảnh báo:** Temp >75 (cảnh báo), >90 (nghiêm trọng); Vib >4.5, >7.1; Load >120; Áp tưới <5.

### 2.2. MC-ROBOT-01 — Cánh tay Robot (`ROBOT_ARM`)

**Chỉ số khi bình thường:**

| Chỉ số | Mức bình thường | Noise |
|---|---|---|
| `Joint_3_Current_A` | ~9.25 A | ±0.05 |
| `Motor_Temp_C` | **40 °C** (cân bằng) | ±0.04 |
| `Gripper_Pressure_Bar` | 6.0 Bar | ±0.08 |
| `Payload_Kg` | 3.5 kg | — |

**3 sự cố:**

| Sự cố | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `GEARBOX_LACK_OF_GREASE` — Khô mỡ hộp số giảm tốc | Dòng **+8.5A**, sinh nhiệt thêm **+4.0°C/s** | Dòng →17.75A (>16.5 quá dòng), Temp →**~121°C** (>80) | `REFILL_GEARBOX_GREASE` |
| `GRIPPER_PNEUMATIC_LEAK` — Rò khí nén tay gắp | Áp kẹp **−1.2 Bar/s** | Áp →0.8 Bar (<3.5 mất áp) | `REPAIR_PNEUMATIC_SYSTEM` |
| `PAYLOAD_OVERLOAD` — Quá tải trọng gắp | Tải gắp **3.5→~12 kg** (dòng theo tải **↑~5.5A**), sinh nhiệt thêm **+1.5°C/s**, áp kẹp **↑~8 Bar** | Dòng →**~14.7A** (>12.5), Temp →~78°C, Tải **3.5→~12 kg**, Áp kẹp **6.0→~8 Bar** | `RESET_PAYLOAD` (về 3.5kg) |

**Ngưỡng:** Dòng >12.5 (cảnh báo), >16.5 (nghiêm trọng); Temp >65, >80; Áp <3.5.

Lỗi `PAYLOAD_OVERLOAD` mô phỏng gắp phôi vượt định mức nên cả **tải trọng gắp** lẫn **áp kẹp gắp** đều tăng (3.5→~12 kg, 6.0→~8 Bar); dòng servo suy ra từ khối lượng đặt nên đạt ~14.7A. Khi hủy lỗi, tải trọng và áp kẹp **hồi về mức danh nghĩa theo động học** (không gán tức thời); `RESET_PAYLOAD` đưa tải trọng về đúng 3.5 kg.

### 2.3. MC-AMR-01 — Xe tự hành (`AMR_VEHICLE`)

**Chỉ số khi bình thường:**

| Chỉ số | Mức bình thường | Noise |
|---|---|---|
| `Current_Velocity_m_s` | 1.2 m/s | ±0.02 |
| `Battery_Pct` | 85 %, **trôi cố ý** −2.7333 %/phút (~2.7) khi di chuyển ở tải 25kg | ±0.05 |
| `Battery_Temp_C` | **33.6 °C** (cân bằng) | ±0.1 |
| `Lidar_Confidence_Pct` | 99.5 % | ±0.2 |

**3 sự cố:**

| Sự cố | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `BATTERY_CELL_DEGRADATION` — Pin chai lão hóa | Xả pin **×4**, Nhiệt pin **↑** | Pin tụt ~11%/phút, Temp →**~56°C** (>55 nguy hiểm) | `REPLACE_BATTERY_MODULE` (nạp lại 95%) |
| `LIDAR_OPTICAL_DIRT` — Bụi bẩn ống kính LiDAR | Độ tin cậy **−2 %/s** | Lidar →40%, vượt <65 (mất định vị) | `CLEAN_LIDAR_OPTICS` |
| `WHEEL_MOTOR_RESISTANCE` — Kẹt cơ cấu bánh xe | Tốc độ **×0.5**, Xả pin **×1.8** | Vận tốc →0.6 m/s, pin hao nhanh | `SERVICE_DRIVE_MOTOR` |

**Ngưỡng:** Pin <25 (cảnh báo), <15 (nghiêm trọng); Nhiệt pin >55; Lidar <65.

### 2.4. MC-AOI-01 — Máy kiểm tra quang (`AOI_INSPECTION`)

**Chỉ số khi bình thường:**

| Chỉ số | Mức bình thường | Noise |
|---|---|---|
| `False_Reject_Rate_Pct` | 0.6 % | ±0.04 |
| `Optics_Cleanliness_Pct` | 99 % (cân bằng trần) | ±0.1 |
| `Illumination_Intensity_Lux` | 18500 Lux | ±15 |
| `Conveyor_Speed_m_min` | 1.2 m/phút | ±0.02 |

**3 sự cố (có chuỗi phản ứng):**

| Sự cố | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `OPTICAL_LENS_CONTAMINATION` — Bẩn lăng kính quang học | Độ sạch **−0.5 %/s**, FRR **↑ theo độ bẩn** | Sạch →30%, FRR →**~11%** (nghiêm trọng >4) | `RECALIBRATE_OPTICS` (hồi phục dần về 99%) |
| `LED_DRIVER_DEGRADATION` — Nguồn LED suy hao | Sáng **−350 Lux/s**, FRR **↑** | Sáng →9000 (<14000), FRR →~8% | `REPLACE_LED_MODULE` |
| `SMEMA_CONVEYOR_JAM` — Kẹt bảng mạch trên băng chuyền | Tốc độ băng →**0** | Vận tốc 0, chu kỳ 0 | `CLEAR_CONVEYOR_JAM` |

**Chuỗi phản ứng FRR:** `FRR = 0.6 + max(0, (88 − độ sạch)×0.18) + |18500 − sáng|/500×0.4`
— kính bẩn hoặc thiếu sáng đều đẩy tỷ lệ từ chối giả lên.

**Ngưỡng:** FRR >2 (cảnh báo), >4 (nghiêm trọng); Độ sạch <75; Sáng <14000.

### 2.5. MC-INJ-01 — Máy ép phun (`INJECTION_MOLDING`)

**Chỉ số khi bình thường:**

| Chỉ số | Mức bình thường | Noise |
|---|---|---|
| `Nozzle_Temp_Zone1` | 220 °C | ±0.12 |
| `Clamping_Pressure_Bar` | 140 Bar | ±0.5 |
| `Injection_Pressure_Bar` | ~95 Bar | ±0.5 |

**3 sự cố:**

| Sự cố | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `HEATER_BAND_RUNAWAY` — Rơ-le vòng nhiệt kẹt | Nhiệt đầu phun **+1.2°C/s** | →280°C (vượt 245 nguy hiểm); áp phun **↓** (nhựa loãng) | `SERVICE_HEATER_SSR` |
| `HYDRAULIC_PROPORTIONAL_VALVE_LEAK` — Rò van tỉ lệ thủy lực | Áp kẹp khuôn **140 → 102 Bar** | <115 (mất áp kẹp) | `REPAIR_HYDRAULIC_VALVE` |
| `NOZZLE_CLOGGING` — Nghẹt nhựa nòng phun | Áp phun **95 → 165 Bar** | >145 (quá áp phun) | `PURGE_BARREL` (đùn xả) |

**Ngưỡng:** Nhiệt >245 (nghiêm trọng), <195 (cảnh báo); Áp kẹp <115; Áp phun >145.

Lệnh `ADJUST_TEMPERATURE` chỉ nhận setpoint **180–245°C**. Giá trị ngoài miền, `NaN` hoặc vô hạn bị từ chối. Nếu phát hiện trạng thái cũ bị hỏng (setpoint ngoài miền hoặc nhiệt thực thấp hơn nhiệt môi trường), model tự đặt lại setpoint và nhiệt đầu phun về **220°C** trước khi tiếp tục mô phỏng.

---

## 3. Hành vi bình thường — tóm tắt "dao động quanh mức"

Sau khi hiệu chỉnh điểm cân bằng:

```
KHÔNG LỖI:   ───── ~~~~ ───── ~~~~     dao động ±noise quanh mức đặt, KHÔNG TRÔI
CÓ LỖI:      ─────╲                       trồi/tụt sang điểm cân bằng mới
                    ╲_______________      (vượt ngưỡng cảnh báo)
SỬA LỖI:                 ╲___________/    trượt về mức cũ
```

**Trôi CÓ CHỦ ĐÍCH (không phải bug):**

| Chỉ số | Tốc độ | Lý do |
|---|---|---|
| `Tool_Wear_Pct` (CNC) | +0.005 %/s (~18%/giờ) | Mòn dao tích lũy vật lý |
| `Battery_Pct` (AMR) | −2.7333 %/phút (~2.7) ở tải 25kg | Xả pin khi vận hành (sạc lại khi `CHARGING`) |
| `boards_inspected_total` (AOI) | +1 board/s ở tốc độ mặc định, dừng khi kẹt/dừng máy | Tích lũy theo `dt`, không theo số lần gọi |
| `boards_flagged_defect` (AOI) | Tăng ngẫu nhiên với xác suất FRR/100 cho mỗi bo kiểm tra | Không tăng cố định mỗi giây; dừng khi không có bo đi qua |

Sửa lỗi sẽ đưa các chỉ số về mức phù hợp với trạng thái điều khiển hiện tại. Hiệu chuẩn quang học, thay LED, làm sạch LiDAR chỉ thay điều kiện/đích phục hồi; số đo tăng/giảm dần. Thay vật tư là trường hợp riêng: thay dao mới đặt mòn về 0%, thay cụm pin mới đặt mức pin 95%. `PURGE_BARREL` chuyển máy ép sang `PURGING`, cần `RESUME` để chạy lại.

Các ngưỡng tĩnh trong mục 2 được dùng thống nhất cho màu cảnh báo Dashboard và Edge (`MACHINE_THRESHOLDS`, lấy từ `machines/specifications.py`). Edge còn có ROC để phát hiện xu hướng tăng nhanh trước khi vượt ngưỡng tĩnh. Kẹt băng AOI và kẹt bánh AMR thể hiện trên tốc độ và danh sách lỗi thủ công; hiện chưa có ngưỡng cảnh báo tốc độ riêng.

---

## 4. Ánh xạ tiếng Việt trên Dashboard (`dashboard/index.html`)

Backend trả về code; **lớp hiển thị** dịch sang tiếng Việt qua 3 bảng tra cứu:

- `MACHINE_TYPE_VI` — tên máy: `CNC_MILLING → Máy phay CNC`, ...
- `STATE_VI` — trạng thái: `RUNNING → ĐANG CHẠY`, `EMERGENCY_STOP → NGẮT KHẨN CẤP`, ...
- `FAULT_VI` — 16 tên lỗi: `SPINDLE_BEARING_LACK_OF_LUBE → Thiếu dầu bôi trơn ổ bi trục chính`, ...

Giá trị số + unit giữ nguyên; **không đổi dữ liệu backend**, chỉ đổi lớp dịch hiển thị.

---

## 5. Tham chiếu code

| Thành phần | File |
|---|---|
| Động học, noise, cân bằng | `machines/*.py` → `generate_telemetry()` |
| Chọn/hủy nhiều lỗi thủ công | `machines/base_machine.py` → `set_active_faults()`, `get_fault_config()` |
| Ngưỡng tĩnh + ROC | `iot/telemetry_receiver.py` → `MACHINE_THRESHOLDS` |
| Lệnh PLC & interlock an toàn | `iot/actuator_dispatcher.py` |
| Stream dữ liệu + API chọn lỗi | `dashboard/server.py`, `dashboard/state_store.py` |
| Hiển thị tiếng Việt | `dashboard/index.html` |

