#!/usr/bin/env bash

WORK_DIR=/sing-box
makdir -p $WORK_DIR/conf
makdir -p $WORK_DIR/public
PORT=${START_PORT:-1080}
TEMPLATE_PATH="https://raw.githubusercontent.com/minlaxz/nekohasekai/main/singbox/v2/sing-box-template"

warning() { echo -e "\033[31m\033[01m$*\033[0m"; }
info() { echo -e "\033[32m\033[01m$*\033[0m"; }
hint() { echo -e "\033[33m\033[01m$*\033[0m"; }

setting_things_up() {
  SERVER_IP="$(wget -q -O- https://ipecho.net/plain)"

  if [[ "$SERVER_IP" =~ : ]]; then
    local DOMAIN_STRATEGY=prefer_ipv4
  else
    local DOMAIN_STRATEGY=ipv4_only
  fi

  local SHADOWTLS_PASSWORD=${CUSTOM_SHADOWTLS_PASSWORD:-"$($WORK_DIR/sing-box generate rand --base64 16)"}
  local UUID=${CUSTOM_UUID:-"$($WORK_DIR/sing-box generate uuid)"}
  local NODE_NAME=${NODE_NAME:-"sing-box"}

  cat > $WORK_DIR/conf/00_log.json << EOF
  {
      "log": {
          "level": "warn",
          "timestamp": true,
          "output": "$WORK_DIR/sing.log"
      }
  }
EOF

  cat > $WORK_DIR/conf/01_outbounds.json << EOF
  {
      "outbounds": [
          {
              "type": "direct",
              "tag": "direct-out",
              "domain_resolver": {
                  "server": "local",
                  "strategy": "${DOMAIN_STRATEGY}"
              }
          }
      ]
  }
EOF

  cat > $WORK_DIR/conf/02_route.json << EOF
  {
      "route": {
          "rule_set": [],
          "rules": []
      }
  }
EOF

  cat > $WORK_DIR/conf/03_experimental.json << EOF
  {
      "experimental": {
          "clash_api": {
              "external_controller": "0.0.0.0:8820",
              "external_ui": "metacubexd",
              "external_ui_download_url": "https://github.com/MetaCubeX/metacubexd/archive/refs/heads/gh-pages.zip",
              "external_ui_download_detour": "direct",
              "default_mode": "rule"
          },
          "cache_file": {
              "enabled": true,
              "path": "$WORK_DIR/cache.db"
          }
      }
  }
EOF

  cat > $WORK_DIR/conf/04_dns.json << EOF
  // As no sniff in outbound, have no effect on this as well
  {
      "dns":{
          "servers": [
              {
                  "type": "local",
                  "tag": "local"
              }
          ]
      }
  }
EOF

  [ "${SHADOWSOCKS}" = 'true' ] && ((PORT++)) && PORT_SHADOWSOCKS=$PORT && cat > $WORK_DIR/conf/${PORT_SHADOWSOCKS}_shadowsocks_inbounds.json << EOF
  {
      "inbounds": [
          {
              "type": "shadowsocks",
              "tag": "${NODE_NAME} shadowsocks",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SHADOWSOCKS},
              "network": "tcp",
              "method": "chacha20-ietf-poly1305",
              "password": "${SHADOWTLS_PASSWORD}"
          }
      ]
  }
EOF

  [ "${SHADOWSOCKSX}" = 'true' ] && ((PORT++)) && PORT_SHADOWSOCKS=$PORT && cat > $WORK_DIR/conf/${PORT_SHADOWSOCKS}_shadowsocks_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "shadowsocks",
              "tag": "${NODE_NAME} shadowsocks",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SHADOWSOCKS},
              "network": "tcp",
              "method": "chacha20-ietf-poly1305",
              "password": "${SHADOWTLS_PASSWORD}",
              "multiplex": {
                  "enabled": true,
                  "padding": true
              }
          }
      ]
  }
EOF

  [ "${HTTP}" = 'true' ] && ((PORT++)) && PORT_HTTP=$PORT && cat > $WORK_DIR/conf/${PORT_HTTP}_http_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "http",
              "tag": "${NODE_NAME} http",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_HTTP},
              "users": [],
              "set_system_proxy": false
          }
      ]
  }
EOF

  [ "${HTTP}" = 'true' ] && ((PORT++)) && PORT_HTTP_DETOUR=$PORT && cat > $WORK_DIR/conf/${PORT_HTTP_DETOUR}_http_detour_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "http",
              "tag": "${NODE_NAME} http-detour",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_HTTP_DETOUR},
              "users": [],
              "set_system_proxy": false,
              "detour": "${NODE_NAME} shadowsocks"
          }
      ]
  }
EOF

  [ "${SOCKS}" = 'true' ] && ((PORT++)) && PORT_SOCKS=$PORT && cat > $WORK_DIR/conf/${PORT_SOCKS}_socks_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "socks",
              "tag": "${NODE_NAME} socks",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SOCKS},
              "users": []
          }
      ]
  }
EOF

[ "${SHADOWSOCKS}" = 'true' ] &&
local INBOUND_REPLACE+=" { \"type\": \"shadowsocks\", \"tag\": \"${NODE_NAME} shadowsocks\", \"server\": \"${SERVER_IP}\", \"domain_strategy\": \"ipv4_only\", \"server_port\": $PORT_SHADOWSOCKS, \"method\": \"chacha20-ietf-poly1305\", \"password\": \"${SHADOWTLS_PASSWORD}\" }," &&
local NODE_REPLACE+="\"${NODE_NAME} shadowsocks\","

[ "${SHADOWSOCKSX}" = 'true' ] &&
local INBOUND_REPLACE+=" { \"type\": \"shadowsocks\", \"tag\": \"${NODE_NAME} shadowsocks\", \"server\": \"${SERVER_IP}\", \"domain_strategy\": \"ipv4_only\", \"server_port\": $PORT_SHADOWSOCKS, \"method\": \"chacha20-ietf-poly1305\", \"password\": \"${SHADOWTLS_PASSWORD}\", \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true } }," &&
local NODE_REPLACE+="\"${NODE_NAME} shadowsocks\","

local SING_BOX_JSON=$(wget -qO- --tries=3 --timeout=2 ${TEMPLATE_PATH})
echo $SING_BOX_JSON | sed 's#, {[^}]\+"tun-in"[^}]\+}##' | sed "s#\"<INBOUND_REPLACE>\",#$INBOUND_REPLACE#; s#\"<NODE_REPLACE>\"#${NODE_REPLACE%,}#g" | jq > $WORK_DIR/public/sing-box-pc

}

setting_things_up

info "Starting sing-box..."
/sing-box/sing-box run -C $WORK_DIR/conf