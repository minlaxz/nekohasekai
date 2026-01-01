FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip redis fastapi["standard"] uvicorn PyYAML
# fastapi-restful is not used currently

# app, templates
COPY . .

EXPOSE 8000

# HEALTHCHECK --interval=10s --timeout=1s --start-period=5s --retries=3 \
#   CMD curl -f http://localhost:8000 || exit 1
