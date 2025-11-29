#!/usr/bin/env bash

PORT=${START_PORT:-1080}
SERVER_WG_KEYPAIR=$(/sing-box/sing-box generate wg-keypair)
SERVER_WG_PRIVATE=$(awk -F': ' '/PrivateKey:/ {print $2}' <<< "$SERVER_WG_KEYPAIR")
SERVER_WG_PUBLIC=$(awk -F': ' '/PublicKey:/ {print $2}' <<< "$SERVER_WG_KEYPAIR")
CLIENT_WG_KEYPAIR=$(/sing-box/sing-box generate wg-keypair)
CLIENT_WG_PRIVATE=$(awk -F': ' '/PrivateKey:/ {print $2}' <<< "$CLIENT_WG_KEYPAIR")
CLIENT_WG_PUBLIC=$(awk -F': ' '/PublicKey:/ {print $2}' <<< "$CLIENT_WG_KEYPAIR")

python3 ./generator.py \
    --start-port "$PORT" \
    --shadowsocks \
    --verbose \
    --wg-priv ${CUSTOM_SERVER_WG_PRIVATE:-$SERVER_WG_PRIVATE} \
    --wg-pub ${CUSTOM_SERVER_WG_PUBLIC:-$SERVER_WG_PUBLIC} \
    --wg-client-pub ${CUSTOM_CLIENT_WG_PUBLIC:-$CLIENT_WG_PUBLIC} \
    --wg-client-priv ${CUSTOM_CLIENT_WG_PRIVATE:-$CLIENT_WG_PRIVATE}

/sing-box/sing-box run -C /sing-box/conf
