#!/usr/bin/env bash

set -euo pipefail


SING_BOX="$HOME/.sekai-generator/sing-box"

if [[ ! -x "$SING_BOX" ]]; then
    echo "sing-box not installed. Run init --download"
    exit 1
fi

ECH_SERVER_NAME=$1
if [[ -z "$ECH_SERVER_NAME" ]]; then
    echo "ECH server name is required as the first argument"
    exit 1
fi

# Generate ECH key pair
ECH_KEYPAIR=$("$SING_BOX" generate ech-keypair "$ECH_SERVER_NAME")
ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
printf '%s\n' "$ECH_PUBLIC" > $HOME/.sekai-generator/certs/ech.config
printf '%s\n' "$ECH_PRIVATE" > $HOME/.sekai-generator/certs/ech.key

echo "ECH key pair has been generated successfully."
