FROM odoo:18.0

USER root

# 0. Cài đặt Tesseract OCR cho image processing
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-vie \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# 1. Lấy uv từ image chính chủ (Cách sạch nhất, không cần cài curl/wget)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 2. Dùng uv để cài đặt thư viện
# --system: Cài thẳng vào Python hệ thống (thay vì tạo venv)
# --break-system-packages: Cho phép ghi đè/cài cùng môi trường Debian quản lý
# Copy requirements và cài đặt
COPY addons/requirements.txt /tmp/requirements.txt
RUN uv pip install --system --break-system-packages -r /tmp/requirements.txt

USER odoo