# Bàn giao dự án cho Claude

Tài liệu này gom bối cảnh cần thiết để tiếp tục dự án. Thư mục gốc là `/Users/albert/Work Space/XLA/AI Image Forensics`.

## Mục tiêu và lý do

Đề tài: **Evaluating AI-Generated Image Detection Under Repeated Compression and Resizing**. Câu hỏi chính là điểm phát hiện ảnh do AI tạo thay đổi thế nào khi ảnh bị nén JPEG hoặc đổi kích thước lặp lại. Các thao tác này thường xuất hiện khi lưu và chia sẻ ảnh, đồng thời có thể làm thay đổi dấu vết mà bộ phát hiện sử dụng. Vì vậy, nghiên cứu so sánh ảnh gốc, các biến thể đã xử lý và đối chứng có cùng kích thước cuối.

Sản phẩm là một trợ lý giám định ảnh chạy cục bộ, một thí nghiệm benchmark có thể tái lập và một báo cáo nghiên cứu. Đây **không phải mô hình phát hiện mới**. Đóng góp nằm ở quy trình so sánh, cách ghi nhận bằng chứng và cách trình bày bất định.

## Phân vai các mô hình

- **B-Free** đo bằng chứng ở cấp toàn ảnh cho tác vụ phát hiện ảnh do AI tạo. Giao diện hiển thị sigmoid của logit trên thang 0–1; đây không phải xác suất đã được hiệu chuẩn. Quy tắc phân loại mặc định là `score > 0.5`, không phải `>=`.
- **TruFor** đo dấu hiệu chỉnh sửa/manipulation và tạo bản đồ bất thường, bản đồ độ tin cậy định vị cùng điểm toàn ảnh. Nó không xác định điểm ảnh do AI tạo. Giữ đầu ra TruFor tách biệt với B-Free; không gộp chúng thành một điểm “độ tin cậy”.
- **Qwen2.5-1.5B-Instruct** chạy trên máy và chọn bước kế tiếp trong danh sách công cụ cho phép dựa trên số liệu đã đo. Nó không nhận ảnh, tên tệp, nhãn thật hay quyền gọi shell/mạng. Báo cáo cuối được tính từ dữ liệu và mã bằng chứng, không phải văn bản tự do do mô hình bịa ra.

Hai chế độ trong giao diện:

1. **Thí nghiệm cố định:** người dùng chọn phép biến đổi, thứ tự, số vòng và chế độ nối tiếp/đối chứng.
2. **Phân tích thích ứng:** đo B-Free trên ảnh gốc trước; sau đó Qwen chọn phép thử JPEG/resize/TruFor hoặc kết thúc. Mặc định tối đa 4 lượt gọi công cụ, gồm cả lượt ảnh gốc; cho phép đặt 2–6. Mỗi nhánh biến đổi bắt đầu từ cùng ảnh gốc. Các vòng bên trong một nhánh thì xử lý nối tiếp.

Giao diện đã được Việt hóa, có chuyển động nhẹ khi tải ảnh, xử lý và nhận bằng chứng mới; chế độ `prefers-reduced-motion` tắt chuyển động. Kết quả thật không được làm hoạt ảnh giả. Có xuất CSV/JSON, mã bằng chứng E1/E2…, cảnh báo bất định và ảnh/bản đồ so sánh.

## Nghiên cứu và kết quả hiện có

Pilot đã chạy trên 320 ảnh: 160 ảnh thật và 160 ảnh tạo bởi bốn họ mô hình (DALL·E 3, Adobe Firefly, Midjourney v5, Stable Diffusion XL), ghép theo nguồn/nội dung. Chia theo nhóm thành 64 train, 64 validation và 192 test. Benchmark có chín điều kiện và 1.728 dự đoán test cho mỗi bộ phát hiện. Đối chứng cổ điển là FFT/DCT + logistic regression, chỉ fit trên ảnh train.

| Điều kiện | B-Free balanced accuracy |
|---|---:|
| Ảnh gốc | 100,00% |
| JPEG Q85, ba lần nén | 100,00% |
| Resize 90%, ba vòng | 95,83% |
| Resize rồi JPEG Q95, ba vòng | 95,83% |
| JPEG Q95 rồi resize, ba vòng | 94,79% |
| Một lượt ở kích thước vòng 3, Q95 | 96,88% |

FFT/DCT đạt 73,44% balanced accuracy trên ảnh gốc và sau ba lần JPEG Q85. Khoảng bootstrap chính của B-Free suy biến thành [0, 0] vì trong 96 nhóm ghép cặp không có nhóm nào đổi quyết định ở điều kiện chính. Điều này **không** chứng minh bất định ngoài mẫu bằng 0. Kết quả chỉ áp dụng cho pilot này; chưa đánh giá trên họ sinh ảnh chưa thấy, ảnh Internet bất kỳ hay quy trình đăng mạng xã hội thực tế.

Đánh giá chính sách Qwen riêng biệt dùng 24 ảnh. Qwen phát hiện 1/1 trường hợp thay đổi ngưỡng với trung bình 4 lượt gọi; chính sách cố định cũng phát hiện 1/1 với 4 lượt, còn luật cơ sở phát hiện 1/1 với 2,54 lượt. Mẫu có đúng một trường hợp bất ổn, nên chưa có bằng chứng Qwen cải thiện phát hiện hay tiết kiệm lượt gọi.

## Chạy dự án

Trên máy đã cấu hình, từ thư mục dự án chạy:

```bash
bash scripts/start-with-models.sh
```

Hoặc mở `start.command`. Truy cập `http://127.0.0.1:8765`. Máy chủ chỉ bind localhost. Mô hình lần đầu có thể mất thời gian tải vào bộ nhớ; TruFor trên ảnh lớn có thể chạy vài phút. Ảnh tải lên và đầu ra được giữ trong `output/runs/` trên máy.

`README.md` hướng dẫn thêm cách dùng CLI, tái lập benchmark, dựng báo cáo và khởi tạo môi trường mới. Môi trường ML cùng mô hình đã cài sẵn trên Mac này; thư mục `external/` và `.venv/` có thể bị gitignore nên không mặc định đi theo bản sao mã nguồn.

## Các tệp requirement và môi trường

- [`requirements.txt`](../requirements.txt): chỉ có Pillow và NumPy cho luồng xử lý cơ bản. Tệp này **không** cài toàn bộ stack neural.
- [`requirements-report.txt`](../requirements-report.txt): ReportLab 4.4.9 và Pillow để dựng báo cáo PDF.
- [`output/model-verification/requirements-installed.txt`](../output/model-verification/requirements-installed.txt): ảnh chụp các gói đã cài cho môi trường ML đã xác minh, gồm Python 3.12, PyTorch 2.5.1, torchvision 0.20.1, timm 1.0.12, Transformers 4.43.4 và các gói liên quan.
- [`docs/MODEL_SETUP.md`](MODEL_SETUP.md): nguồn/revision mô hình, checksum trọng số, cách cài đặt, preprocessing và giới hạn từng adapter.

Khi chạy có mô hình, dùng `scripts/start-with-models.sh` hoặc `source scripts/model-env.sh` cùng `.venv/bin/python`; không cài stack ML vào Python hệ thống. B-Free và TruFor upstream có điều khoản informational/nonprofit; cần giữ license và kiểm tra quyền sử dụng trước khi phân phối hay dùng thương mại.

## Tệp quan trọng

- [`README.md`](../README.md): cách chạy, luồng sử dụng, tái lập và giới hạn tổng quát.
- [`docs/RESEARCH_WRITEUP.md`](RESEARCH_WRITEUP.md): báo cáo nghiên cứu đầy đủ và diễn giải số liệu.
- [`docs/BENCHMARK_PROTOCOL.md`](BENCHMARK_PROTOCOL.md): protocol đã đóng băng của pilot.
- [`docs/BENCHMARK_RESULTS.md`](BENCHMARK_RESULTS.md): kết quả benchmark và kiểm định.
- [`docs/AGENT_DESIGN.md`](AGENT_DESIGN.md): hợp đồng hành động Qwen, ngân sách, bằng chứng và giới hạn.
- [`docs/AGENT_RESULTS.md`](AGENT_RESULTS.md): kết quả replay so sánh chính sách trợ lý.
- [`docs/EXPERIMENT_PROTOCOL.md`](EXPERIMENT_PROTOCOL.md): đề cương rộng hơn; ghi rõ nội dung nào là đề xuất lịch sử, chưa chạy.
- [`docs/UI_RESEARCH.md`](UI_RESEARCH.md): quyết định UX và tham khảo Mobbin.
- `web/index.html`, `web/app.js`, `web/style.css`: giao diện hiện tại.
- `forensics/`: xử lý ảnh, adapter mô hình, máy chủ, planner và benchmark.
- `output/pdf/AI_Image_Forensics_Research_Report.pdf`: báo cáo PDF được tạo.

## Tình trạng và quy tắc khi tiếp tục

Prototype, benchmark 320 ảnh, đánh giá chính sách, báo cáo và website tiếng Việt đã có. Chỉ thay đổi yêu cầu hiện tại của người dùng; không tự ý thiết kế lại sản phẩm hay chạy lại các lượt suy luận lớn.

Các module benchmark, baseline, pipeline, evaluator, agent và planner được ràng buộc bởi hash/protocol trong nghiên cứu. Đọc `output/benchmark/protocol.json` trước khi sửa. Không chỉnh sửa kết quả đã đo hay thay ngưỡng/dataset rồi gọi kết quả mới là cùng benchmark. Nếu cần nghiên cứu mới, tạo protocol/thư mục output riêng và ghi rõ khác biệt.

Giữ các phân biệt khoa học sau trong mọi giao diện/báo cáo:

- Điểm B-Free là bằng chứng mô hình, không phải xác suất xác thực.
- TruFor định vị dấu hiệu chỉnh sửa, không phải vùng ảnh do AI tạo.
- Các biến thể cùng nguồn có tương quan, không phải bằng chứng độc lập.
- Điểm thấp không chứng minh ảnh thật; điểm cao không chứng minh ảnh do AI tạo.
- Kết quả thiếu/lỗi không được thay bằng 0, heuristic hoặc heatmap giả.
- Tách rõ kết quả benchmark, ví dụ demo và phép thử đơn ảnh.

### Lưu ý về tệp PDF được cung cấp

Tệp `/Users/albert/Downloads/ĐỀ 13- BTL XLA.pdf` mang tên như đề bài, nhưng nội dung trích xuất bắt đầu bằng bài báo *A Bias-Free Training Paradigm for More General AI-generated Image Detection* (B-Free, arXiv:2412.17671v2). Hãy xem đó là tài liệu tham khảo về B-Free, không phải rubric/yêu cầu môn học. Nếu cần chứng minh đã đáp ứng đề bài, cần có đúng đề cương/rubric của môn trước khi chốt phần đối chiếu yêu cầu.

## Prompt tiếp tục dùng với Claude

> Tiếp tục dự án tại `/Users/albert/Work Space/XLA/AI Image Forensics`. Đọc toàn bộ `docs/HANDOFF_TO_CLAUDE.md` trước, rồi kiểm tra các tệp nguồn liên quan đến yêu cầu mình giao. Giữ nguyên protocol/hash benchmark và các giới hạn khoa học đã ghi trong handoff. Tệp PDF trong Downloads là bài báo B-Free, không phải rubric bài tập. Nếu có yêu cầu học phần cụ thể, đối chiếu với đề bài chính thức thay vì suy diễn từ bài báo.
