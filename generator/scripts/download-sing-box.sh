#!/usr/bin/env bash

set -euo pipefail

SING_BOX_VERSION=1.12.22

ARCH=$(uname -m)
if [[ "$ARCH" == "x86_64" ]]; then
    SING_BOX_ARCH=amd64
elif [[ "$ARCH" == "aarch64" ]]; then
    SING_BOX_ARCH=arm64
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

SING_BOX_URL="https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-${SING_BOX_ARCH}.tar.gz"

curl -sL -o /tmp/sing-box.tar.gz "$SING_BOX_URL"
# tar -xzf /tmp/sing-box.tar.gz -C /usr/local/bin --strip-components=1 && rm /tmp/sing-box.tar.gz LICENSE
tar -xzf /tmp/sing-box.tar.gz --strip-components=1 && rm /tmp/sing-box.tar.gz LICENSE

echo "Sing-Box version ${SING_BOX_VERSION} has been installed successfully."
