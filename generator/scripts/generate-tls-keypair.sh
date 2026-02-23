#!/usr/bin/env bash

set -euo pipefail

# Check sing-box is installed
if ! command -v sing-box &> /dev/null; then
    echo "sing-box is not installed. Please run dl-sing-box.sh first."
    exit 1
fi

# Generate tls key pair
TLS_KEYPAIR=$(sing-box generate tls-keypair mozilla.org)
PRIVATE_KEY=$(sed -n '/-----BEGIN PRIVATE KEY-----/,/-----END PRIVATE KEY-----/p' <<< "$TLS_KEYPAIR")
PUBLIC_KEY=$(sed -n '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/p' <<< "$TLS_KEYPAIR")
printf '%s\n' "$PRIVATE_KEY" > private.key
printf '%s\n' "$PUBLIC_KEY" > certificate.crt

echo "TLS key pair has been generated successfully."
