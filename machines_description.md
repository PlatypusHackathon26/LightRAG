# ĐẶC THẢU MÔ PHỎNG 5 MÁY (machines_description.md)

> Tài liệu mô tả hành vi mô phỏng của 5 thiết bị trong dự án **Long-agent / Denso Hackathon 2026**.
> Đối tượng đọc: kỹ sư viết test, người vận hành demo, và bất kỳ ai cần hiểu vì sao
> chỉ số biến đổi trên Dashboard.

---

## 1. Tổng quan kiến trúc mô phỏng

### 1.1. Ba lớp trong `generate_telemetry()` (gọi mỗi 1 giây/máy)

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
| Robot | `Motor_Temp_C` | **40 °C** | `heat_out = (T−26) × 0.09`: 1.28/0.09 ≈ +14°C → 40°C |
| AMR | `Battery_Temp_C` | **33.6 °C** | điểm cân bằng pin đầy tải khi di chuyển |
| AOI | `Optics_Cleanliness_Pct` | **99 %** | trần hồi phục `min(99, +0.1·dt)` |

Khi **có sự cố**, heat_in nhảy vọt → điểm cân bằng mới cao/thấp hơn hẳn →
chỉ số **trồi/tụt sang mức mới** trong vài giây → vượt ngưỡng cảnh báo.

### 1.2. Cơ chế sinh lỗi tự động (`BaseMachine`)

- `fault_interval_sec` (mặc định 30 giây, chỉnh 1–300s từ Web UI qua `POST /api/fault/interval`)
- Kiểm tra mỗi chu kỳ: `elapsed ≥ fault_interval` **VÀ** máy chưa có lỗi nào **VÀ** `fault_auto_enabled`
  → chọn ngẫu nhiên 1 lỗi trong danh mục, bật cờ.
- `last_fault_time` reset khi: lỗi mới sinh, lỗi được sửa (`clear_fault`), hoặc **đổi tần suất**.
- Lỗi chỉ sinh khi trạng thái `RUNNING` (4 máy) hoặc `NAVIGATING` (AMR).
- Khoảng cách thực tế giữa 2 lỗi = **interval + thời gian chờ sửa lỗi**.

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
| `Spindle_Temp_C` | **38 °C** (cân bằng, không trôi) | ±0.06 |
| `Vibration_RMS_mm_s` | ~1.2 mm/s | ±0.03 |
| `Coolant_Pressure_Bar` | 20 Bar | ±0.2 |
| `Tool_Wear_Pct` | 12 %, **trôi cố ý** +0.005 %/s | — |

**4 sự cố → tác động:**

| Sự cố (code → tiếng Việt) | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `SPINDLE_BEARING_LACK_OF_LUBE` — Thiếu dầu bôi trơn ổ bi trục chính | Load **+20**, Temp **+4.5°C/s**, Vib **+3.2** | Load →65%, Temp →**138°C** (vượt 75 cảnh báo, 90 nghiêm trọng), Vib →4.4+ | `REFILL_SPINDLE_LUBRICANT` |
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
| `GEARBOX_LACK_OF_GREASE` — Khô mỡ hộp số giảm tốc | Dòng **+8.5A**, Nhiệt **+4.0°C/s** | Dòng →17.75A (>16.5 quá dòng), Temp →**~123°C** (>80) | `REFILL_GEARBOX_GREASE` |
| `GRIPPER_PNEUMATIC_LEAK` — Rò khí nén tay gắp | Áp kẹp **−1.2 Bar/s** | Áp →0.8 Bar (<3.5 mất áp) | `REPAIR_PNEUMATIC_SYSTEM` |
| `PAYLOAD_OVERLOAD` — Quá tải trọng gắp | Dòng **+5.5A**, Nhiệt **+1.5°C/s** | Dòng →14.75A (>12.5), Temp →~79°C | `RESET_PAYLOAD` (về 3.5kg) |

**Ngưỡng:** Dòng >12.5 (cảnh báo), >16.5 (nghiêm trọng); Temp >65, >80; Áp <3.5.

### 2.3. MC-AMR-01 — Xe tự hành (`AMR_VEHICLE`)

**Chỉ số khi bình thường:**

| Chỉ số | Mức bình thường | Noise |
|---|---|---|
| `Current_Velocity_m_s` | 1.2 m/s | ±0.02 |
| `Battery_Pct` | 85 %, **trôi cố ý** −2.7 %/phút khi di chuyển | ±0.05 |
| `Battery_Temp_C` | **33.6 °C** (cân bằng) | ±0.1 |
| `Lidar_Confidence_Pct` | 99.5 % | ±0.2 |

**3 sự cố:**

| Sự cố | Chỉ số bị tác động | Đường đi | Lệnh PLC sửa |
|---|---|---|---|
| `BATTERY_CELL_DEGRADATION` — Pin chai lão hóa | Xả pin **×4**, Nhiệt pin **↑** | Pin tụt ~11%/phút, Temp →**~56°C** (>55 nguy hiểm) | `REPLACE_BATTERY_MODULE` (nạp lại 95%) |
| `LIDAR_OPTICAL_DIRT` — Bụi bẩn ống kính LiDAR | Độ tin cậy **−2 %/s** | Lidar →40%, vượt <65 (mất định vị) | `CLEAN_LIDAR_OPTICS` |
| `WHEEL_MOTOR_RESISTANCE` — Kẹt cơ cấu bánh xe | Tốc độ **×0.5**, Xả pin **×1.8** | Vận tốc →0.6 m/s, pin hao nhanh | `SERVICE_DRIVE_MOTOR` |

**Ngưỡng:** Pin <25 (cảnh báo), <15 (nghiêm trọng); Nhiệt pin >55; Lidar <65.

|---|---|---|---|
| `SPINDLE_BEARING_LACK_OF_LUBE` — Thiếu dầu bôi trơn ổ bi trục chính | Load **+20**, Temp **+4.5°C/s**, Vib **+3.2** | Load →65%, Temp →**138°C** (vượt 75 cảnh báo, 90 nghiêm trọng), Vib →4.4+ | `REFILL_SPINDLE_LUBRICANT` |
| `COOLANT_PUMP_FAILURE` — Hỏng bơm làm mát | Áp tưới **−8 Bar/s về 0**, Temp **↑** (toả chỉ 30%), Mòn dao **×7** | Áp →0 (mất áp <5), Temp →~66°C, Wear tăng nhanh | `REPAIR_COOLANT_SYSTEM` |
| `TOOL_CHIPPING_OR_WEAR` — Dao phay mẻ/mòn | Load **+35**, Vib **+4.5**, Mòn dao **×3** | Load →80%, Vib →5.7 (vượt 4.5) | `REPLACE_TOOL` (reset mòn 0%) |
| `GUIDEWAY_LUBRICATION_ISSUE` — Thiếu dầu trượt | Load **+8**, Vib **+1.5** | Biểu hiện nhẹ | `LUBRICATE_GUIDEWAYS` |
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
| `OPTICAL_LENS_CONTAMINATION` — Bẩn lăng kính quang học | Độ sạch **−0.5 %/s**, FRR **↑ theo độ bẩn** | Sạch →30%, FRR →**~11%** (nghiêm trọng >4) | `RECALIBRATE_OPTICS` (reset 99.2%) |
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
| `Battery_Pct` (AMR) | −2.7 %/phút khi di chuyển | Xả pin khi vận hành (sạc lại khi `CHARGING`) |
| `boards_inspected_total`, `boards_flagged_defect` (AOI) | +1 board/s | Bộ đếm tích lũy |

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
| Sinh lỗi theo tần suất | `machines/base_machine.py` → `maybe_trigger_random_fault()` |
| Ngưỡng tĩnh + ROC | `iot/telemetry_receiver.py` → `MACHINE_THRESHOLDS` |
| Lệnh PLC & interlock an toàn | `iot/actuator_dispatcher.py` |
| Stream dữ liệu + API tần suất | `dashboard/server.py`, `dashboard/state_store.py` |
| Hiển thị tiếng Việt | `dashboard/index.html` |

