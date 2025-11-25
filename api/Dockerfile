FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip redis fastapi["standard"] uvicorn
# fastapi_restful is not used currently

# app, templates
COPY . .

EXPOSE 8000

# See more options at https://fastapi.tiangolo.com/deployment/docker/
CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--proxy-headers"]
