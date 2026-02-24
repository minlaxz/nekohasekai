#!/usr/bin/env bash

set -euo pipefail

SING_BOX_VERSION=1.12.22

SING_BOX="$HOME/.sekai-generator/sing-box"

if [[ -x "$SING_BOX" ]]; then
    echo "sing-box already installed. Skipping installation."
    exit 0
fi

# Check the architecture

ARCH=$(uname -m)
if [[ "$ARCH" == "x86_64" ]]; then
    SING_BOX_ARCH=amd64
elif [[ "$ARCH" == "aarch64" ]]; then
    SING_BOX_ARCH=arm64
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

mkdir -p "$HOME/.sekai-generator"

SING_BOX_URL="https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}.tar.gz"
SING_BOX_PATH="$HOME/.sekai-generator"

curl -sL -o /tmp/sing-box.tar.gz "$SING_BOX_URL"
tar -xzf /tmp/sing-box.tar.gz --strip-components=1 -C "$SING_BOX_PATH"
rm /tmp/sing-box.tar.gz
# Optional
chmod +x $SING_BOX_PATH

echo "${SING_BOX_VERSION} has been installed successfully to $SING_BOX_PATH."
