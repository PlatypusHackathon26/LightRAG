# Held-out questions (draft_v4; 22 questions x 2 run(s), through the gateway)

| Metric | Result |
|---|---|
| Answer has the required facts (answerable) | 100% (38/38) |
| Correct source document cited | 95% (36/38) |
| A correct page cited | 92% (35/38) |
| Only correct pages cited | 76% (29/38) |
| Refusal when the documents do not say | 100% (6/6) |
| LLM judge (all questions) | 100% (44/44) |
| Average seconds per question | 29.1 |

## By kind

| Kind | Facts | Page | Judge |
|---|---|---|---|
| fact | 100% (32/32) | 91% (29/32) | 100% (32/32) |
| scan | 100% (6/6) | 100% (6/6) | 100% (6/6) |
| refusal | 100% (6/6) | - | 100% (6/6) |

## Per question

| Q | lang | facts | doc | page | cited | judge | answer |
|---|---|---|---|---|---|---|---|
| I01 | vi | True | True | True | ntification-Bulletin-English p.2 | 1.0 | Nếu thay máy nén có diode trong van điều khiển ngoài bằng một máy nén không có diode trong van điều khiển ngoài, máy nén sẽ không hoạt động và ECU sẽ  |
| I02 | en | True | True | True | _brochure_tips-and-tricks_EN p.5, 6, 8, 9, 27, 28, …; ntification-Bulletin-English p.3 | 1.0 | When liquid refrigerant accumulates in the compressor, the CS (Crank to Suction) valve quickly discharges liquid refrigerant to the suction chamber to |
| I03 | vi | True | False | False | mpressor Installation Manual p.4, 5, 6 | 1.0 | Cần xả từ 30% đến 50% tổng lượng dầu khi tháo máy nén cũ. (AC Compressor Installation Manual.md, p. 2) |
| I04 | en | True | True | True | _brochure_tips-and-tricks_EN p.9; oil_troubleshooting_bulletin p.1 | 1.0 | Insufficient lubrication due to universal oil is the second most common reason for A/C compressor failure. |
| I05 | vi | True | True | True | _brochure_tips-and-tricks_EN p.6; ssor_Failure Analysis_Poster p.1 | 1.0 | Khi dầu PAO được cho vào chu trình môi chất lạnh có dầu PAG, hai loại dầu này sẽ không hòa quyện với nhau, dẫn đến việc tạo ra chất paraffine (paraffi |
| I06 | en | True | True | True | ssor_Failure Analysis_Poster p.1 | 1.0 | Discontinued |
| I07 | vi | True | True | True | mpressor Installation Manual p.4 | 1.0 | Không được đổ dầu trực tiếp vào máy nén. Khi cần điều chỉnh lượng dầu, dầu phải được đổ vào máy lạnh (condenser), bình lọc ẩm (receiver dryer) hoặc ch |
| I08 | en | True | True | True | _brochure_tips-and-tricks_EN p.4, 8, 10, 18; mpressor Installation Manual p.4; AC Compressor Leaflet p.2; oil_troubleshooting_bulletin p.1, 2 | 1.0 | No, DENSO does not recommend using an A/C service station to flush the refrigerant cycle. According to the provided context, when flushing the refrige |
| I09 | vi | True | True | True | mpressor Installation Manual p.4 | 1.0 | Khi hệ thống có chất chống rò rỉ (leak stop), không thể thực hiện súc rửa được. Trong trường hợp này, toàn bộ hệ thống phải được thay thế. (AC Compres |
| I10 | vi | True | True | True | Spark Plug Catalogue 2025 p.4 | 1.0 | Không được dùng bugi DENSO để đánh lửa cho đầu đốt gas (gas burner).   Bugi DENSO được thiết kế và sản xuất chỉ cho các động cơ ô tô, và việc sử dụng  |
| I11 | en | True | True | True | Spark Plug Catalogue 2025 p.4, 5, 6 | 1.0 | If a spark plug is installed with too low torque, it may cause damage to the engine and the plugs due to leakage of combustion gas or vibration. (Spar |
| I12 | en | True | True | True | Spark Plug Catalogue 2025 p.2, 3, 4, 5, 16, 17, … | 1.0 | R: removable |
| I13 | vi | True | True | False | Bài 5 - Tìm kiếm có đối thủ p.1 | 1.0 | Trong cờ vua, hệ số phân nhánh b khoảng 35 và độ sâu m khoảng 100. (Bài 5 - Tìm kiếm có đối thủ, trang 27) |
| I14 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.27 | 1.0 | Độ sâu tìm kiếm 12-ply tương đương với trình độ của Deep Blue và Garry Kasparov. (Trang 27, ngôn ngữ: vi) |
| I15 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.45 | 1.0 | Chương trình Chinook đã kết thúc 40 năm thống trị của nhà vô địch thế giới Marion Tinsley vào năm 1994, bằng cách sử dụng một cơ sở dữ liệu kết thúc t |
| I16 | en | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.4, 40 | 1.0 | Deep Blue performed 30 billion evaluations per move. |
| I17 | vi | True | True | True | allation guide (đa ngôn ngữ) p.1; Phieu_bao_tri_SCV_scan p.1 | 1.0 | Bộ kit: DCRS300260 (294009-2150) (Phieu_bao_tri_SCV_scan, p. 1) |
| I18 | en | True | True | True | AC_oil_table_photo p.1 | 1.0 | DENSO Oil 12 is listed for #PA, #S, #SB, #SE, SC, 6CA compressors with HFO 1234yf. |
| I19 | ja | True | True | True | SCV_ghi_chu_JP_scan p.1 | 1.0 | ガイドピンなしで取り付けると燃料漏れの恐れがあります。 (SCV_ghi_chu_JP_scan.md, p. 1) |
| I20 | vi | True | None | None |  | 1.0 | Tài liệu được cung cấp không chứa thông tin về giá cả của lon dầu DENSO ND-oil 12. Do đó, tôi không thể cung cấp câu trả lời về giá tiền của sản phẩm  |
| I21 | en | True | None | None |  | 1.0 | The provided context does not specify the warranty period for DENSO A/C compressors. Therefore, I cannot determine how many months of warranty DENSO g |
| I22 | vi | True | None | None |  | 1.0 | Tôi không có đủ thông tin để trả lời câu hỏi này. |
| I01 | vi | True | True | True | ntification-Bulletin-English p.2 | 1.0 | Nếu thay máy nén có diode trong van điều khiển ngoài bằng một máy nén không có diode trong van điều khiển ngoài, thì máy nén sẽ không hoạt động và ECU |
| I02 | en | True | True | True | _brochure_tips-and-tricks_EN p.5, 6, 8, 9, 27, 28, …; ntification-Bulletin-English p.3 | 1.0 | When liquid refrigerant accumulates in the compressor, the CS (Crank to Suction) valve quickly discharges liquid refrigerant to the suction chamber to |
| I03 | vi | True | False | False | mpressor Installation Manual p.4, 5, 6 | 1.0 | Khi tháo máy nén cũ, cần xả từ 30% đến 50% tổng lượng dầu. (AC Compressor Installation Manual.md, p. 2) |
| I04 | en | True | True | True | _brochure_tips-and-tricks_EN p.9; oil_troubleshooting_bulletin p.1 | 1.0 | Insufficient lubrication due to universal oil is the second most common reason for A/C compressor failure. |
| I05 | vi | True | True | True | _brochure_tips-and-tricks_EN p.6; ssor_Failure Analysis_Poster p.1 | 1.0 | Khi dầu PAO bị cho vào chu trình môi chất lạnh có dầu PAG, hai loại dầu này sẽ không hòa quyện với nhau, dẫn đến việc tạo ra chất paraffine (paraffin- |
| I06 | en | True | True | True | ssor_Failure Analysis_Poster p.1 | 1.0 | Discontinued |
| I07 | vi | True | True | True | mpressor Installation Manual p.4 | 1.0 | Không được đổ dầu trực tiếp vào máy nén. Khi cần điều chỉnh lượng dầu, dầu phải được đổ vào máy lọc ẩm (receiver dryer), dàn ngưng (condenser) hoặc ch |
| I08 | en | True | True | True | _brochure_tips-and-tricks_EN p.4, 8, 10, 18; mpressor Installation Manual p.4; AC Compressor Leaflet p.2; oil_troubleshooting_bulletin p.1, 2 | 1.0 | No, DENSO does not recommend using an A/C service station to flush the refrigerant cycle. According to the provided context, when flushing the refrige |
| I09 | vi | True | True | True | mpressor Installation Manual p.4 | 1.0 | Khi hệ thống có chất chống rò rỉ (leak stop), không thể thực hiện súc rửa được. Trong trường hợp này, toàn bộ hệ thống phải được thay thế. (AC Compres |
| I10 | vi | True | True | True | Spark Plug Catalogue 2025 p.4 | 1.0 | Không được dùng bugi DENSO để đánh lửa cho đầu đốt gas (gas burner).   Bugi DENSO được thiết kế và sản xuất cho các động cơ xe hơi, và việc sử dụng ch |
| I11 | en | True | True | True | Spark Plug Catalogue 2025 p.4, 5, 6 | 1.0 | If a spark plug is installed with too low torque, it may cause damage to the engine and the plugs due to leakage of combustion gas or vibration. (Spar |
| I12 | en | True | True | True | Spark Plug Catalogue 2025 p.2, 3, 4, 5, 16, 17, … | 1.0 | R: removable |
| I13 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.27 | 1.0 | Trong cờ vua, hệ số phân nhánh b khoảng 35 và độ sâu m khoảng 100. (Trang 27) |
| I14 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.27 | 1.0 | 12-ply = Deep Blue, Kasparov. (Bài 5 - Tìm kiếm có đối thủ, tr. 27) |
| I15 | vi | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.45 | 1.0 | Chương trình Chinook đã kết thúc 40 năm thống trị của nhà vô địch thế giới Marion Tinsley vào năm 1994, bằng cách sử dụng một cơ sở dữ liệu kết thúc t |
| I16 | en | True | True | True | Bài 5 - Tìm kiếm có đối thủ p.4, 40 | 1.0 | Deep Blue performed 30 billion evaluations per move. |
| I17 | vi | True | True | True | allation guide (đa ngôn ngữ) p.1; Phieu_bao_tri_SCV_scan p.1 | 1.0 | Bộ kit có mã DCRS300260 (294009-2150). (Phieu_bao_tri_SCV_scan.md, p. 1) |
| I18 | en | True | True | True | AC_oil_table_photo p.1 | 1.0 | DENSO Oil 12 is listed for #PA, #S, #SB, #SE, SC, 6CA compressors with HFO 1234yf. |
| I19 | ja | True | True | True | SCV_ghi_chu_JP_scan p.1 | 1.0 | ガイドピンなしで取り付けると燃料漏れの恐れがあります。 (SCV_ghi_chu_JP_scan.md, p. 1) |
| I20 | vi | True | None | None |  | 1.0 | Tài liệu được cung cấp không chứa thông tin về giá cả của lon dầu DENSO ND-oil 12. Do đó, tôi không thể cung cấp câu trả lời về giá tiền của sản phẩm  |
| I21 | en | True | None | None |  | 1.0 | The provided context does not specify the warranty period for DENSO A/C compressors. Therefore, I cannot determine how many months of warranty DENSO g |
| I22 | vi | True | None | None |  | 1.0 | Tôi không có đủ thông tin để trả lời câu hỏi này. |
