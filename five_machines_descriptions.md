## 1. Máy phay CNC độ chính xác cao (Gia công thân vỏ / bơm nhiên liệu / kim phun)

* **Mã máy DENSO / Model phổ biến:** `DMG MORI NVX 5080` (hoặc `Makino a51nx`, `Mazak VCN`). Mã trạm nội bộ: `MC-MILL-01` (Machining Center 01).
* **Tên tiếng Anh:** High-Precision CNC Vertical Machining Center.
* **Tên tiếng Việt:** Máy phay trung tâm CNC đứng độ chính xác cao.
* **Vai trò:** Cắt gọt kim loại, phay chi tiết cơ khí chính xác như thân kim phun áp suất cao, vỏ bơm cao áp diesel/xăng.
* **Vấn đề máy có thể gặp phải:**
  * Mòn, mẻ hoặc gãy dao cắt (*Tool wear / Tool breakage*).
  * Nhiệt độ trục chính (*Spindle*) tăng vọt do hỏng vòng bi hoặc thiếu dầu bôi trơn.
  * Tắc vòi làm mát gây biến dạng nhiệt phôi.
* **Dữ liệu log/cảm biến cấp cho IoT (qua chuẩn MTConnect / OPC-UA):**
  * `Spindle_RPM` (vòng/phút), `Spindle_Load_%` (tải trục chính), `Spindle_Temp_C` (nhiệt độ).
  * `Vibration_RMS_X/Y/Z` (gia tốc rung động 3 trục).
  * `Coolant_Pressure_Bar` (áp suất dung dịch làm mát), `Tool_Life_Remaining_Minutes` (thời lượng dao).
* **Thao tác Agent có thể thực thi:**
  * **Thao tác can thiệp PLC:** Phát lệnh `FEED_HOLD` (tạm dừng tiến dao) hoặc giảm `Feed_Rate_Override` về 50% để tránh gãy dao văng phôi khi phát hiện tải tăng đột biến.
  * **Thao tác hệ thống:** Gọi API tạo Ticket bảo trì khẩn cấp vào hệ thống CMMS, gửi thông báo cảnh báo qua Telegram/Zalo cho kỹ thuật viên khu vực `MC-MILL`.
  * **Thao tác RAG/Knowledge:** Tự động tra cứu manual của dao, trích xuất quy trình "Thay đài dao T04 và offset lại toạ độ" đính kèm vào thông báo.

---

## 2. Cánh tay Robot 6 trục (Gắp thả, lắp ráp linh kiện vi mô)

* **Mã máy DENSO:** `DENSO ROBOTICS VS-068` (Dòng robot công nghiệp 6 trục chính chủ do DENSO Wave sản xuất).
* **Tên tiếng Anh:** 6-Axis Articulated Industrial Robot.
* **Tên tiếng Việt:** Robot khớp nối công nghiệp 6 trục.
* **Vai trò:** Gắp, căn chỉnh, lắp ráp các module điện tử nhỏ (ECU, cảm biến ô tô), bắt ốc vít chính xác cao, bốc xếp pallet.
* **Vấn đề máy có thể gặp phải:**
  * Động cơ servo quá dòng hoặc quá nhiệt (*Servo Motor Overload*).
  * Lệch khớp hoặc va chạm cơ học (*Collision detected*).
  * Mòn đai truyền động hoặc cạn mỡ bôi trơn hộp giảm tốc (*Gearbox backlash*).
  * Hỏng van hút chân không/kẹp gắp phôi (*Gripper vacuum failure*).
* **Dữ liệu log/cảm biến cấp cho IoT (qua RC8/RC9 Controller API, Modbus TCP):**
  * `Joint_Current_J1_to_J6` (dòng điện từng khớp), `Motor_Temp_J1_to_J6` (°C).
  * `Pos_Error` (độ lệch vị trí mục tiêu vs thực tế).
  * `Gripper_Vacuum_Level_kPa` (áp suất hút kẹp), `Cycle_Time_Sec` (thời gian chu kỳ).
  * Mã lỗi controller (ví dụ: `Error 8150: Joint 3 Overload`).
* **Thao tác Agent có thể thực thi:**
  * **Thao tác PLC/Controller:** Kích hoạt chế độ `Safe-Home-Routine` (đưa tay máy về điểm an toàn rồi dừng, tránh dừng đột ngột gây kẹt phôi).
  * **Thao tác vận hành:** Giảm tốc độ robot (`Cycle speed override = 70%`) khi phát hiện động cơ khớp J3 tiệm cận ngưỡng quá nhiệt để duy trì vận hành đến ca bảo dưỡng.
  * **Thao tác phân tích:** Truy vấn log 20 chu kỳ trước đó, đối chiếu với tài liệu bảo trì robot DENSO RC8 để kết luận nguyên nhân do kẹp phôi lệch trọng tâm hay do lỗi cơ khí.

---

## 3. Máy ép nhựa / đúc khuôn linh kiện điện tử (Vỏ ECU, hộp cầu chì)

* **Mã máy DENSO / Model phổ biến:** `FANUC ROBOSHOT S-100iA` hoặc `Sumitomo SE-EV`. Mã trạm nội bộ: `IM-PRESS-04` (Injection Molding Station 04).
* **Tên tiếng Anh:** All-Electric Injection Molding Machine.
* **Tên tiếng Việt:** Máy ép phun nhựa bằng điện.
* **Vai trò:** Ép khuôn nhựa kỹ thuật chịu nhiệt làm vỏ bọc cho các hộp điều khiển điện tử ECU, cảm biến đỗ xe, giắc cắm chịu nước trên ô tô.
* **Vấn đề máy có thể gặp phải:**
  * Áp suất phun dao động làm sản phẩm bị thiếu liệu (*short shot*) hoặc bavia (*flash*).
  * Nhiệt độ nòng trục vít (*barrel*) không đều khiến nhựa bị cháy hoặc vón cục.
  * Kẹt khuôn, rò rỉ nhiệt khuôn đúc.
* **Dữ liệu log/cảm biến cấp cho IoT (qua giao thức Euromap 63/77, OPC-UA):**
  * `Barrel_Zone1..Zone5_Temp` (nhiệt độ các vùng nung).
  * `Injection_Peak_Pressure_MPa` (áp suất phun cực đại), `Cushion_Position_mm` (vị trí đệm nhựa).
  * `Mold_Temp_Cavity/Core` (nhiệt độ lòng khuôn).
  * `Clamping_Force_kN` (lực kẹp khuôn).
* **Thao tác Agent có thể thực thi:**
  * **Thao tác kiểm soát chất lượng (MES):** Khi phát hiện áp suất phun lệch chuẩn 5 shot liên tiếp, gắn cờ `Quality_Hold` trên hệ thống MES cho lô sản phẩm vừa ép, kích hoạt cổng phân loại tự động (*Reject Gate*) loại bỏ sản phẩm nghi lỗi.
  * **Thao tác năng lượng/bảo trì:** Điều chỉnh dải nhiệt sấy nòng hoặc gửi lệnh ngừng chu trình ép tự động nếu nhiệt độ nòng không đạt ngưỡng hóa dẻo tiêu chuẩn.

---

## 4. Máy kiểm tra quang học tự động (Kiểm tra chân hàn bảng mạch ECU)

* **Mã máy DENSO / Model phổ biến:** `Koh Young 3D AOI Zenith Alpha` hoặc `Omron VT-S10 Series`. Mã trạm nội bộ: `AOI-INSPECT-02`.
* **Tên tiếng Anh:** 3D Automated Optical Inspection (AOI) Machine.
* **Tên tiếng Việt:** Máy kiểm tra quang học tự động 3D.
* **Vai trò:** Dùng camera độ phân giải cao và laser quét 3D bề mặt bo mạch điện tử ô tô (SMT PCBA), phát hiện lỗi hàn chì, lệch linh kiện, thiếu linh kiện trước khi đóng vỏ.
* **Vấn đề máy có thể gặp phải:**
  * Tỷ lệ báo động giả tăng vọt (*False Call Rate*) do ánh sáng nền hoặc bụi bám thấu kính camera.
  * Lệch cân chỉnh toạ độ quang học (*Calibration drift*).
  * Quá nhiệt hệ thống đèn chiếu sáng LED đa góc.
* **Dữ liệu log/cảm biến cấp cho IoT (qua SECS/GEM hoặc TCP/IP Log Stream):**
  * `Defect_Type` (loại lỗi: *Bridging, Tombstone, Missing, Coplanarity*).
  * `PCB_ID_Barcode` (mã định danh bo mạch).
  * `Camera_Light_Source_Current` (cường độ đèn LED), `Inspection_Duration_ms`.
  * `False_Reject_Ratio_%` (tỷ lệ lỗi trên tổng sản phẩm).
* **Thao tác Agent có thể thực thi:**
  * **Tự động cập nhật tham số (Fine-tune Threshold):** Nhận diện mẫu báo lỗi giả lặp lại liên tục ở linh kiện cụ thể do sai lệch quang sai, tự động điều chỉnh ngưỡng biên độ dung sai (*tolerance window*) trong file recipe theo quy tắc đã được phê duyệt.
  * **Thao tác phân luồng:** Phát lệnh dừng khẩn cấp dây chuyền dán bề mặt (*Pick-and-Place machine*) ở công đoạn trước nếu phát hiện 3 bảng mạch liên tiếp cùng thiếu linh kiện tại vị trí `R102`.

---

## 5. Xe tự hành vận chuyển linh kiện nội bộ (AGV/AMR)

* **Mã máy DENSO / Model phổ biến:** `MiR250` (Mobile Industrial Robots) hoặc AGV dẫn đường từ DENSO Logistics Solution. Mã trạm nội bộ: `AMR-TRANS-03`.
* **Tên tiếng Anh:** Autonomous Mobile Robot (AMR).
* **Tên tiếng Việt:** Robot tự hành vận chuyển vật tư nội bộ.
* **Vai trò:** Vận chuyển khay phôi kim loại từ máy CNC sang máy kiểm tra, hoặc đưa các linh kiện đã hoàn thiện vào kho chứa tự động (AS/RS).
* **Vấn đề máy có thể gặp phải:**
  * Mất bản đồ toạ độ (*Localization lost*) do vật cản thay đổi bất ngờ trong lối đi.
  * Hao pin nhanh, pin chai hoặc trượt sạc trạm docking.
  * Cảm biến LiDAR bị bụi bẩn bám dính gây lỗi vật cản ảo (*Ghost obstacle*).
* **Dữ liệu log/cảm biến cấp cho IoT (qua REST API / MQTT / ROS Bridge):**
  * `Battery_SOC_%` (dung lượng pin), `Battery_Current_A`, `Battery_Cell_Temp_C`.
  * `LiDAR_Point_Cloud_Noise_Level` (độ nhiễu LiDAR).
  * `Navigation_Status` (*Driving, Blocked, Lost, Charging*).
  * `Payload_Weight_kg` (trọng tải hiện tại).
* **Thao tác Agent có thể thực thi:**
  * **Thao tác điều hướng:** Phát hiện xe bị kẹt quá 2 phút do lối đi chính bị chặn, tính toán lại lộ trình và cập nhật toạ độ tránh đường sang nhánh phụ.
  * **Thao tác quản lý năng lượng:** Nhận diện nhiệt độ pin tăng cao bất thường trong chu kỳ sạc nhanh, gửi lệnh hạ dòng sạc trạm docking xuống mức an toàn và gán lệnh vận chuyển cấp bách cho xe khác dự phòng.