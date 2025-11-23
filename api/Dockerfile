FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip redis fastapi["standard"] uvicorn requests

COPY . .

EXPOSE 8000

# See more options at https://fastapi.tiangolo.com/deployment/docker/
CMD ["fastapi", "run", "api/app/main.py", "--port", "8000", "--proxy-headers"]
