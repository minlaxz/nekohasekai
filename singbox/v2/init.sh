#!/usr/bin/env bash

WORK_DIR=/sing-box
mkdir -p $WORK_DIR/conf
mkdir -p $WORK_DIR/public
PORT=${START_PORT:-1080}
# TEMPLATE_PATH="https://raw.githubusercontent.com/minlaxz/nekohasekai/main/singbox/v2/sing-box-template"

warning() { echo -e "\033[31m\033[01m$*\033[0m"; }
info() { echo -e "\033[32m\033[01m$*\033[0m"; }
hint() { echo -e "\033[33m\033[01m$*\033[0m"; }

upupup() {
  SERVER_IP="$(wget -q -O- https://ipecho.net/plain)"

  if [[ "$SERVER_IP" =~ : ]]; then
    local DOMAIN_STRATEGY=ipv6_only
  else
    local DOMAIN_STRATEGY=ipv4_only
  fi

  local SS_ENCRYPTION_METHOD=${CUSTOM_SS_ENCRYPTION_METHOD:="chacha20-ietf-poly1305"}
  local SS_ENCRYPTION_PASSWORD=${CUSTOM_SS_ENCRYPTION_PASSWORD:-"$($WORK_DIR/sing-box generate rand --base64 16)"}
  local REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-AUTO_REALITY_PRIVATE}
  local REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-AUTO_REALITY_PUBLIC}
  local UUID=${CUSTOM_UUID:-"$($WORK_DIR/sing-box generate uuid)"}


#   local UUID=${CUSTOM_UUID:-"$($WORK_DIR/sing-box generate uuid)"}
#   local NODE_NAME=${NODE_NAME:-"sing-box"}

  cat > $WORK_DIR/conf/00_log.json << EOF
  {
      "log": {
          "level": "warn",
          "timestamp": true,
          "output": "$WORK_DIR/sing.log"
      }
  }
EOF
    hint "Generated log config."

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
    hint "Generated outbound config."

  cat > $WORK_DIR/conf/02_route.json << EOF
  {
      "route": {
          "rule_set": [],
          "rules": []
      }
  }
EOF
    hint "Generated route config."

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
    hint "Generated clash config."

  cat > $WORK_DIR/conf/04_dns.json << EOF
  // As no sniff in outbound, do not affect this as well
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
    hint "Generated dns config."

  [ "${XTLS_REALITY}" = 'true' ] && ((PORT++)) && PORT_XTLS_REALITY=$PORT && cat > $WORK_DIR/conf/${PORT_XTLS_REALITY}_xtls-reality_inbounds.json << EOF
  //  "public_key": "${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type": "vless",
              "tag": "xtls-reality",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_XTLS_REALITY},
              "users": [
                  {
                      "uuid": "${UUID}",
                      "flow": ""
                  }
              ],
              "tls": {
                  "enabled": true,
                  "server_name": "fast.com",
                  "reality": {
                      "enabled": true,
                      "handshake": {
                          "server": "fast.com",
                          "server_port": 443
                      },
                      "private_key": "${REALITY_PRIVATE}",
                      "short_id": [
                          ""
                      ]
                  }
              }
          }
      ]
  }
EOF
    [ "${XTLS_REALITY}" = 'true' ] && hint "Generated xtls-reality inbound config."

  [ "${XTLS_REALITYX}" = 'true' ] && ((PORT++)) && PORT_XTLS_REALITY=$PORT && cat > $WORK_DIR/conf/${PORT_XTLS_REALITY}_xtls-reality_inbounds.json << EOF
  //  "public_key": "${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type": "vless",
              "tag": "xtls-reality",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_XTLS_REALITY},
              "users": [
                  {
                      "uuid": "${UUID}",
                      "flow": ""
                  }
              ],
              "tls": {
                  "enabled": true,
                  "server_name": "fast.com",
                  "reality": {
                      "enabled": true,
                      "handshake": {
                          "server": "fast.com",
                          "server_port": 443
                      },
                      "private_key": "${REALITY_PRIVATE}",
                      "short_id": [
                          ""
                      ]
                  }
              },
              "multiplex": {
                  "enabled": true,
                  "padding": true
              }
          }
      ]
  }
EOF
    [ "${XTLS_REALITYX}" = 'true' ] && hint "Generated xtls-reality-x inbound config."

  [ "${SHADOWSOCKS}" = 'true' ] && ((PORT++)) && PORT_SHADOWSOCKS=$PORT && cat > $WORK_DIR/conf/${PORT_SHADOWSOCKS}_shadowsocks_inbounds.json << EOF
  {
      "inbounds": [
          {
              "type": "shadowsocks",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SHADOWSOCKS},
              "network": "tcp",
              "method": "${SS_ENCRYPTION_METHOD}",
              "password": "${SS_ENCRYPTION_PASSWORD}",
              "users": []
          }
      ]
  }
EOF
    [ "${SHADOWSOCKS}" = 'true' ] && hint "Generated shadowsocks inbound config."

  [ "${SHADOWSOCKSX}" = 'true' ] && ((PORT++)) && PORT_SHADOWSOCKS=$PORT && cat > $WORK_DIR/conf/${PORT_SHADOWSOCKS}_shadowsocks_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "shadowsocks",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SHADOWSOCKS},
              "network": "tcp",
              "method": "${SS_ENCRYPTION_METHOD}",
              "password": "${SS_ENCRYPTION_PASSWORD}",
              "users": [],
              "multiplex": {
                  "enabled": true,
                  "padding": true
              }
          }
      ]
  }
EOF
    [ "${SHADOWSOCKSX}" = 'true' ] && hint "Generated shadowsocksx inbound config."

  [ "${SOCKS}" = 'true' ] && ((PORT++)) && PORT_SOCKS=$PORT && cat > $WORK_DIR/conf/${PORT_SOCKS}_socks_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "socks",
              "tag": "socks",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SOCKS},
              "users": []
          }
      ]
  }
EOF
    [ "${SOCKS}" = 'true' ] && hint "Generated socks inbound config."

INBOUND_REPLACE="["

if [ "${XTLS_REALITY}" = "true" ]; then
  [ "$INBOUND_REPLACE" != "[" ] && INBOUND_REPLACE+=','
  INBOUND_REPLACE+='{"type":"vless","tag":"xtls-reality","server":"'"${SERVER_IP}"'","domain_strategy":"'"${DOMAIN_STRATEGY}"'","server_port":'"${PORT_XTLS_REALITY}"',"uuid":"'"${UUID}"'","flow":"","packet_encoding":"xudp","tls":{"enabled":true,"server_name":"fast.com","utls":{"enabled":true,"fingerprint":"chrome"},"reality":{"enabled":true,"public_key":"'"${REALITY_PUBLIC}"'","short_id":""}}}'
fi

if [ "${XTLS_REALITYX}" = "true" ]; then
  [ "$INBOUND_REPLACE" != "[" ] && INBOUND_REPLACE+=','
  INBOUND_REPLACE+='{"type":"vless","tag":"xtls-reality","server":"'"${SERVER_IP}"'","domain_strategy":"'"${DOMAIN_STRATEGY}"'","server_port":'"${PORT_XTLS_REALITY}"',"uuid":"'"${UUID}"'","flow":"","packet_encoding":"xudp","tls":{"enabled":true,"server_name":"fast.com","utls":{"enabled":true,"fingerprint":"chrome"},"reality":{"enabled":true,"public_key":"'"${REALITY_PUBLIC}"'","short_id":""}},"multiplex":{"enabled":true,"protocol":"h2mux","max_connections":8,"min_streams":16,"padding":true}}'
fi

if [ "${SHADOWSOCKS}" = "true" ]; then
  [ "$INBOUND_REPLACE" != "[" ] && INBOUND_REPLACE+=','
  INBOUND_REPLACE+='{"type":"shadowsocks","tag":"shadowsocks","server":"'"${SERVER_IP}"'","domain_strategy":"'"${DOMAIN_STRATEGY}"'","server_port":'"${PORT_SHADOWSOCKS}"',"method":"'"${SS_ENCRYPTION_METHOD}"'","password":"'"${SS_ENCRYPTION_PASSWORD}"'"}'
fi

if [ "${SHADOWSOCKSX}" = "true" ]; then
  [ "$INBOUND_REPLACE" != "[" ] && INBOUND_REPLACE+=','
  INBOUND_REPLACE+='{"type":"shadowsocks","tag":"shadowsocks","server":"'"${SERVER_IP}"'","domain_strategy":"'"${DOMAIN_STRATEGY}"'","server_port":'"${PORT_SHADOWSOCKS}"',"method":"'"${SS_ENCRYPTION_METHOD}"'","password":"'"${SS_ENCRYPTION_PASSWORD}"'","multiplex":{"enabled":true,"protocol":"h2mux","max_connections":8,"min_streams":16,"padding":true}}'
fi

INBOUND_REPLACE+="]"
echo $INBOUND_REPLACE | jq '.' > "$WORK_DIR/public/local.json"
}

info "starting..."
upupup
info "started."
/sing-box/sing-box run -C $WORK_DIR/conf
