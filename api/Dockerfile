FROM python:3.11-slim

WORKDIR /app

RUN pip install --upgrade pip

RUN pip install --no-cache-dir redis fastapi["standard"] uvicorn requests

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
