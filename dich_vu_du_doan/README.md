---
title: KLTN Churn Service
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Dịch vụ dự đoán nguy cơ rời bỏ (nguyên mẫu AI Agent – KLTN)

Dịch vụ chỉ đọc, phục vụ năm công cụ của Agent (Bảng 3.16): `get_customer`, `predict_risk`,
`explain_customer`, `count_by_group`, `list_customers`. Mô hình: HistGradientBoosting, phương án P0,
cấu hình ban đầu, không hiệu chỉnh; ngưỡng t* ≈ 0,3594; điểm S = min(10; 1 + ⌊10p⌋); nhóm thấp 1–2,
trung bình 3–5, cao 6–10. Dữ liệu CRM thử nghiệm: 1.015 hồ sơ holdout, không chứa nhãn Churn.

- Khóa truy cập: đặt biến bí mật `SERVICE_API_KEY` (Settings → Variables and secrets → New secret).
  Mọi lời gọi `POST /tools/<tên công cụ>` phải gửi header `X-API-Key`.
- Kiểm tra hoạt động: `GET /health`.
- Mã băm của mô hình, metadata và dữ liệu CRM được kiểm tra trước khi tải (`model/manifest.json`).
- Kiểm thử cục bộ: `pip install -r requirements.txt pytest httpx && pytest -q`.
