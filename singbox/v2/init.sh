#!/usr/bin/env bash

WORK_DIR=/sing-box
mkdir -p $WORK_DIR/certs
mkdir -p $WORK_DIR/conf
mkdir -p $WORK_DIR/public
PORT=${START_PORT:-1080}
DOMAIN=${CUSTOM_DOMAIN:-example.com}

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
  local REALITY_KEYPAIR=$($WORK_DIR/sing-box generate reality-keypair) && AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR") && AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
  local REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-AUTO_REALITY_PRIVATE}
  local REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-AUTO_REALITY_PUBLIC}
  local UUID=${CUSTOM_UUID:-"$($WORK_DIR/sing-box generate uuid)"}


#   local UUID=${CUSTOM_UUID:-"$($WORK_DIR/sing-box generate uuid)"}
#   local NODE_NAME=${NODE_NAME:-"sing-box"}

  openssl ecparam -genkey -name prime256v1 -out ${WORK_DIR}/certs/private.key && \
  openssl req -new -x509 -days 36500 -key ${WORK_DIR}/certs/private.key -out ${WORK_DIR}/certs/cert.pem -subj "/CN=${DOMAIN}"

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
              "external_ui_download_detour": "direct-out",
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

# === XTLS_REALITY ===
  [ "${XTLS_REALITY}" = 'true' ] && ((PORT++)) && PORT_XTLS_REALITY=$PORT && cat > $WORK_DIR/conf/${PORT_XTLS_REALITY}_xtls-reality_inbounds.json << EOF
  //  "public_key": "${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type": "vless",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_XTLS_REALITY},
              "users": [
                  {
                      "uuid": "${UUID}",
                      "flow": "xtls-rprx-vision"
                  }
              ],
              "tls": {
                  "enabled": true,
                  "server_name": "${DOMAIN}",
                  "reality": {
                      "enabled": true,
                      "handshake": {
                          "server": "${DOMAIN}",
                          "server_port": 443
                      },
                      "private_key": "${REALITY_PRIVATE}",
                      "short_id": [
                          "0123456789abcdef"
                      ]
                  }
              }
          }
      ]
  }
EOF
    [ "${XTLS_REALITY}" = 'true' ] && hint "Generated xtls-reality inbound config."

# === SHADOWSOCKS ===
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

# === TROJAN ===
  [ "${TROJAN}" == 'true' ] && ((PORT++)) && PORT_TROJAN=$PORT && cat > $WORK_DIR/conf/${PORT_TROJAN}_trojan_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type": "trojan",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_TROJAN},
              "users": [
                  {
                      "password": "${UUID}"
                  }
              ],
              "tls": {
                "enabled": true,
                "server_name": "${DOMAIN}",
                "certificate_path": "${WORK_DIR}/certs/cert.pem",
                "key_path": "${WORK_DIR}/certs/private.key",
                "alpn": ["http/1.1", "h2", "h3"]
              }
          }
      ]
  }
EOF
    [ "${TROJAN}" = 'true' ] && hint "Generated trojan inbound config."

# === SHADOWTLS ===
  [ "${SHADOWTLS}" == 'true' ] && ((PORT++)) && PORT_SHADOWTLS=$PORT && cat > $WORK_DIR/conf/${PORT_SHADOWTLS}_shadowtls_inbounds.json << EOF
  {
      "inbounds": [
          {
              "type": "shadowtls",
              "tag": "shadowtls",
              "listen": "0.0.0.0",
              "listen_port": ${PORT_SHADOWTLS},
              "detour": "shadowtls-in",
              "version": 3,
              "users": [
                  {
                      "password": "${UUID}"
                  }
              ],
              "handshake": {
                  "server": "${DOMAIN}",
                  "server_port": 443
              },
              "strict_mode": true
          },
          {
              "type": "shadowsocks",
              "tag": "shadowtls-in",
              "listen": "127.0.0.1",
              "network": "tcp",
              "method": "${SS_ENCRYPTION_METHOD}",
              "password": "${SS_ENCRYPTION_PASSWORD}"
          }
      ]
  }
EOF
    [ "${SHADOWTLS}" = 'true' ] && hint "Generated shadowtls inbound config."

# === SOCKS ===
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
append_comma_if_needed() {
  [ "$INBOUND_REPLACE" != "[" ] && INBOUND_REPLACE+=','
}

# === XTLS_REALITY ===
if [ "${XTLS_REALITY}" = "true" ]; then
  append_comma_if_needed
  INBOUND_REPLACE+=$(
    cat <<EOF
{
  "type": "vless",
  "tag": "xtls-reality",
  "server": "${SERVER_IP}",
  "domain_strategy": "${DOMAIN_STRATEGY}",
  "server_port": ${PORT_XTLS_REALITY},
  "uuid": "${UUID}",
  "flow": "xtls-rprx-vision",
  "packet_encoding": "xudp",
  "tls": {
    "enabled": true,
    "insecure": true,
    "server_name": "${DOMAIN}",
    "utls": {
      "enabled": true,
      "fingerprint": "chrome"
    },
    "reality": {
      "enabled": true,
      "public_key": "${REALITY_PUBLIC}",
      "short_id": "0123456789abcdef"
    }
  }
}
EOF
  )
fi

# === SHADOWSOCKS ===
if [ "${SHADOWSOCKS}" = "true" ]; then
  append_comma_if_needed
  INBOUND_REPLACE+=$(
    cat <<EOF
{
  "type": "shadowsocks",
  "tag": "shadowsocks",
  "server": "${SERVER_IP}",
  "domain_strategy": "${DOMAIN_STRATEGY}",
  "server_port": ${PORT_SHADOWSOCKS},
  "method": "${SS_ENCRYPTION_METHOD}",
  "password": "${SS_ENCRYPTION_PASSWORD}"
}
EOF
  )
fi

# === TROJAN ===
if [ "${TROJAN}" = "true" ]; then
  append_comma_if_needed
  INBOUND_REPLACE+=$(
    cat <<EOF
{
  "type": "trojan",
  "tag": "trojan",
  "server": "${SERVER_IP}",
  "domain_strategy": "${DOMAIN_STRATEGY}",
  "server_port": ${PORT_TROJAN},
  "password": "${UUID}",
  "tls": {
    "enabled": true,
    "insecure": true,
    "server_name": "${DOMAIN}",
    "alpn": ["http/1.1", "h2", "h3"],
    "utls": {
      "enabled": true,
      "fingerprint": "chrome"
    }
  }
}
EOF
  )
fi


# === SHADOWTLS ===
if [ "${SHADOWTLS}" = "true" ]; then
  append_comma_if_needed
  INBOUND_REPLACE+=$(
    cat <<EOF
{
  "type": "shadowsocks",
  "tag": "shadowtls",
  "method": "${SS_ENCRYPTION_METHOD}",
  "password": "${SS_ENCRYPTION_PASSWORD}",
  "detour": "shadowtls-out",
  "udp_over_tcp": false
},
{
  "type": "shadowtls",
  "tag": "shadowtls-out",
  "server": "${SERVER_IP}",
  "domain_strategy": "${DOMAIN_STRATEGY}",
  "server_port": ${PORT_SHADOWTLS},
  "version": 3,
  "password": "${UUID}",
  "tls": {
    "enabled": true,
    "server_name": "${DOMAIN}",
    "utls": {
      "enabled": true,
      "fingerprint": "chrome"
    }
  }
}
EOF
  )
fi

INBOUND_REPLACE+="]"
echo "Generated public inbound config."
echo "$INBOUND_REPLACE"
echo "$INBOUND_REPLACE" | jq '.' > "$WORK_DIR/public/local.json"
}

info "starting..."
upupup
info "started."
/sing-box/sing-box run -C $WORK_DIR/conf
