#!/usr/bin/env bash

REALITY_KEYPAIR=$(/sing-box/sing-box generate reality-keypair)
AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}

HANDSHAKE_DOMAIN=${HANDSHAKE_DOMAIN:-"addons.mozilla.org"}
START_PORT=${START_PORT:-8040}
END_PORT=${END_PORT:-8050}
SKIP_INIT=${SKIP_INIT:-"false"}
WG_COUNT=${WG_COUNT:-0}

if [ "$SKIP_INIT" != "true" ]; then
python3 ./generator.py \
    --start-port "$START_PORT" \
    --end-port "$END_PORT" \
    --shadowsocks \
    --trojan \
    --handshake-domain "$HANDSHAKE_DOMAIN" \
    --reality-privatekey "$REALITY_PRIVATE" \
    --reality-publickey "$REALITY_PUBLIC" \
    --verbose \
    --wg-pc "$WG_COUNT"
fi

# Letting docker-compose handle subsequence CMD instruction like python manage.py ... or gunicorn ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"
