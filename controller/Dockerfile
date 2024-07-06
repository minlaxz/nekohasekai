FROM python:3.11.3-alpine as base

WORKDIR /usr/src/app
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY ./requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements.txt


FROM python:3.11.3-alpine as dist

RUN mkdir -p /home/app
ENV APP_HOME=/home/app
WORKDIR ${APP_HOME}
RUN addgroup -S app && adduser -S app -G app

COPY --from=base /usr/src/app/wheels /wheels
COPY --from=base /usr/src/app/requirements.txt .
RUN pip install --no-cache /wheels/*
RUN rm -rf /wheels

COPY . .
RUN chown -R app:app $APP_HOME
USER app

CMD [ "python3", "-m" , "gunicorn", "-w", "4", "wsgi:app", "-b", "0.0.0.0:8000"]