#!/usr/bin/env bash

set -euo pipefail

mkdir -p "$HOME/.sekai-generator/configs"
mkdir -p "$HOME/.sekai-generator/certs"
mkdir -p "$HOME/.sekai-generator/logs"
mkdir -p "$HOME/.sekai-generator/cache"
mkdir -p "$HOME/.sekai-generator/public"

TEMPLATE_URL="https://raw.githubusercontent.com/nekohasekai/master/generator/templates"

# Download all templates
curl -sL -o "$HOME/.sekai-generator/configs/dns.json" "$TEMPLATE_URL/dns.json"
curl -sL -o "$HOME/.sekai-generator/configs/endpoints.json" "$TEMPLATE_URL/endpoints.json"
curl -sL -o "$HOME/.sekai-generator/configs/experimental.json" "$TEMPLATE_URL/experimental.json"
curl -sL -o "$HOME/.sekai-generator/configs/log.json" "$TEMPLATE_URL/log.json"
curl -sL -o "$HOME/.sekai-generator/configs/outbounds.json" "$TEMPLATE_URL/outbounds.json"
curl -sL -o "$HOME/.sekai-generator/configs/route.json" "$TEMPLATE_URL/route.json"
curl -sL -o "$HOME/.sekai-generator/configs/services.json" "$TEMPLATE_URL/services.json"

echo "Template files have been downloaded successfully to $HOME/.sekai-generator/configs."