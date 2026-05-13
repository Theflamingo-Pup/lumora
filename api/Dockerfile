# =============================================================
# Lumora API Dockerfile
# =============================================================
# Phase 2b update: copies main.py + auth.py + photos.py.
# =============================================================
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# All Python source files
COPY main.py .
COPY auth.py .
COPY photos.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
