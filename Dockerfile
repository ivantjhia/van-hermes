# Gunakan image Python yang ringan
FROM python:3.11-slim

# Set environment variable agar log langsung muncul di konsol Koyeb
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Buat direktori kerja di dalam container
WORKDIR /app

# Instal pustaka sistem yang dasar
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Menyalin berkas kebutuhan dependency
COPY requirements.txt .

# Instal pustaka Python
RUN pip install --no-cache-dir -r requirements.txt

# Menyalin seluruh kode agen ke dalam container
COPY . .

HEALTHCHECK NONE

# Jalankan skrip utama Hermes Agent saat container dinyalakan
CMD ["python", "main.py"]
