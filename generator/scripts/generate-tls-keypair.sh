#!/usr/bin/env bash

set -euo pipefail

SING_BOX="$HOME/.sekai-generator/sing-box"

if [[ ! -x "$SING_BOX" ]]; then
    echo "sing-box not installed. Run init --download"
    exit 1
fi

TLS_SERVER_NAME=$1
if [[ -z "$TLS_SERVER_NAME" ]]; then
    echo "TLS server name is required as the first argument"
    exit 1
fi

# Generate tls key pair
TLS_KEYPAIR=$("$SING_BOX" generate tls-keypair "$TLS_SERVER_NAME")
PRIVATE_KEY=$(sed -n '/-----BEGIN PRIVATE KEY-----/,/-----END PRIVATE KEY-----/p' <<< "$TLS_KEYPAIR")
PUBLIC_KEY=$(sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' <<< "$TLS_KEYPAIR")
printf '%s\n' "$PRIVATE_KEY" > $HOME/.sekai-generator/certs/private.key
printf '%s\n' "$PUBLIC_KEY" > $HOME/.sekai-generator/certs/certificate.crt

echo "TLS key pair has been generated successfully."
