FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Yahan 'ai-viral-clipper/' lagana zaroori hai
COPY ai-viral-clipper/requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY ai-viral-clipper/src/ /app/src/
COPY ai-viral-clipper/assets/ /app/assets/
COPY ai-viral-clipper/main.py /app/main.py
COPY frontend/ /app/frontend/

RUN mkdir -p /app/workspace/raw_videos /app/workspace/temp /app/workspace/final_shorts

EXPOSE 10000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
