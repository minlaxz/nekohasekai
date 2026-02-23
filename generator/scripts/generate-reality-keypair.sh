#!/usr/bin/env bash

set -euo pipefail


SING_BOX="$HOME/.sekai-generator/sing-box"

if [[ ! -x "$SING_BOX" ]]; then
    echo "sing-box not installed. Run init --download"
    exit 1
fi

# Generate reality key pair
REALITY_KEYPAIR=$("$SING_BOX" generate reality-keypair)
REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
printf '%s\n' "$REALITY_PRIVATE" > $HOME/.sekai-generator/certs/reality_private.key
printf '%s\n' "$REALITY_PUBLIC" > $HOME/.sekai-generator/certs/reality_public.key

echo "Reality key pair has been generated successfully."
