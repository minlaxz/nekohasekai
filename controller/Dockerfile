FROM --platform=linux/amd64 python:3.11.9-slim as base

WORKDIR /usr/src/app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update -q \
    && apt-get install --no-install-recommends \
    gcc g++ make -yqq

COPY ./requirements.txt .
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --no-deps \
    --wheel-dir /usr/src/app/wheels \
    -r requirements.txt


FROM --platform=linux/amd64 python:3.11.9-slim as dist

WORKDIR /home/app
RUN apt-get update -q \
    && apt-get install --no-install-recommends \
    ncat gcc g++ make \
    -yqq && rm -rf /var/lib/apt/lists/*

RUN useradd -m -d /home/app -s /bin/bash -c "Container User" -u 1000 app

COPY --from=base /usr/src/app/wheels /wheels
COPY --from=base /usr/src/app/requirements.txt .
RUN pip install --no-cache /wheels/* && rm -rf /wheels

COPY . .
# RUN sed -i 's/\r$//g' ./entrypoint.sh && chmod +x ./entrypoint.sh
RUN chown -R app:app .
USER app

EXPOSE 8000

CMD ["gunicorn", "-w", "3", "--bind", "0.0.0.0:8000", "wsgi:app"]
