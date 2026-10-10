# Held-out questions (draft_v2; 22 questions x 2 run(s), through the gateway)

| Metric | Result |
|---|---|
| Answer has the required facts (answerable) | 89% (34/38) |
| Correct source document cited | 89% (34/38) |
| A correct page cited | 84% (32/38) |
| Only correct pages cited | 68% (26/38) |
| Refusal when the documents do not say | 100% (6/6) |
| LLM judge (all questions) | 98% (43/44) |
| Average seconds per question | 19.6 |

## By kind

| Kind | Facts | Page | Judge |
|---|---|---|---|
| fact | 88% (28/32) | 81% (26/32) | 97% (31/32) |
| scan | 100% (6/6) | 100% (6/6) | 100% (6/6) |
| refusal | 100% (6/6) | - | 100% (6/6) |

## Per question

| Q | lang | facts | doc | page | cited | judge | answer |
|---|---|---|---|---|---|---|---|
| I01 | vi | True | False | False | Phieu_bao_tri_SCV_scan p.2 | 1.0 | Nếu thay máy nén có diode trong van điều khiển ngoài bằng một máy nén không có diode trong van điều khiển ngoài, máy nén sẽ không hoạt động và ECU sẽ  |
| I02 | en | True | True | True | _brochure_tips-and-tricks_EN p.5, 6, 8, 9, 27, 28, …; ntification-Bulletin-English p.3 | 1.0 | When liquid refrigerant accumulates in the compressor, the CS (Crank to Suction) valve quickly discharges liquid refrigerant to the suction chamber to |
| I03 | vi | True | True | True | _brochure_tips-and-tricks_EN p.10, 14; Phieu_bao_tri_SCV_scan p.1, 2; oil_troubleshooting_bulletin p.2 | 1.0 | Khi tháo máy nén cũ, cần xả từ 30% đến 50% tổng lượng dầu. (Trang 2 / ngôn ngữ: en) |
| I04 | en | True | True | True | _brochure_tips-and-tricks_EN p.9; oil_troubleshooting_bulletin p.1 | 1.0 | Insufficient lubrication due to universal oil is the second most common reason for A/C compressor failure. |
| I05 | vi | True | True | True | _brochure_tips-and-tricks_EN p.5; ssor_Failure Analysis_Poster p.1 | 1.0 | Khi dầu PAO được cho vào chu trình môi chất lạnh có dầu PAG, hai loại dầu này sẽ không hòa quyện với nhau, dẫn đến việc tạo ra chất có dạng paraffine  |
| I06 | en | True | True | True | ssor_Failure Analysis_Poster p.1 | 1.0 | Discontinued |
| I07 | vi | False | True | True | mpressor Installation Manual p.4 | 0.5 | Không được đổ dầu trực tiếp vào máy nén. Khi cần điều chỉnh lượng dầu, dầu phải được đổ vào máy lọc, máy sấy hoặc máy hơi thứ hai (nếu có). (AC Compre |
| I08 | en | True | True | True | _brochure_tips-and-tricks_EN p.4, 8, 10, 18; mpressor Installation Manual p.4; AC Compressor Leaflet p.2; oil_troubleshooting_bulletin p.1, 2 | 1.0 | No, DENSO does not recommend using an A/C service station to flush the refrigerant cycle. According to the provided context, when flushing the refrige |
| I09 | vi | True | False | False | _brochure_tips-and-tricks_EN p.8 | 1.0 | Khi hệ thống có chất chống rò rỉ (leak stop), không thể thực hiện súc rửa được. Trong trường hợp này, cần thay thế toàn bộ hệ thống vì súc rửa không c |
| I10 | vi | True | True | True | Spark Plug Catalogue 2025 p.4 | 1.0 | Không được dùng bugi DENSO để đánh lửa cho đầu đốt gas (gas burner).   Bugi DENSO được thiết kế và sản xuất chỉ cho các động cơ ô tô, và việc sử dụng  |
| I11 | en | True | True | True | Spark Plug Catalogue 2025 p.4, 5, 6 | 1.0 | If a spark plug is installed with too low torque, it may cause damage to the engine and the plugs due to leakage of combustion gas or vibration. (Spar |
| I12 | en | False | True | True | Spark Plug Catalogue 2025 p.2, 3, 4, 5, 16, 17, … | 1.0 | R: removable |
| I13 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.1, 9, 24, 27 | 1.0 | Theo slide, trong cờ vua, hệ số phân nhánh b khoảng 35 và độ sâu m khoảng 100. |
| I14 | vi | True | True | False | Bài 5 - Tìm kiếm có đối thủ p.1 | 1.0 | 12-ply = Deep Blue, Kasparov. (Bài 5 - Tìm kiếm có đối thủ, tr. 27) |
| I15 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.45 | 1.0 | Chương trình Chinook đã kết thúc 40 năm thống trị của nhà vô địch thế giới Marion Tinsley vào năm 1994, bằng cách sử dụng một cơ sở dữ liệu kết thúc t |
| I16 | en | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.40 | 1.0 | Deep Blue performed 30 billion evaluations per move. (Bài 5 - Tìm kiếm có đối thủ, p. 40) |
| I17 | vi | True | True | True | allation guide (đa ngôn ngữ) p.1; Phieu_bao_tri_SCV_scan p.1 | 1.0 | Bộ kit: DCRS300260 (294009-2150) (Phieu_bao_tri_SCV_scan, p. 1) |
| I18 | en | True | True | True | AC_oil_table_photo p.1; AC Compressor Leaflet p.2 | 1.0 | DENSO Oil 12 |
| I19 | ja | True | True | True | SCV_ghi_chu_JP_scan p.1 | 1.0 | ガイドピンなしで取り付けると燃料漏れの恐れがあります。 (SCV_ghi_chu_JP_scan.md, p. 1) |
| I20 | vi | True | None | None |  | 1.0 | Tài liệu được cung cấp không chứa thông tin về giá cả của lon dầu DENSO ND-oil 12. Do đó, tôi không thể cung cấp câu trả lời về giá tiền của sản phẩm  |
| I21 | en | True | None | None |  | 1.0 | The provided context does not specify the warranty period for DENSO A/C compressors. While the documents mention warranty conditions (e.g., voiding wa |
| I22 | vi | True | None | None |  | 1.0 | Tôi không có đủ thông tin để trả lời câu hỏi này. |
| I01 | vi | True | False | False | Phieu_bao_tri_SCV_scan p.2 | 1.0 | Nếu thay máy nén có diode trong van điều khiển ngoài bằng một máy nén không có diode trong van điều khiển ngoài, thì máy nén sẽ không hoạt động và ECU |
| I02 | en | True | True | True | _brochure_tips-and-tricks_EN p.5, 6, 8, 9, 27, 28, …; ntification-Bulletin-English p.3 | 1.0 | When liquid refrigerant accumulates in the compressor, the CS (Crank to Suction) valve quickly discharges liquid refrigerant to the suction chamber to |
| I03 | vi | True | True | True | _brochure_tips-and-tricks_EN p.10, 14; Phieu_bao_tri_SCV_scan p.1, 2; oil_troubleshooting_bulletin p.2 | 1.0 | Khi tháo máy nén cũ, cần xả từ 30% đến 50% tổng lượng dầu. (Trang 2 / ngôn ngữ: en) |
| I04 | en | True | True | True | _brochure_tips-and-tricks_EN p.9; oil_troubleshooting_bulletin p.1 | 1.0 | Insufficient lubrication due to universal oil is the second most common reason for A/C compressor failure. |
| I05 | vi | True | True | True | _brochure_tips-and-tricks_EN p.5, 6; ssor_Failure Analysis_Poster p.1 | 1.0 | Khi dầu PAO bị cho vào chu trình môi chất lạnh có dầu PAG, dầu PAO và dầu PAG sẽ không trộn lẫn nhau, dẫn đến việc tạo ra chất có dạng paraffine (para |
| I06 | en | True | True | True | ssor_Failure Analysis_Poster p.1 | 1.0 | Discontinued |
| I07 | vi | False | True | True | mpressor Installation Manual p.4 | 0.5 | Không được đổ dầu trực tiếp vào máy nén. Khi cần điều chỉnh lượng dầu, dầu phải được đổ vào máy lọc, máy sấy hoặc máy hơi thứ hai (nếu có). (AC Compre |
| I08 | en | True | True | True | _brochure_tips-and-tricks_EN p.4, 8, 10, 18; mpressor Installation Manual p.4; AC Compressor Leaflet p.2; oil_troubleshooting_bulletin p.1, 2 | 1.0 | No, DENSO does not recommend using an A/C service station to flush the refrigerant cycle. According to the provided context, when flushing the refrige |
| I09 | vi | True | False | False | _brochure_tips-and-tricks_EN p.8 | 1.0 | Khi hệ thống có chất chống rò rỉ (leak stop), không thể thực hiện súc rửa được. Trong trường hợp này, cần thay thế toàn bộ hệ thống vì súc rửa không k |
| I10 | vi | True | True | True | Spark Plug Catalogue 2025 p.4 | 1.0 | Không được dùng bugi DENSO để đánh lửa cho đầu đốt gas (gas burner). Bugi DENSO được bán ra không được thiết kế và sản xuất cho mục đích này, và việc  |
| I11 | en | True | True | True | Spark Plug Catalogue 2025 p.4, 5, 6 | 1.0 | If a spark plug is installed with too low torque, it may cause damage to the engine and the plugs due to leakage of combustion gas or vibration. (Spar |
| I12 | en | False | True | True | Spark Plug Catalogue 2025 p.2, 3, 4, 5, 16, 17, … | 1.0 | R: removable |
| I13 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.27 | 1.0 | b ~ 35, m ~100 |
| I14 | vi | True | True | False | Bài 5 - Tìm kiếm có đối thủ p.1 | 1.0 | 12-ply = Deep Blue, Kasparov. (Bài 5 - Tìm kiếm có đối thủ, tr. 27) |
| I15 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.45 | 1.0 | Chương trình Chinook đã đánh bại nhà vô địch cờ đam Marion Tinsley vào năm 1994, dựa vào một cơ sở dữ liệu kết thúc trận đấu được tính trước, xác định |
| I16 | en | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.4, 40 | 1.0 | Deep Blue performed 30 billion evaluations per move. |
| I17 | vi | True | True | True | allation guide (đa ngôn ngữ) p.1; Phieu_bao_tri_SCV_scan p.1 | 1.0 | Bộ kit: DCRS300260 (294009-2150) (Phieu_bao_tri_SCV_scan, p. 1) |
| I18 | en | True | True | True | AC_oil_table_photo p.1; AC Compressor Leaflet p.2 | 1.0 | DENSO Oil 12 |
| I19 | ja | True | True | True | SCV_ghi_chu_JP_scan p.1 | 1.0 | ガイドピンなしで取り付けると燃料漏れの恐れがあります。 (SCV_ghi_chu_JP_scan.md, p. 1) |
| I20 | vi | True | None | None |  | 1.0 | Tài liệu được cung cấp không chứa thông tin về giá cả của lon dầu DENSO ND-oil 12. Do đó, tôi không thể cung cấp thông tin về giá tiền của sản phẩm nà |
| I21 | en | True | None | None |  | 1.0 | The provided context does not specify the warranty period for DENSO A/C compressors. While the documents mention warranty conditions (e.g., voiding wa |
| I22 | vi | True | None | None |  | 1.0 | Tôi không có đủ thông tin để trả lời câu hỏi này. |
