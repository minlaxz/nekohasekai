#!/usr/bin/env bash

START_PORT=${START_PORT:-8040}
END_PORT=${END_PORT:-8050}
SKIP_INIT=${SKIP_INIT:-"false"}
WG_COUNT=${WG_COUNT:-0}

if [ "$SKIP_INIT" != "true" ]; then
python3 ./generator.py \
    --start-port "$START_PORT" \
    --end-port "$END_PORT" \
    --shadowsocks \
    --verbose \
    --wg-pc "$WG_COUNT"
fi

# Letting docker-compose handle subsequence CMD instruction like python manage.py ... or gunicorn ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"
