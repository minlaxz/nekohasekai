FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip redis fastapi["standard"] uvicorn

COPY . .

EXPOSE 8000
