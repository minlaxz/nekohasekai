#!/usr/bin/env bash

set -euo pipefail

# Check sing-box is installed
if ! command -v sing-box &> /dev/null; then
    echo "sing-box is not installed. Please run dl-sing-box.sh first."
    exit 1
fi

# Generate reality key pair
REALITY_KEYPAIR=$(sing-box generate reality-keypair)
REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
printf '%s\n' "$REALITY_PRIVATE" > reality_private.key
printf '%s\n' "$REALITY_PUBLIC" > reality_public.key

echo "Reality key pair has been generated successfully."
