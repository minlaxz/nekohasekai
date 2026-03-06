FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip fastapi["standard"] uvicorn httpx python-dotenv fastapi-utils

COPY . .

EXPOSE 8000
