# Dịch vụ dự đoán cho nguyên mẫu AI Agent – chạy trên Hugging Face Spaces (Docker) hoặc bất kỳ máy chủ Docker nào.
# Thư viện trùng phiên bản với môi trường huấn luyện (requirements.txt). Python 3.13 là bản ổn định đã kiểm thử:
# xác suất tính lại cho 1.015 hồ sơ holdout khớp dự đoán đã lưu (sai khác ≤ 1e-12, xem tests/).
ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user . .
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
