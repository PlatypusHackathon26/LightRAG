# Answering models on identical retrieval (nvidia_vs_cerebras)

| Model | Judge | Facts recall | All facts | Abstention | Avg s |
|---|---|---|---|---|---|
| nemotron | 98% | 86% | 73% | 100% | 1.8 |
| cerebras-gpt-oss | 98% | 79% | 68% | 100% | 2.0 |

## Questions where the models disagree

- Q19: nemotron 1.0, cerebras-gpt-oss 0.5
- Q24: nemotron 0.5, cerebras-gpt-oss 1.0

## Vietnamese probes (read: anything not in the documents?)

### thuật toán alpha-beta pruning là gì
- **nemotron**: Thuật toán alpha-beta pruning là một phương pháp cắt cụt được sử dụng trong thuật toán Minimax để giảm số lượng nút cần được đánh giá trong cây trò chơi, từ đó tăng hiệu suất tìm kiếm mà không ảnh hưởng đến kết quả cuối cùng. Nó hoạt động bằng cách duy trì hai giá trị: alpha (giá trị tốt nhất hiện tại cho người chơi Max) và beta (giá trị tốt nhất hiện tại cho người chơi Min). Nếu tại bất kỳ điểm nào trong quá trình duyệt cây, alpha trở nên lớn hơn hoặc bằng beta, thì các nhánh còn lại của nút hiện tại có thể bị cắt bỏ (pruned) vì chúng không thể ảnh hưởng đến quyết định cuối cùng.

Các đặc điểm chính của alpha-beta pruning bao gồm:
- Nó không ảnh hưởng đến kết quả cuối cùng của thuật toán Minimax, chỉ giảm thời gian tìm kiếm.
- Thứ tự sắp xếp các bước đi trong cây tìm kiếm có ảnh hưởng lớn đến hiệu quả của việc cắt cụt; với một "sắp xếp hoàn hảo", độ phức tạp thời gian giảm từ O(b^m) xuống O(b^(m/2)), trong đó b là hệ số phân nhánh và m là độ sâu của cây.
- Alpha (α) được định nghĩa là giá trị tốt nhất (cao nhất) mà Max có thể đảm bảo đến thời điểm hiện tại; nếu một nút con có giá trị kém hơn alpha, Max sẽ loại bỏ nút đó (cắt nhánh).
- Beta (β) được định nghĩa tương tự cho Min: là giá trị tốt nhất (thấp nhất) mà Min có thể đảm bảo; nếu một nút con tốt hơn beta, Min sẽ loại bỏ nó.

Thuật toán được mô tả qua hai hàm đệ quy: MaxVal và MinVal. Trong MaxVal, alpha được cập nhật bằng giá trị lớn nhất giữa alpha hiện tại và kết quả của MinVal trên các nút con; nếu alpha >= beta, quá trình duyệt dừng lại. Tương tự, trong MinVal, beta được cập nhật bằng giá trị nhỏ nhất giữa beta hiện tại và kết quả của MaxVal trên các nút con; nếu alpha >= beta, quá trình cũng dừng lại.
- **cerebras-gpt-oss**: **Alpha‑beta pruning** là một kỹ thuật cắt nhánh được sử dụng trong thuật toán tìm kiếm cây trò chơi (Minimax) để loại bỏ các nhánh không cần thiết mà không ảnh hưởng đến kết quả cuối cùng. Khi duyệt cây, nếu giá trị **α** (giá trị tốt nhất hiện tại của nút Max) lớn hơn hoặc bằng **β** (giá trị tốt nhất hiện tại của nút Min), các nhánh còn lại của nút hiện tại sẽ bị bỏ qua vì chúng không thể cải thiện kết quả đã biết. Nhờ vậy, thời gian tìm kiếm giảm đáng kể mà không làm thay đổi quyết định tối ưu cuối cùng. (Bài 5 - Tìm kiếm có đối thủ.md, p. 34)

### Deep Blue và AlphaGo đã dùng thuật toán gì để thắng con người?
- **nemotron**: Deep Blue đã sử dụng thuật toán Minimax kết hợp với phương pháp cắt cụt alpha-beta (α-β pruning) để đánh bại Garry Kasparov trong cờ vua năm 1997. AlphaGo đã sử dụng học sâu (Deep Learning) kết hợp với các kỹ thuật như bảng chuyển vị (transposition table), cắt tiến (forward pruning) và bảng tra cứu cho nước đi mở đầu và kết thúc để đánh bại Lee Sedol trong cờ vây năm 2016. (Trang 40, Trang 39, Trang 45)
- **cerebras-gpt-oss**: Deep Blue đã thắng con người bằng cách áp dụng **thuật toán Minimax kết hợp cắt cụt α‑β** (alpha‑beta pruning), cho phép duyệt và đánh giá hàng tỷ vị trí trong cây trò chơi mà không làm thay đổi kết quả cuối cùng (xem phần “Advanced techniques” và “Hệ thống chơi cờ” trong tài liệu) [2].  

AlphaGo thắng con người bằng **học sâu (deep learning)**, sử dụng các mạng nơ‑ron để học chiến lược và đánh giá vị trí (được nêu trong phần “AlphaGo” của tài liệu) [2].

### Sau khi lắp máy nén điều hòa mới phải chạy rà như thế nào?
- **nemotron**: Sau khi lắp máy nén điều hòa mới, cần thực hiện quy trình chạy rà (run-in procedure) để phân phối dầu máy nén và bắt đầu quá trình bôi trơn, nhằm ngăn ngừa hư hỏng ngay sau khi lắp đặt mới. Các bước cụ thể như sau:

1. Đặt nhiệt độ ở mức làm lạnh tối đa.  
2. Bật quạt thông gió ở tốc độ tối đa.  
3. Khởi động máy và giữ tốc độ máy ở chế độ ralentí.  
4. Bật hệ thống điều hòa trong ít nhất 5 phút. KHÔNG tăng tốc độ máy trong thời gian này.  
5. Sau 5 phút, toàn bộ dầu máy nén ban đầu được chứa trong máy nén sẽ được vận chuyển qua toàn bộ hệ thống. Lúc này mới có thể tăng tốc độ máy và kiểm tra hệ thống điều hòa.

Quy trình này được áp dụng đồng nhất trong nhiều phiên bản tài liệu hướng dẫn lắp đặt máy nén điều hòa của DENSO, bao gồm các bản tiếng Anh, Romanian, Spanish và Croatian, với cùng một mục đích: đảm bảo dầu được phân phối đều và tránh hư hỏng do thiếu bôi trơn ngay sau lắp đặt.
- **cerebras-gpt-oss**: **Quy trình chạy rà (run‑in) sau khi lắp máy nén điều hòa mới**

1. **Đặt nhiệt độ điều hòa ở mức tối đa lạnh**.  
2. **Bật quạt cabin ở tốc độ tối đa**.  
3. **Khởi động động cơ và giữ ở chế độ hãm** (idle).  
4. **Bật chế độ A/C trong ít nhất 5 phút** và **không tăng tốc độ động cơ** trong thời gian này.  
5. **Sau 5 phút**, dầu máy nén – vốn ban đầu chỉ nằm trong máy nén – sẽ được phân phối khắp hệ thống. Khi đó, có thể tăng tốc độ động cơ và kiểm tra hoạt động của hệ thống A/C.  

*(Tham khảo: “Procedura de rulare a compresorului” trong tài liệu *AC Compressor Installation Manual.md* – trang 44, tiếng Romania; “Procedimiento de puesta en marcha” trong tài liệu *AC Compressor Installation Manual.md* – trang 20, tiếng Tây Ban Nha.)*

### Dầu DENSO nào dùng cho máy nén kiểu TV với môi chất R-134a?
- **nemotron**: Dầu DENSO 9 (DENSO Oil 9) được dùng cho máy nén kiểu TV với môi chất R-134a. (AC Compressor Leaflet.md)
- **cerebras-gpt-oss**: Đối với máy nén kiểu **TV (vane‑type blower)** khi sử dụng môi chất **R‑134a**, DENSO khuyến cáo dùng **DENSO Oil 9**.

