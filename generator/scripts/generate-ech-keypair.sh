#!/usr/bin/env bash

set -euo pipefail

# Check sing-box is installed
if ! command -v sing-box &> /dev/null; then
    echo "sing-box is not installed. Please run dl-sing-box.sh first."
    exit 1
fi

# Generate ECH key pair
ECH_KEYPAIR=$(sing-box generate ech-keypair google.com)
ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
printf '%s\n' "$ECH_PUBLIC" > ech.config
printf '%s\n' "$ECH_PRIVATE" > ech.key

echo "ECH key pair has been generated successfully."