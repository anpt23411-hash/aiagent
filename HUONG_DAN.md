# Nguyên mẫu AI Agent đánh giá nguy cơ rời bỏ – hướng dẫn triển khai và đánh giá

Gói này hiện thực thiết kế ở mục 3.10–3.11 của khóa luận: Tools Agent trên n8n gọi năm công cụ chỉ đọc (Bảng 3.16) của một dịch vụ dự đoán Python chứa pipeline đã lưu (HistGradientBoosting P0, t* ≈ 0,3594, điểm 1–10, nhóm thấp 1–2 / trung bình 3–5 / cao 6–10), trình bày báo cáo theo Bảng 3.17 và xử lý ngoại lệ theo Bảng 3.18.

```
agent_kltn/
├── dich_vu_du_doan/        → tải lên Hugging Face Space (Docker)
│   ├── app.py, core.py     dịch vụ FastAPI và lõi tính toán
│   ├── src/                3 tệp gốc của dự án (cần để tải pipeline.joblib)
│   ├── model/              pipeline.joblib, metadata.json, manifest.json (mã băm)
│   ├── data/               crm_holdout.csv (1.015 hồ sơ holdout, KHÔNG có cột Churn), tu_dien_du_lieu.csv
│   ├── Dockerfile, requirements.txt, README.md
│   └── tests/              kiểm thử (pytest)
├── n8n/
│   ├── workflow_ai_agent.json      → import vào n8n
│   └── chi_dan_he_thong_v1.md      chỉ dẫn hệ thống v1.0 (đã nằm sẵn trong node AI Agent)
└── danh_gia/
    ├── tao_bo_tinh_huong.py        tạo 72 tình huống T1–T9, kết quả kỳ vọng gọi thẳng từ dịch vụ
    ├── chay_danh_gia.py            chạy k lần qua webhook, chấm điểm, tổng hợp chỉ số Bảng 3.20
    ├── cham_diem.py, test_cham_diem.py
```

## Bước 1. Deploy dịch vụ dự đoán lên Hugging Face Spaces (miễn phí)

1. Tạo tài khoản tại huggingface.co → **New Space** → đặt tên (ví dụ `kltn-churn`) → **SDK: Docker** (Blank) → phần cứng **CPU basic (free)** → **Create Space**.
   Chế độ **Public** là đơn giản nhất: dịch vụ vẫn được khóa bằng `X-API-Key`, nhưng mã nguồn, tệp mô hình và dữ liệu CRM thử nghiệm (dữ liệu Kaggle công khai) sẽ xem được trong tab Files.
2. Tải toàn bộ nội dung thư mục `dich_vu_du_doan/` lên Space, giữ nguyên thư mục con (`src/`, `model/`, `data/`):
   - Cách kéo thả: tab **Files** → **Add file → Upload files** → kéo các tệp và thư mục vào → **Commit**. Sau đó kiểm tra đường dẫn hiển thị đúng dạng `model/pipeline.joblib`, `src/thesis_preprocessing.py`.
   - Hoặc dòng lệnh: `pip install -U huggingface_hub`, `hf auth login`, rồi trong thư mục `dich_vu_du_doan`: `hf upload TEN_TAI_KHOAN/kltn-churn . . --repo-type space`.
3. **Settings → Variables and secrets → New secret**: tên `SERVICE_API_KEY`, giá trị là một chuỗi ngẫu nhiên dài (giữ lại để dùng ở Bước 2).
4. Đợi tab **Logs** báo build xong và Space ở trạng thái *Running*. Mở `https://TEN_TAI_KHOAN-kltn-churn.hf.space/health` (chữ thường; dấu `_` trong tên đổi thành `-`): phải thấy `"crm_records": 1015`.
   Space miễn phí ngủ sau một thời gian không dùng; mở lại `/health` và chờ Space chạy trước khi chat hoặc đánh giá.

## Bước 2. Import workflow vào n8n

1. n8n → **Workflows → Import from File** → chọn `n8n/workflow_ai_agent.json`.
2. Gắn credential (không có khóa nào nằm trong tệp JSON):
   - **OpenAI Chat Model** → credential OpenAI (API key). Mặc định `gpt-4.1`, Temperature 0. Nếu đổi sang model suy luận (gpt-5…, o…), xóa tùy chọn Temperature.
   - **Gọi dịch vụ dự đoán** → Credential type *Header Auth*: Name `X-API-Key`, Value = `SERVICE_API_KEY` ở Bước 1.
   - **Webhook kiểm thử** → *Header Auth*: Name `X-Test-Key`, Value = một chuỗi ngẫu nhiên khác (dùng cho tập lệnh đánh giá).
3. **Cấu hình dịch vụ (điền tại đây)** → `dich_vu_url` = `https://TEN_TAI_KHOAN-kltn-churn.hf.space` (không có `/` ở cuối).
4. **Save**. Năm công cụ gọi lại chính workflow này bằng ID, nên luôn lưu trước khi chat.

## Bước 3. Chạy thử

Bấm **Open chat** (node *Khi có tin nhắn chat*) và thử lần lượt:
- `Khách 50012 có nguy cơ rời bỏ cao không?` → báo cáo 6 phần theo Bảng 3.17.
- `Vì sao khách 50012 có mức nguy cơ như vậy?`, `Có bao nhiêu khách hàng nguy cơ cao ở CityTier 3?`, `Liệt kê 10 khách hàng nguy cơ cao nhất`.
- Ngoại lệ: `Khách 50001 có nguy cơ không?` (không có trong CRM thử nghiệm), `Khách ABC12…`, `Khách này có sao không?`, `Nên tặng khách 50012 mã giảm giá bao nhiêu?`.
Mở **Executions** để xem từng bước: công cụ được gọi, tham số, kết quả JSON, token của node OpenAI.

## Bước 4. Đánh giá theo mục 3.11

1. Bật workflow (**Publish/Active**) để dùng địa chỉ *Production URL* của node **Webhook kiểm thử** (dạng `https://TEN.app.n8n.cloud/webhook/kltn-agent-kiem-thu`).
2. Tạo bộ tình huống (chỉ cần Python 3.9+, không cài thêm gì):
   `python tao_bo_tinh_huong.py --url https://TEN_TAI_KHOAN-kltn-churn.hf.space --key SERVICE_API_KEY`
   → `bo_tinh_huong.json` / `.csv`: 72 tình huống, 27 phần phát triển, 45 phần đánh giá; mã khách hàng phủ ba nhóm, hồ sơ thiếu dữ liệu, gần t* và gần ranh giới nhóm.
3. Giai đoạn phát triển (được phép chỉnh chỉ dẫn hệ thống và mô tả công cụ):
   `python chay_danh_gia.py --webhook PRODUCTION_URL --khoa-kiem-thu GIA_TRI_X_TEST_KEY --phan phat_trien --k 1`
   Nếu sửa chỉ dẫn hệ thống, đổi số phiên bản ở dòng đầu (ví dụ `v1.1`); phản hồi và kết quả đánh giá tự ghi phiên bản này.
4. Lượt đánh giá cuối (không chỉnh gì sau khi bắt đầu):
   `python chay_danh_gia.py --webhook PRODUCTION_URL --khoa-kiem-thu ... --phan danh_gia --k 3 --ten-mo-hinh "gpt-4.1 (ghi đúng phiên bản)" --don-gia-vao GIA --don-gia-ra GIA --out ket_qua_cuoi`
   Kết quả: `tong_hop.md` / `tong_hop.json` (tỷ lệ đúng công cụ, tham số, hồ sơ, lời gọi thừa, khớp giá trị, số giá trị tự tạo, tỷ lệ hoàn thành, pass^k, thời gian trung vị/p95), `ket_qua_tung_lan.csv`, và `cham_giai_thich_thu_cong.csv` để người chấm xác nhận bốn tiêu chí giải thích (3.11.4).
   Token và chi phí: nếu gói n8n có API, thêm `--n8n-api-url https://TEN.app.n8n.cloud --n8n-api-key ...`; nếu không, lấy tổng token theo ngày đánh giá trong trang Usage của OpenAI rồi chia cho số lần chạy.
5. Lưu ý hạn mức: mỗi lần chạy Agent và mỗi lần gọi công cụ (quy trình con) đều tạo một execution trên n8n. Với 45 tình huống × k = 3 cần khoảng 135 lượt Agent và vài trăm lượt công cụ; kiểm tra hạn mức execution của gói n8n Cloud đang dùng trước khi chạy.

## Những điểm khác hoặc cần bổ sung so với thiết kế đang viết ở mục 3.10–3.11

- Nền tảng: n8n Cloud và dịch vụ trên Hugging Face Spaces (Docker), thay cho n8n tự cài bằng Docker như câu chữ hiện tại của 3.10. Ghi phiên bản n8n Cloud tại ngày đánh giá (Settings → About n8n).
- Môi trường dịch vụ: thư viện trùng phiên bản lúc huấn luyện (scikit-learn 1.9.1, imbalanced-learn 0.14.2, SHAP 0.54.1, NumPy 2.5.4, pandas 3.1.0); Python 3.13 thay vì 3.15.1 ghi trong metadata (công cụ cài đặt dùng khi kiểm thử chỉ có Python 3.15 bản thử nghiệm 3.15.0b4; kiểm thử cũng đạt trên bản này). Xác suất tính lại cho 1.015 hồ sơ holdout khớp dự đoán đã lưu (sai khác tối đa 1,1×10⁻¹⁶; kiểm thử `tests/`).
- Năm node Call n8n Workflow Tool trỏ đến một quy trình con dùng chung nằm trong cùng workflow (node *Khi Agent gọi công cụ*), định tuyến theo tên công cụ, thay vì năm quy trình con riêng.
- Đánh giá chạy bằng tập lệnh Python qua webhook (phương án dự phòng đã nêu ở 3.11), không dùng chức năng Evaluations/Data table của n8n.
- Thông số cần điền khi viết lại: LLM `gpt-4.1` (ghi phiên bản chính xác), Temperature 0, Max Iterations 6, Simple Memory 6 lượt, chỉ dẫn hệ thống v1.0, dịch vụ 1.0.0, mô hình `hist_gradient_boosting/P0/untuned sha256:3a3694f82dd6`.

## Giới hạn đã biết

- Bộ chấm tự động dùng quy tắc so khớp chuỗi tiếng Việt; tiêu chí giải thích chỉ là chấm sơ bộ và cần người chấm xác nhận. Kết quả ở `ket_qua_tung_lan.csv` cho phép xem lại từng lần chạy.
- Tham số "đúng" được so với kỳ vọng của từng tình huống; với câu "nguy cơ cao nhất", lựa chọn thêm nhóm "cao" chỉ được chấp nhận khi trả về đúng cùng danh sách.
- Giải thích SHAP mô tả cơ sở của dự đoán, không phải nguyên nhân rời bỏ; Agent không đề xuất ưu đãi hay can thiệp (Bảng 3.17, tình huống T9).
