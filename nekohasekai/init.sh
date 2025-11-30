#!/usr/bin/env bash

PORT=${START_PORT:-1080}
SKIP_INIT=${SKIP_INIT:="false"}
WG_COUNT=${WG_COUNT:-2}

if [ "$SKIP_INIT" != "true" ]; then
python3 ./generator.py \
    --start-port "$PORT" \
    --shadowsocks \
    --verbose \
    --wg-pc "$WG_COUNT"
fi

# Letting docker-compose handle subsequence CMD instruction like python manage.py ... or gunicorn ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"
