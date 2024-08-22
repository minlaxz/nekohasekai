#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
set -e

# If there's an .env file, exit the script
if [ -f .env ]; then
  echo -e "${RED}.env file already exists!${NC}"
  exit 1
fi

docker pull ghcr.io/sagernet/sing-box
sudo apt install curl
server_ip=$(curl -q ipinfo.io/ip)

read -p "Do you want to enable Multiplex? [Y/n]: " multiplex
if [ -z "$multiplex" ]; then
  multiplex="Y"
fi
if [ "$multiplex" == "Y" ] || [ "$multiplex" == "y" ]; then
echo "${GREEN}Multiplex is enabled!${NC}"
  cat <<EOF > .env
START_PORT=8800
SERVER_IP=
ARGO_DOMAIN=
ARGO_AUTH=
CDN=www.csgo.com
CUSTOM_UUID=
CUSTOM_REALITY_PRIVATE=
CUSTOM_REALITY_PUBLIC=
CUSTOM_SHADOWTLS_PASSWORD=
XTLS_REALITYX=true
HYSTERIA2=true
TUIC=true
SHADOWTLSX=true
SHADOWSOCKSX=true
TROJANX=true
VLESS_WSX=true
H2_REALITYX=true
GRPC_REALITYX=true
EOF
else
echo "${GREEN}Multiplex is disabled!${NC}"
  cat <<EOF > .env
START_PORT=8800
SERVER_IP=
ARGO_DOMAIN=
ARGO_AUTH=
CDN=www.csgo.com
CUSTOM_UUID=
CUSTOM_REALITY_PRIVATE=
CUSTOM_REALITY_PUBLIC=
CUSTOM_SHADOWTLS_PASSWORD=
XTLS_REALITY=true
HYSTERIA2=true
TUIC=true
SHADOWTLS=true
SHADOWSOCKS=true
TROJAN=true
VLESS_WS=true
H2_REALITY=true
GRPC_REALITY=true
EOF
fi

sed -i "s/^SERVER_IP=.*/SERVER_IP=$server_ip/" .env

echo "${GREEN}Server IP has been updated to: $server_ip${NC}"

new_uuid=$(docker run --rm ghcr.io/sagernet/sing-box generate uuid)

sed -i "s/^CUSTOM_UUID=.*/CUSTOM_UUID=$new_uuid/" .env

echo "${GREEN}CUSTOM_UUID has been updated to: $new_uuid${NC}"

reality_keypair=$(docker run --rm ghcr.io/sagernet/sing-box generate reality-keypair) && auto_reality_private=$(awk '/PrivateKey/{print $NF}' <<< "$reality_keypair") && auto_reality_public=$(awk '/PublicKey/{print $NF}' <<< "$reality_keypair")

sed -i "s/^CUSTOM_REALITY_PRIVATE=.*/CUSTOM_REALITY_PRIVATE=$auto_reality_private/" .env
sed -i "s/^CUSTOM_REALITY_PUBLIC=.*/CUSTOM_REALITY_PUBLIC=$auto_reality_public/" .env

echo "${GREEN}CUSTOM_REALITY_PRIVATE has been updated to: $auto_reality_private${NC}"
echo "${GREEN}CUSTOM_REALITY_PUBLIC has been updated to: $auto_reality_public${NC}"

shadowtls_password=$(docker run --rm ghcr.io/sagernet/sing-box generate rand --base64 16)

sed -i "s/^CUSTOM_SHADOWTLS_PASSWORD=.*/CUSTOM_SHADOWTLS_PASSWORD=$shadowtls_password/" .env

echo "${GREEN}CUSTOM_SHADOWTLS_PASSWORD has been updated to: $shadowtls_password${NC}"

echo -e "${GREEN}All configurations have been generated successfully!${NC}"
