#!/usr/bin/env bash

set -euo pipefail

SING_BOX="$HOME/.sekai-generator/sing-box"

# Check if sing-box is installed

if [[ ! -x "$SING_BOX" ]]; then
    echo "sing-box not installed. Run init --download"
    exit 1
fi

# If reality_private.key and reality_public.key already exist, skip generation

if [[ -f "$HOME/.sekai-generator/certs/reality_private.key" && -f "$HOME/.sekai-generator/certs/reality_public.key" ]]; then
    echo "Reality key pair already exists. Skipping generation."
    exit 0
fi

# Generate reality key pair

REALITY_KEYPAIR=$("$SING_BOX" generate reality-keypair)
REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
printf '%s\n' "$REALITY_PRIVATE" > $HOME/.sekai-generator/certs/reality_private.key
printf '%s\n' "$REALITY_PUBLIC" > $HOME/.sekai-generator/certs/reality_public.key

echo "Reality key pair has been generated successfully."
