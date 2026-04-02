FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir \
    fastapi["standard"]==0.128.1 \
    uvicorn==0.40.0 \
    httpx==0.28.1 \
    python-dotenv==1.2.2 \
    apscheduler==3.11.2

COPY . .

EXPOSE 8000
