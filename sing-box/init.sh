#!/usr/bin/env bash

START_PORT=${START_PORT:-8040}
END_PORT=${END_PORT:-8050}
SKIP_CERTS=${SKIP_CERTS:-"false"}
SKIP_INIT=${SKIP_INIT:-"false"}

# Check certs dir has any certs, abort if so
if [ -d "certs" ] && [ "$(ls -A certs)" ]; then
  echo "Certs directory already exists and is not empty. "
  echo "ignored: TLS__SERVER_NAME: ${TLS__SERVER_NAME}"
  echo "ignored: ECH__SERVER_NAME: ${ECH__SERVER_NAME}"
  echo "Skipped certificate, reality keypair, ech keypair generations."
  printf '\n'
  SKIP_CERTS="true"
fi

if [ "$SKIP_CERTS" == "false" ]; then

  mkdir -p certs && \
  openssl ecparam -genkey -name prime256v1 -out certs/private.key && \
  openssl req -new -x509 -days 36500 \
    -key certs/private.key \
    -out certs/certificate.crt \
    -subj "/CN=${TLS__SERVER_NAME}" \
    -addext "subjectAltName=DNS:${TLS__SERVER_NAME}"

  REALITY_KEYPAIR=$(/sing-box/sing-box generate reality-keypair)
  AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
  AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
  REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
  REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}
  printf '%s\n' "$REALITY_PRIVATE" > certs/reality_private.key
  printf '%s\n' "$REALITY_PUBLIC" > certs/reality_public.key

  ECH_KEYPAIR=$(/sing-box/sing-box generate ech-keypair ${ECH__SERVER_NAME})
  AUTO_ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
  AUTO_ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
  ECH_PRIVATE=${CUSTOM_ECH_PRIVATE:-$AUTO_ECH_PRIVATE}
  ECH_PUBLIC=${CUSTOM_ECH_PUBLIC:-$AUTO_ECH_PUBLIC}
  printf '%s\n' "$ECH_PRIVATE" > certs/ech.key
  printf '%s\n' "$ECH_PUBLIC" > certs/ech.config
fi

if [ "$SKIP_INIT" != "true" ]; then
  echo "Initializing sing-box configuration ..."
  python3 ./main.py
fi

# Letting docker-compose handle subsequence CMD instruction like python ....py ... or fastapi ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"