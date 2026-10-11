# Quy trình bảo trì (SOP) – 5 máy mô phỏng nhà máy DENSO

Tài liệu dùng cho kỹ sư bảo trì và cho agent giám sát khi chẩn đoán cảnh báo. Mỗi mục nêu: triệu chứng
(chỉ số và chiều lệch), cách phân biệt với lỗi gần giống, nguyên nhân gốc, lệnh sửa, điều kiện khởi động lại
và cách kiểm chứng. Tên lệnh viết đúng như máy khai báo.

## 0. Quy tắc chung (áp dụng cho mọi máy)

**Quy trình sửa chuẩn:**

1. `SAFE_STOP` – dừng máy có kiểm soát. Tốc độ, tải, dòng điện về 0; nhiệt độ nguội dần, không tụt ngay.
2. `LOCKOUT` – cô lập năng lượng (khoá an toàn LOTO). Chỉ thực hiện khi các bộ phận chuyển động đã đứng yên.
3. Lệnh sửa (bảng bên dưới) – chỉ chạy khi máy ở trạng thái khoá an toàn, mất một khoảng thời gian, và chỉ sửa
   đúng bộ phận đó. Sửa sai bộ phận thì lỗi vẫn còn.
4. `UNLOCK` – gỡ khoá an toàn, máy về trạng thái đã dừng.
5. Kỹ sư kiểm tra máy rồi mới duyệt `START`. Máy khởi động có thời gian; liên động có thể từ chối khởi động.
6. Theo dõi khoảng 2 phút sau khi chạy lại: không có cảnh báo là sửa thành công; cảnh báo quay lại là sửa chưa
   đúng nguyên nhân, cần chẩn đoán lại và không lặp lại lệnh vừa thử.

**Nguyên tắc:**

- Sửa chữa không làm số đo về bình thường ngay. Nhiệt độ, áp suất, rung động hồi phục dần theo vật lý sau khi
  máy chạy lại. Một máy đã dừng có áp suất bằng 0 là bình thường, không phải lỗi.
- Dừng máy làm triệu chứng của lỗi biến mất (bộ phận hỏng không còn hoạt động) nhưng **không sửa được lỗi**;
  chạy lại mà chưa sửa thì triệu chứng quay lại.
- Sau dừng khẩn cấp (`EMERGENCY_STOP`) phải `RESET_ESTOP` trước mọi thao tác khác.
- Lệnh vận hành tạm thời (giảm tốc, tăng tưới nguội, tạm dừng `HOLD`) chỉ để giảm nhẹ trong lúc chờ sửa,
  không thay thế lệnh sửa.

## 1. MC-MILL-01 – Máy phay CNC (CNC_MILLING)

Mức bình thường: tốc độ trục 12000 RPM, tải 45%, nhiệt trục chính 38°C (tối đa 75, nguy hiểm 90),
rung 1.2 mm/s (tối đa 4.5, nguy hiểm 7.1), áp tưới nguội 20 Bar (tối thiểu 5).
Liên động khởi động: nhiệt trục chính phải ≤ 90°C.

### SOP-CNC-01 – Hỏng bơm tưới nguội

- **Triệu chứng:** áp suất tưới nguội tụt về 0 Bar (dưới 5 Bar); nhiệt trục chính tăng vừa phải lên khoảng 60–70°C;
  độ mòn dao tăng nhanh gấp 7 lần.
- **Phân biệt:** tải và rung gần bình thường. Nếu áp tưới nguội vẫn 20 Bar mà nhiệt tăng cao thì không phải bơm.
- **Nguyên nhân gốc:** bơm tưới nguội hỏng (COOLANT_PUMP_FAILURE).
- **Lệnh sửa:** `REPAIR_COOLANT_SYSTEM` (khoảng 60 s). `COOLANT_BOOST` không có tác dụng khi bơm đã hỏng.
- **Kiểm chứng:** sau khi chạy lại, áp suất dựng lại dần về 20 Bar, nhiệt về khoảng 38°C.

### SOP-CNC-02 – Thiếu mỡ bôi trơn ổ bi trục chính

- **Triệu chứng:** nhiệt trục chính tăng cao vượt 75°C, có thể tới 140°C; rung tăng theo nhiệt (vượt 7.1 mm/s
  khi rất nóng); tải tăng khoảng +20% (lên khoảng 65%).
- **Phân biệt:** áp tưới nguội vẫn bình thường (20 Bar). Đây là điểm khác với hỏng bơm tưới nguội.
- **Nguyên nhân gốc:** ổ bi trục chính thiếu mỡ (SPINDLE_BEARING_LACK_OF_LUBE).
- **Lệnh sửa:** `REFILL_SPINDLE_LUBRICANT` (khoảng 40 s).
- **Khởi động lại:** chờ nhiệt trục chính ≤ 90°C (liên động sẽ từ chối nếu còn nóng hơn).

### SOP-CNC-03 – Dao phay mẻ hoặc mòn

- **Triệu chứng:** tải tăng mạnh lên khoảng 75–90%; rung 4.5–7.1 mm/s; mòn dao tăng nhanh gấp 3 lần.
- **Phân biệt:** nhiệt chỉ tăng nhẹ, áp tưới nguội bình thường; rung cao ngay cả khi nhiệt chưa cao.
- **Nguyên nhân gốc:** lưỡi dao mẻ hoặc mòn (TOOL_CHIPPING_OR_WEAR).
- **Lệnh sửa:** `REPLACE_TOOL` (khoảng 30 s). Dao mới có độ mòn 0%.

### SOP-CNC-04 – Thiếu dầu băng trượt

- **Triệu chứng:** tải tăng nhẹ lên khoảng 50–58%; rung tăng nhẹ nhưng dưới 4.5 mm/s.
- **Phân biệt:** biểu hiện nhẹ, không quá nhiệt, áp tưới nguội bình thường.
- **Nguyên nhân gốc:** băng trượt các trục thiếu dầu (GUIDEWAY_LUBRICATION_ISSUE).
- **Lệnh sửa:** `LUBRICATE_GUIDEWAYS` (khoảng 30 s).

## 2. MC-ROBOT-01 – Cánh tay robot (ROBOT_ARM)

Mức bình thường: dòng khớp 3 là 9.25 A (tối đa 12.5, nguy hiểm 16.5), nhiệt động cơ 40°C (tối đa 65, nguy hiểm 80),
áp kẹp gắp 6 Bar (tối thiểu 3.5), tải gắp 3.5 kg.
Liên động khởi động: nhiệt động cơ khớp phải ≤ 80°C.

### SOP-ROB-01 – Khô mỡ hộp số giảm tốc khớp 3

- **Triệu chứng:** dòng khớp 3 tăng lên khoảng 17–18 A (vượt 16.5 A); nhiệt động cơ vượt 80°C, có thể tới 120°C.
- **Phân biệt:** tải gắp vẫn 3.5 kg và áp kẹp vẫn 6 Bar. Nếu tải gắp tăng lên khoảng 12 kg thì là quá tải phôi.
- **Nguyên nhân gốc:** hộp số khô mỡ (GEARBOX_LACK_OF_GREASE).
- **Lệnh sửa:** `REFILL_GEARBOX_GREASE` (khoảng 40 s).
- **Khởi động lại:** chờ nhiệt động cơ ≤ 80°C.

### SOP-ROB-02 – Rò khí nén tay gắp

- **Triệu chứng:** áp kẹp gắp tụt xuống khoảng 0.8 Bar (dưới 3.5 Bar).
- **Phân biệt:** dòng điện và nhiệt động cơ bình thường.
- **Nguyên nhân gốc:** gioăng hoặc ống khí nén tay gắp bị rò (GRIPPER_PNEUMATIC_LEAK).
- **Lệnh sửa:** `REPAIR_PNEUMATIC_SYSTEM` (khoảng 30 s).
- **Ghi chú:** khi khoá an toàn, khí nén được xả về 0 Bar; áp dựng lại khi máy khởi động.

### SOP-ROB-03 – Quá tải phôi gắp

- **Triệu chứng:** tải gắp tăng lên khoảng 12 kg; dòng khớp 3 khoảng 14.7 A (vượt 12.5 A); nhiệt khoảng 78°C;
  áp kẹp tăng lên khoảng 8 Bar.
- **Phân biệt:** tải gắp cao là dấu hiệu riêng của lỗi này.
- **Nguyên nhân gốc:** phôi nặng vượt định mức (PAYLOAD_OVERLOAD).
- **Lệnh sửa:** `RESET_PAYLOAD` (khoảng 20 s): gỡ phôi quá tải, nạp phôi đúng định mức 3.5 kg.

## 3. MC-AMR-01 – Xe tự hành (AMR_VEHICLE)

Mức bình thường: vận tốc 1.2 m/s, pin 85% (tối thiểu 25, nguy hiểm 15), nhiệt pin 33.6°C (tối đa 55),
độ tin cậy LiDAR 99.5% (tối thiểu 65). Pin giảm dần khi xe chạy là bình thường.
Liên động khởi động: pin ≥ 15% và nhiệt pin ≤ 55°C.

### SOP-AMR-01 – Pin chai (suy giảm cell)

- **Triệu chứng:** nhiệt pin tăng vượt 55°C; pin tụt nhanh gấp khoảng 4 lần bình thường (khoảng 11%/phút).
- **Phân biệt:** pin thấp mà nhiệt pin bình thường (khoảng 33°C) là **hao pin do vận hành**, không phải pin chai:
  xử lý bằng `RETURN_TO_CHARGER`, không cần sửa. Sạc không sửa được pin chai.
- **Nguyên nhân gốc:** cell pin suy giảm, nội trở cao (BATTERY_CELL_DEGRADATION).
- **Lệnh sửa:** `REPLACE_BATTERY_MODULE` (khoảng 60 s). Module mới đã sạc sẵn khoảng 95%.

### SOP-AMR-02 – Bụi bẩn ống kính LiDAR

- **Triệu chứng:** độ tin cậy LiDAR tụt dần về khoảng 40% (dưới 65%).
- **Phân biệt:** vận tốc và nhiệt pin bình thường.
- **Nguyên nhân gốc:** ống kính LiDAR bám bụi (LIDAR_OPTICAL_DIRT).
- **Lệnh sửa:** `CLEAN_LIDAR_OPTICS` (khoảng 20 s).

### SOP-AMR-03 – Kẹt cơ cấu bánh xe

- **Triệu chứng:** vận tốc chỉ còn khoảng 0.6 m/s (một nửa); pin hao nhanh gấp 1.8 lần.
- **Phân biệt:** nhiệt pin tăng nhẹ, LiDAR bình thường.
- **Nguyên nhân gốc:** động cơ hoặc cơ cấu bánh xe bị kẹt (WHEEL_MOTOR_RESISTANCE).
- **Lệnh sửa:** `SERVICE_DRIVE_MOTOR` (khoảng 45 s).

## 4. MC-AOI-01 – Máy kiểm tra quang AOI (AOI_INSPECTION)

Mức bình thường: tỉ lệ từ chối giả 0.6% (tối đa 2, nguy hiểm 4), độ sạch lăng kính 99% (tối thiểu 75),
độ sáng 18500 Lux (tối thiểu 14000), băng tải 1.2 m/phút.

### SOP-AOI-01 – Bẩn lăng kính quang học

- **Triệu chứng:** độ sạch lăng kính giảm dần về khoảng 30% (dưới 75%); tỉ lệ từ chối giả tăng mạnh (trên 4%).
- **Phân biệt:** độ sáng vẫn khoảng 18500 Lux.
- **Nguyên nhân gốc:** lăng kính bám bẩn (OPTICAL_LENS_CONTAMINATION).
- **Lệnh sửa:** `RECALIBRATE_OPTICS` (khoảng 30 s). Độ sạch đo được hồi phục dần về 99%.

### SOP-AOI-02 – Suy hao nguồn đèn LED

- **Triệu chứng:** độ sáng giảm về khoảng 9000 Lux (dưới 14000); tỉ lệ từ chối giả tăng (khoảng 8%).
- **Phân biệt:** độ sạch lăng kính vẫn khoảng 99%.
- **Nguyên nhân gốc:** driver đèn LED suy hao (LED_DRIVER_DEGRADATION).
- **Lệnh sửa:** `REPLACE_LED_MODULE` (khoảng 40 s).

### SOP-AOI-03 – Kẹt bảng mạch trên băng tải

- **Triệu chứng:** tốc độ băng tải về 0; số bảng kiểm tra đứng yên.
- **Phân biệt:** quang học bình thường; máy vẫn ở trạng thái chạy nhưng không có bảng đi qua.
- **Nguyên nhân gốc:** bảng mạch kẹt trên băng tải SMEMA (SMEMA_CONVEYOR_JAM).
- **Lệnh sửa:** `CLEAR_CONVEYOR_JAM` (khoảng 20 s).

## 5. MC-INJ-01 – Máy ép phun (INJECTION_MOLDING)

Mức bình thường: nhiệt đầu phun 220°C (tối thiểu 195, nguy hiểm 245), áp kẹp khuôn 140 Bar (tối thiểu 115),
áp phun 95 Bar (tối đa 145). Khi dừng máy (`SAFE_STOP`) gia nhiệt vẫn bật; khoá an toàn thì ngắt nhiệt.
Liên động khởi động: đầu phun ≤ 245°C; máy chỉ vào chạy khi đầu phun đã nóng ≥ 195°C (khởi động có thể mất vài phút).

### SOP-INJ-01 – Rơ-le vòng gia nhiệt kẹt (quá nhiệt đầu phun)

- **Triệu chứng:** nhiệt đầu phun tăng liên tục khoảng 1.2°C/s, vượt 245°C, tới 280°C; áp phun giảm (nhựa loãng).
- **Phân biệt:** áp kẹp khuôn bình thường. Dừng máy chưa đủ vì gia nhiệt vẫn bật: phải khoá an toàn để ngắt nhiệt.
- **Nguyên nhân gốc:** rơ-le bán dẫn SSR của vòng nhiệt bị kẹt (HEATER_BAND_RUNAWAY).
- **Lệnh sửa:** `SERVICE_HEATER_SSR` (khoảng 40 s).
- **Khởi động lại:** chờ đầu phun ≤ 245°C.

### SOP-INJ-02 – Rò van tỉ lệ thủy lực kẹp khuôn

- **Triệu chứng:** áp kẹp khuôn tụt từ 140 xuống khoảng 102 Bar (dưới 115 Bar).
- **Phân biệt:** nhiệt đầu phun và áp phun bình thường.
- **Nguyên nhân gốc:** phớt van tỉ lệ thủy lực bị rò (HYDRAULIC_PROPORTIONAL_VALVE_LEAK).
- **Lệnh sửa:** `REPAIR_HYDRAULIC_VALVE` (khoảng 60 s).

### SOP-INJ-03 – Nghẹt nhựa nòng phun

- **Triệu chứng:** áp phun tăng từ 95 lên khoảng 165 Bar (vượt 145 Bar).
- **Phân biệt:** nhiệt đầu phun bình thường (khoảng 220°C). Áp phun cao kèm nhiệt thấp có thể chỉ là nhựa nguội.
- **Nguyên nhân gốc:** nhựa cặn nghẹt nòng phun (NOZZLE_CLOGGING).
- **Lệnh sửa:** `PURGE_BARREL` (khoảng 30 s). Khác các lệnh sửa khác: chỉ cần `SAFE_STOP`, **không khoá an toàn**,
  vì đùn xả cần nòng còn nóng ≥ 195°C.
