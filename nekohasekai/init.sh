#!/usr/bin/env bash

REALITY_KEYPAIR=$(/sing-box/sing-box generate reality-keypair)
AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}

HANDSHAKE_DOMAIN=${HANDSHAKE_DOMAIN}
START_PORT=${START_PORT:-8040}
END_PORT=${END_PORT:-8050}
SKIP_INIT=${SKIP_INIT:-"false"}


if [ "$SKIP_INIT" != "true" ]; then
mkdir -p certs && \

openssl ecparam -genkey -name prime256v1 -out certs/private.key && \
openssl req -new -x509 -days 36500 \
  -key certs/private.key \
  -out certs/cert.pem \
  -subj "/CN=${HANDSHAKE_DOMAIN}" \
  -addext "subjectAltName=DNS:${HANDSHAKE_DOMAIN}"

python3 ./main.py \
    --start-port "$START_PORT" \
    --end-port "$END_PORT"
fi

# Letting docker-compose handle subsequence CMD instruction like python ....py ... or fastapi ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"
