FROM python:3.11-slim

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/vault/cache/huggingface \
    KOKORO_MODELS_DIR=/data/vault/cache/kokoro

# Install system dependencies including ffmpeg for audio transcoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    docker.io \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Fail the image build if the Docker client was not installed.
RUN docker --version

WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create volume mount directory for encrypted vault storage
RUN mkdir -p /data/vault /data/vault/cache

EXPOSE 8000

# Start FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
