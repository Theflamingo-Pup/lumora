# =============================================================
# Lumora API Dockerfile
# =============================================================
# Phase 1 update: copies BOTH main.py and auth.py.
# Easy bug to hit when adding a new Python module - the Dockerfile
# only copies what you tell it to. Forgetting one file means the
# container starts but immediately ModuleNotFoundError's.
# =============================================================
FROM python:3.12-slim

WORKDIR /app

# Install Python deps first (cached layer - rebuilds skip this
# unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ALL Python source files. As you add more modules, list them here.
COPY main.py .
COPY auth.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
