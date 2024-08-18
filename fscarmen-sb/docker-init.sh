#!/usr/bin/env bash

# 2024.08.18
WORK_DIR=/sing-box
PORT=$START_PORT
SUBSCRIBE_TEMPLATE="https://raw.githubusercontent.com/minlaxz/nekohasekai/main/fscarmen-sb"

warning() { echo -e "\033[31m\033[01m$*\033[0m"; }
info() { echo -e "\033[32m\033[01m$*\033[0m"; }
hint() { echo -e "\033[33m\033[01m$*\033[0m"; }

check_arch() {
  case "$ARCH" in
    arm64 )
      SING_BOX_ARCH=arm64; JQ_ARCH=arm64; QRENCODE_ARCH=arm64; ARGO_ARCH=arm64
      ;;
    amd64 )
      [[ "$(awk -F ':' '/flags/{print $2; exit}' /proc/cpuinfo)" =~ avx2 ]] && SING_BOX_ARCH=amd64v3 || SING_BOX_ARCH=amd64
      JQ_ARCH=amd64; QRENCODE_ARCH=amd64; ARGO_ARCH=amd64
      ;;
    armv7 )
      SING_BOX_ARCH=armv7; JQ_ARCH=armhf; QRENCODE_ARCH=arm; ARGO_ARCH=arm
      ;;
  esac
}

check_latest_sing-box() {
  local VERSION_LATEST=$(wget -qO- "https://api.github.com/repos/SagerNet/sing-box/releases" | awk -F '["v-]' '/tag_name/{print $5}' | sort -r | sed -n '1p')
  wget -qO- "https://api.github.com/repos/SagerNet/sing-box/releases" | awk -F '["v]' -v var="tag_name.*$VERSION_LATEST" '$0 ~ var {print $5; exit}'
}

install() {
  echo "Installing sing-box ..."
  local ONLINE=$(check_latest_sing-box)
  wget https://github.com/SagerNet/sing-box/releases/download/v$ONLINE/sing-box-$ONLINE-linux-$SING_BOX_ARCH.tar.gz -O- | tar xz -C $WORK_DIR sing-box-$ONLINE-linux-$SING_BOX_ARCH/sing-box && mv $WORK_DIR/sing-box-$ONLINE-linux-$SING_BOX_ARCH/sing-box $WORK_DIR/sing-box && rm -rf $WORK_DIR/sing-box-$ONLINE-linux-$SING_BOX_ARCH

  echo "Installing jq ..."
  wget -O $WORK_DIR/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-$JQ_ARCH && chmod +x $WORK_DIR/jq

  echo "Installing qrencode ..."
  wget -O $WORK_DIR/qrencode https://github.com/fscarmen/client_template/raw/main/qrencode-go/qrencode-go-linux-$QRENCODE_ARCH && chmod +x $WORK_DIR/qrencode

  echo "Installing cloudflared ..."
  wget -O $WORK_DIR/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARGO_ARCH && chmod +x $WORK_DIR/cloudflared

  if [[ "$SERVER_IP" =~ : ]]; then
    local DOMAIN_STRATEGY=prefer_ipv6
  else
    local DOMAIN_STRATEGY=prefer_ipv4
  fi

  local REALITY_KEYPAIR=$($WORK_DIR/sing-box generate reality-keypair) && REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR") && REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
  local SHADOWTLS_PASSWORD=$($WORK_DIR/sing-box generate rand --base64 16)
  local UUID=${UUID:-"$($WORK_DIR/sing-box generate uuid)"}
  local NODE_NAME=${NODE_NAME:-"sing-box"}
  local CDN=${CDN:-"cdn.jsdelivr.net"}

  cat > $WORK_DIR/conf/00_log.json << EOF
  {
      "log":{
          "level":"error",
          "output":"$WORK_DIR/logs/box.log",
          "timestamp":true
      }
  }
EOF

  cat > $WORK_DIR/conf/01_outbounds.json << EOF
  {
      "outbounds":[
          {
              "type":"direct",
              "tag":"direct",
              "domain_strategy":"${DOMAIN_STRATEGY}"
          }
      ]
  }
EOF

  cat > $WORK_DIR/conf/02_route.json << EOF
  {
      "route":{
          "rule_set":[],
          "rules":[]
      }
  }
EOF

  cat > $WORK_DIR/conf/03_experimental.json << EOF
  {
      "experimental": {
          "cache_file": {
              "enabled": true,
              "path": "$WORK_DIR/cache.db"
          }
      }
  }
EOF

  cat > $WORK_DIR/conf/04_dns.json << EOF
  {
      "dns":{
          "servers":[
              {
                  "address":"local"
              }
          ]
      }
  }
EOF

  [ "${XTLS_REALITY}" = 'true' ] && ((PORT++)) && PORT_XTLS_REALITY=$PORT && cat > $WORK_DIR/conf/11_xtls-reality_inbounds.json << EOF
  //  "public_key":"${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} xtls-reality",
              "listen":"::",
              "listen_port":${PORT_XTLS_REALITY},
              "users":[
                  {
                      "uuid":"${UUID}",
                      "flow":""
                  }
              ],
              "tls":{
                  "enabled":true,
                  "server_name":"addons.mozilla.org",
                  "reality":{
                      "enabled":true,
                      "handshake":{
                          "server":"addons.mozilla.org",
                          "server_port":443
                      },
                      "private_key":"${REALITY_PRIVATE}",
                      "short_id":[
                          ""
                      ]
                  }
              }
          }
      ]
  }
EOF

  [ "${XTLS_REALITYX}" = 'true' ] && ((PORT++)) && PORT_XTLS_REALITY=$PORT && cat > $WORK_DIR/conf/11_xtls-reality_inbounds.json << EOF
  //  "public_key":"${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} xtls-reality",
              "listen":"::",
              "listen_port":${PORT_XTLS_REALITY},
              "users":[
                  {
                      "uuid":"${UUID}",
                      "flow":""
                  }
              ],
              "tls":{
                  "enabled":true,
                  "server_name":"addons.mozilla.org",
                  "reality":{
                      "enabled":true,
                      "handshake":{
                          "server":"addons.mozilla.org",
                          "server_port":443
                      },
                      "private_key":"${REALITY_PRIVATE}",
                      "short_id":[
                          ""
                      ]
                  }
              },
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  [ "${HYSTERIA2}" = 'true' ] && ((PORT++)) && PORT_HYSTERIA2=$PORT && cat > $WORK_DIR/conf/12_hysteria2_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"hysteria2",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} hysteria2",
              "listen":"::",
              "listen_port":${PORT_HYSTERIA2},
              "users":[
                  {
                      "password":"${UUID}"
                  }
              ],
              "ignore_client_bandwidth":false,
              "tls":{
                  "enabled":true,
                  "server_name":"",
                  "alpn":[
                      "h3"
                  ],
                  "min_version":"1.3",
                  "max_version":"1.3",
                  "certificate_path":"$WORK_DIR/cert/cert.pem",
                  "key_path":"$WORK_DIR/cert/private.key"
              }
          }
      ]
  }
EOF

  [ "${TUIC}" = 'true' ] && ((PORT++)) && PORT_TUIC=$PORT && cat > $WORK_DIR/conf/13_tuic_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"tuic",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} tuic",
              "listen":"::",
              "listen_port":${PORT_TUIC},
              "users":[
                  {
                      "uuid":"${UUID}",
                      "password":"${UUID}"
                  }
              ],
              "congestion_control": "bbr",
              "zero_rtt_handshake": false,
              "tls":{
                  "enabled":true,
                  "alpn":[
                      "h3"
                  ],
                  "certificate_path":"$WORK_DIR/cert/cert.pem",
                  "key_path":"$WORK_DIR/cert/private.key"
              }
          }
      ]
  }
EOF

  [ "${SHADOWTLS}" = 'true' ] && ((PORT++)) && PORT_SHADOWTLS=$PORT && cat > $WORK_DIR/conf/14_ShadowTLS_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"shadowtls",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} ShadowTLS",
              "listen":"::",
              "listen_port":${PORT_SHADOWTLS},
              "detour":"shadowtls-in",
              "version":3,
              "users":[
                  {
                      "password":"${UUID}"
                  }
              ],
              "handshake":{
                  "server":"addons.mozilla.org",
                  "server_port":443
              },
              "strict_mode":true
          },
          {
              "type":"shadowsocks",
              "tag":"shadowtls-in",
              "listen":"127.0.0.1",
              "network":"tcp",
              "method":"2022-blake3-aes-128-gcm",
              "password":"${SHADOWTLS_PASSWORD}"
          }
      ]
  }
EOF

  [ "${SHADOWTLSX}" = 'true' ] && ((PORT++)) && PORT_SHADOWTLS=$PORT && cat > $WORK_DIR/conf/14_ShadowTLS_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"shadowtls",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} ShadowTLS",
              "listen":"::",
              "listen_port":${PORT_SHADOWTLS},
              "detour":"shadowtls-in",
              "version":3,
              "users":[
                  {
                      "password":"${UUID}"
                  }
              ],
              "handshake":{
                  "server":"addons.mozilla.org",
                  "server_port":443
              },
              "strict_mode":true
          },
          {
              "type":"shadowsocks",
              "tag":"shadowtls-in",
              "listen":"127.0.0.1",
              "network":"tcp",
              "method":"2022-blake3-aes-128-gcm",
              "password":"${SHADOWTLS_PASSWORD}",
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  [ "${SHADOWSOCKS}" = 'true' ] && ((PORT++)) && PORT_SHADOWSOCKS=$PORT && cat > $WORK_DIR/conf/15_shadowsocks_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"shadowsocks",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} shadowsocks",
              "listen":"::",
              "listen_port":${PORT_SHADOWSOCKS},
              "method":"aes-128-gcm",
              "password":"${UUID}"
          }
      ]
  }
EOF

  [ "${SHADOWSOCKSX}" = 'true' ] && ((PORT++)) && PORT_SHADOWSOCKS=$PORT && cat > $WORK_DIR/conf/15_shadowsocks_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"shadowsocks",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} shadowsocks",
              "listen":"::",
              "listen_port":${PORT_SHADOWSOCKS},
              "method":"aes-128-gcm",
              "password":"${UUID}",
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  [ "${TROJAN}" = 'true' ] && ((PORT++)) && PORT_TROJAN=$PORT && cat > $WORK_DIR/conf/16_trojan_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"trojan",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} trojan",
              "listen":"::",
              "listen_port":${PORT_TROJAN},
              "users":[
                  {
                      "password":"${UUID}"
                  }
              ],
              "tls":{
                  "enabled":true,
                  "certificate_path":"$WORK_DIR/cert/cert.pem",
                  "key_path":"$WORK_DIR/cert/private.key"
              }
          }
      ]
  }
EOF

  [ "${TROJANX}" = 'true' ] && ((PORT++)) && PORT_TROJAN=$PORT && cat > $WORK_DIR/conf/16_trojan_inbounds.json << EOF
  {
      "inbounds":[
          {
              "type":"trojan",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} trojan",
              "listen":"::",
              "listen_port":${PORT_TROJAN},
              "users":[
                  {
                      "password":"${UUID}"
                  }
              ],
              "tls":{
                  "enabled":true,
                  "certificate_path":"$WORK_DIR/cert/cert.pem",
                  "key_path":"$WORK_DIR/cert/private.key"
              },
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  [ "${VLESS_WS}" = 'true' ] && ((PORT++)) && PORT_VLESS_WS=$PORT && cat > $WORK_DIR/conf/18_vless-ws-tls_inbounds.json << EOF
  //  "CDN": "${CDN}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff_override_destination":true,
              "sniff":true,
              "tag":"${NODE_NAME} vless-ws-tls",
              "listen":"::",
              "listen_port":${PORT_VLESS_WS},
              "tcp_fast_open":false,
              "proxy_protocol":false,
              "users":[
                  {
                      "name":"sing-box",
                      "uuid":"${UUID}"
                  }
              ],
              "transport":{
                  "type":"ws",
                  "path":"/${UUID}-vless",
                  "max_early_data":2048,
                  "early_data_header_name":"Sec-WebSocket-Protocol"
              }
          }
      ]
  }
EOF

  [ "${VLESS_WSX}" = 'true' ] && ((PORT++)) && PORT_VLESS_WS=$PORT && cat > $WORK_DIR/conf/18_vless-ws-tls_inbounds.json << EOF
  //  "CDN": "${CDN}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff_override_destination":true,
              "sniff":true,
              "tag":"${NODE_NAME} vless-ws-tls",
              "listen":"::",
              "listen_port":${PORT_VLESS_WS},
              "tcp_fast_open":false,
              "proxy_protocol":false,
              "users":[
                  {
                      "name":"sing-box",
                      "uuid":"${UUID}"
                  }
              ],
              "transport":{
                  "type":"ws",
                  "path":"/${UUID}-vless",
                  "max_early_data":2048,
                  "early_data_header_name":"Sec-WebSocket-Protocol"
              },
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  [ "${H2_REALITY}" = 'true' ] && ((PORT++)) && PORT_H2_REALITY=$PORT && cat > $WORK_DIR/conf/19_h2-reality_inbounds.json << EOF
  //  "public_key":"${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} h2-reality",
              "listen":"::",
              "listen_port":${PORT_H2_REALITY},
              "users":[
                  {
                      "uuid":"${UUID}"
                  }
              ],
              "tls":{
                  "enabled":true,
                  "server_name":"addons.mozilla.org",
                  "reality":{
                      "enabled":true,
                      "handshake":{
                          "server":"addons.mozilla.org",
                          "server_port":443
                      },
                      "private_key":"${REALITY_PRIVATE}",
                      "short_id":[
                          ""
                      ]
                  }
              },
              "transport": {
                  "type": "http"
              }
          }
      ]
  }
EOF

  [ "${H2_REALITYX}" = 'true' ] && ((PORT++)) && PORT_H2_REALITY=$PORT && cat > $WORK_DIR/conf/19_h2-reality_inbounds.json << EOF
  //  "public_key":"${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} h2-reality",
              "listen":"::",
              "listen_port":${PORT_H2_REALITY},
              "users":[
                  {
                      "uuid":"${UUID}"
                  }
              ],
              "tls":{
                  "enabled":true,
                  "server_name":"addons.mozilla.org",
                  "reality":{
                      "enabled":true,
                      "handshake":{
                          "server":"addons.mozilla.org",
                          "server_port":443
                      },
                      "private_key":"${REALITY_PRIVATE}",
                      "short_id":[
                          ""
                      ]
                  }
              },
              "transport": {
                  "type": "http"
              },
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  [ "${GRPC_REALITY}" = 'true' ] && ((PORT++)) && PORT_GRPC_REALITY=$PORT && cat > $WORK_DIR/conf/20_grpc-reality_inbounds.json << EOF
  //  "public_key":"${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} grpc-reality",
              "listen":"::",
              "listen_port":${PORT_GRPC_REALITY},
              "users":[
                  {
                      "uuid":"${UUID}"
                  }
              ],
              "tls":{
                  "enabled":true,
                  "server_name":"addons.mozilla.org",
                  "reality":{
                      "enabled":true,
                      "handshake":{
                          "server":"addons.mozilla.org",
                          "server_port":443
                      },
                      "private_key":"${REALITY_PRIVATE}",
                      "short_id":[
                          ""
                      ]
                  }
              },
              "transport": {
                  "type": "grpc",
                  "service_name": "grpc"
              }
          }
      ]
  }
EOF

  [ "${GRPC_REALITYX}" = 'true' ] && ((PORT++)) && PORT_GRPC_REALITY=$PORT && cat > $WORK_DIR/conf/20_grpc-reality_inbounds.json << EOF
  //  "public_key":"${REALITY_PUBLIC}"
  {
      "inbounds":[
          {
              "type":"vless",
              "sniff":true,
              "sniff_override_destination":true,
              "tag":"${NODE_NAME} grpc-reality",
              "listen":"::",
              "listen_port":${PORT_GRPC_REALITY},
              "users":[
                  {
                      "uuid":"${UUID}"
                  }
              ],
              "tls":{
                  "enabled":true,
                  "server_name":"addons.mozilla.org",
                  "reality":{
                      "enabled":true,
                      "handshake":{
                          "server":"addons.mozilla.org",
                          "server_port":443
                      },
                      "private_key":"${REALITY_PRIVATE}",
                      "short_id":[
                          ""
                      ]
                  }
              },
              "transport": {
                  "type": "grpc",
                  "service_name": "grpc"
              },
              "multiplex":{
                  "enabled":true,
                  "padding":true,
                  "brutal":{
                      "enabled":true,
                      "up_mbps":1000,
                      "down_mbps":1000
                  }
              }
          }
      ]
  }
EOF

  if [[ -n "$ARGO_DOMAIN" && -n "$ARGO_AUTH" ]]; then
    if [[ "$ARGO_AUTH" =~ TunnelSecret ]]; then
      ARGO_JSON=${ARGO_AUTH//[ ]/}
      ARGO_RUNS="cloudflared tunnel --edge-ip-version auto --config $WORK_DIR/tunnel.yml run"
      echo $ARGO_JSON > $WORK_DIR/tunnel.json
      cat > $WORK_DIR/tunnel.yml << EOF
tunnel: $(cut -d\" -f12 <<< $ARGO_JSON)
credentials-file: $WORK_DIR/tunnel.json

ingress:
  - hostname: ${ARGO_DOMAIN}
    service: https://localhost:${START_PORT}
    originRequest:
      noTLSVerify: true
  - service: http_status:404
EOF

    elif [[ "${ARGO_AUTH}" =~ [a-z0-9A-Z=]{120,250} ]]; then
      [[ "{$ARGO_AUTH}" =~ cloudflared.*service ]] && ARGO_TOKEN=$(awk -F ' ' '{print $NF}' <<< "$ARGO_AUTH") || ARGO_TOKEN=$ARGO_AUTH
      ARGO_RUNS="cloudflared tunnel --edge-ip-version auto run --token ${ARGO_TOKEN}"
    fi
  else
    ((PORT++))
    METRICS_PORT=$PORT
    ARGO_RUNS="cloudflared tunnel --edge-ip-version auto --no-autoupdate --no-tls-verify --metrics 0.0.0.0:$METRICS_PORT --url https://localhost:$START_PORT"
  fi

  mkdir -p /etc/supervisor.d
  SUPERVISORD_CONF="[supervisord]
user=root
nodaemon=true
logfile=/dev/null
pidfile=/run/supervisord.pid

[program:nginx]
command=/usr/sbin/nginx -g 'daemon off;'
autostart=true
autorestart=true
stderr_logfile=/dev/null
stdout_logfile=/dev/null

[program:sing-box]
command=$WORK_DIR/sing-box run -C $WORK_DIR/conf/
autostart=true
autorestart=true
stderr_logfile=/dev/null
stdout_logfile=/dev/null"

[ -z "$METRICS_PORT" ] && SUPERVISORD_CONF+="

[program:argo]
command=$WORK_DIR/$ARGO_RUNS
autostart=true
autorestart=true
stderr_logfile=/dev/null
stdout_logfile=/dev/null
"

  echo "$SUPERVISORD_CONF" > /etc/supervisor.d/daemon.ini

  # 如使用临时隧道，先运行 cloudflared 以获取临时隧道域名
  if [ -n "$METRICS_PORT" ]; then
    $WORK_DIR/$ARGO_RUNS >/dev/null 2>&1 &
    sleep 3
    local ARGO_DOMAIN=$(wget -qO- http://localhost:$METRICS_PORT/quicktunnel | awk -F '"' '{print $4}')
  fi

  local NGINX_CONF="user root;

  worker_processes auto;

  error_log  /dev/null;
  pid        /var/run/nginx.pid;

  events {
      worker_connections  1024;
  }

  http {
    map \$http_user_agent \$path {
      default                    /;                # 默认路径
      ~*v2rayN|Neko              /base64;          # 匹配 V2rayN / NekoBox 客户端
      ~*clash                    /clash;           # 匹配 Clash 客户端
      ~*ShadowRocket             /shadowrocket;    # 匹配 ShadowRocket  客户端
      ~*SFM                      /sing-box-pc;     # 匹配 Sing-box pc 客户端
      ~*SFI|SFA                  /sing-box-phone;  # 匹配 Sing-box phone 客户端
   #   ~*Chrome|Firefox|Mozilla  /;                # 添加更多的分流规则
    }

      include       /etc/nginx/mime.types;
      default_type  application/octet-stream;

      log_format  main  '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                        '\$status \$body_bytes_sent "\$http_referer" '
                        '"\$http_user_agent" "\$http_x_forwarded_for"';

      access_log  /dev/null;

      sendfile        on;
      #tcp_nopush     on;

      keepalive_timeout  65;

      #gzip  on;

      #include /etc/nginx/conf.d/*.conf;

    server {
      listen 127.0.0.1:$START_PORT ssl http2; # sing-box backend
      server_name addons.mozilla.org;

      ssl_certificate            $WORK_DIR/cert/cert.pem;
      ssl_certificate_key        $WORK_DIR/cert/private.key;
      ssl_protocols              TLSv1.3;
      ssl_session_tickets        on;
      ssl_stapling               off;
      ssl_stapling_verify        off;"

  [ "${VLESS_WS}" = 'true' ] && NGINX_CONF+="
      # 反代 sing-box websocket
      location /${UUID}-vmess {
        if (\$http_upgrade != "websocket") {
           return 404;
        }
        proxy_pass                          http://127.0.0.1:${PORT_VLESS_WS};
        proxy_http_version                  1.1;
        proxy_set_header Upgrade            \$http_upgrade;
        proxy_set_header Connection         "upgrade";
        proxy_set_header X-Real-IP          \$remote_addr;
        proxy_set_header X-Forwarded-For    \$proxy_add_x_forwarded_for;
        proxy_set_header Host               \$host;
        proxy_redirect                      off;
      }"

  NGINX_CONF+="
      # 来自 /auto 的分流
      location ~ ^/${UUID}/auto {
        default_type 'text/plain; charset=utf-8';
        alias $WORK_DIR/subscribe/\$path;
      }

      location ~ ^/${UUID}/(.*) {
        autoindex on;
        proxy_set_header X-Real-IP \$proxy_protocol_addr;
        default_type 'text/plain; charset=utf-8';
        alias $WORK_DIR/subscribe/\$1;
      }
    }
  }"

  echo "$NGINX_CONF" > /etc/nginx/nginx.conf

  # IPv6 时的 IP 处理
  if [[ "$SERVER_IP" =~ : ]]; then
    SERVER_IP_1="[$SERVER_IP]"
    SERVER_IP_2="[[$SERVER_IP]]"
  else
    SERVER_IP_1="$SERVER_IP"
    SERVER_IP_2="$SERVER_IP"
  fi

  # 生成 Sing-box 订阅文件
  [ "${XTLS_REALITY}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} xtls-reality\", \"server\":\"${SERVER_IP}\", \"server_port\":${PORT_XTLS_REALITY}, \"uuid\":\"${UUID}\", \"flow\":\"\", \"packet_encoding\":\"xudp\", \"tls\":{ \"enabled\":true, \"server_name\":\"addons.mozilla.org\", \"utls\":{ \"enabled\":true, \"fingerprint\":\"chrome\" }, \"reality\":{ \"enabled\":true, \"public_key\":\"${REALITY_PUBLIC}\", \"short_id\":\"\" } }, \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} xtls-reality\","

  [ "${XTLS_REALITYX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} xtls-reality\", \"server\":\"${SERVER_IP}\", \"server_port\":${PORT_XTLS_REALITY}, \"uuid\":\"${UUID}\", \"flow\":\"\", \"packet_encoding\":\"xudp\", \"tls\":{ \"enabled\":true, \"server_name\":\"addons.mozilla.org\", \"utls\":{ \"enabled\":true, \"fingerprint\":\"chrome\" }, \"reality\":{ \"enabled\":true, \"public_key\":\"${REALITY_PUBLIC}\", \"short_id\":\"\" } }, \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} xtls-reality\","

  [ "${HYSTERIA2}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"hysteria2\", \"tag\": \"${NODE_NAME} hysteria2\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_HYSTERIA2}, \"up_mbps\": 200, \"down_mbps\": 1000, \"password\": \"${UUID}\", \"tls\": { \"enabled\": true, \"insecure\": true, \"server_name\": \"\", \"alpn\": [ \"h3\" ] } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} hysteria2\","

  [ "${TUIC}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"tuic\", \"tag\": \"${NODE_NAME} tuic\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_TUIC}, \"uuid\": \"${UUID}\", \"password\": \"${UUID}\", \"congestion_control\": \"bbr\", \"udp_relay_mode\": \"native\", \"zero_rtt_handshake\": false, \"heartbeat\": \"10s\", \"tls\": { \"enabled\": true, \"insecure\": true, \"server_name\": \"\", \"alpn\": [ \"h3\" ] } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} tuic\","

  [ "${SHADOWTLS}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"shadowsocks\", \"tag\": \"${NODE_NAME} ShadowTLS\", \"method\": \"2022-blake3-aes-128-gcm\", \"password\": \"${SHADOWTLS_PASSWORD}\", \"detour\": \"shadowtls-out\", \"udp_over_tcp\": false, \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }, { \"type\": \"shadowtls\", \"tag\": \"shadowtls-out\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_SHADOWTLS}, \"version\": 3, \"password\": \"${UUID}\", \"tls\": { \"enabled\": true, \"server_name\": \"addons.mozilla.org\", \"utls\": { \"enabled\": true, \"fingerprint\": \"chrome\" } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} ShadowTLS\","

  [ "${SHADOWSOCKS}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"shadowsocks\", \"tag\": \"${NODE_NAME} shadowsocks\", \"server\": \"${SERVER_IP}\", \"server_port\": $PORT_SHADOWSOCKS, \"method\": \"aes-128-gcm\", \"password\": \"${UUID}\", \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} shadowsocks\","

  [ "${TROJAN}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"trojan\", \"tag\": \"${NODE_NAME} trojan\", \"server\": \"${SERVER_IP}\", \"server_port\": $PORT_TROJAN, \"password\": \"${UUID}\", \"tls\": { \"enabled\":true, \"insecure\": true, \"server_name\":\"\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" } }, \"multiplex\": { \"enabled\":true, \"protocol\":\"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} trojan\","

  [ "${VLESS_WS}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} vless-ws-tls\", \"server\":\"${CDN}\", \"server_port\":443, \"uuid\":\"${UUID}\", \"tls\": { \"enabled\":true, \"server_name\":\"${ARGO_DOMAIN}\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" } }, \"transport\": { \"type\":\"ws\", \"path\":\"/${UUID}-vless\", \"headers\": { \"Host\": \"${ARGO_DOMAIN}\" }, \"max_early_data\":2048, \"early_data_header_name\":\"Sec-WebSocket-Protocol\" }, \"multiplex\": { \"enabled\":true, \"protocol\":\"h2mux\", \"max_streams\":16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} vless-ws-tls\","

  [ "${H2_REALITY}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} h2-reality\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_H2_REALITY}, \"uuid\":\"${UUID}\", \"tls\": { \"enabled\":true, \"server_name\":\"addons.mozilla.org\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" }, \"reality\":{ \"enabled\":true, \"public_key\":\"${REALITY_PUBLIC}\", \"short_id\":\"\" } }, \"packet_encoding\": \"xudp\", \"transport\": { \"type\": \"http\" } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} h2-reality\","

  [ "${GRPC_REALITY}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} grpc-reality\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_GRPC_REALITY}, \"uuid\":\"${UUID}\", \"tls\": { \"enabled\":true, \"server_name\":\"addons.mozilla.org\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" }, \"reality\":{ \"enabled\":true, \"public_key\":\"${REALITY_PUBLIC}\", \"short_id\":\"\" } }, \"packet_encoding\": \"xudp\", \"transport\": { \"type\": \"grpc\", \"service_name\": \"grpc\" } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} grpc-reality\","

  [ "${SHADOWTLSX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"shadowsocks\", \"tag\": \"${NODE_NAME} ShadowTLS\", \"method\": \"2022-blake3-aes-128-gcm\", \"password\": \"${SHADOWTLS_PASSWORD}\", \"detour\": \"shadowtls-out\", \"udp_over_tcp\": false, \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }, { \"type\": \"shadowtls\", \"tag\": \"shadowtls-out\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_SHADOWTLS}, \"version\": 3, \"password\": \"${UUID}\", \"tls\": { \"enabled\": true, \"server_name\": \"addons.mozilla.org\", \"utls\": { \"enabled\": true, \"fingerprint\": \"chrome\" } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} ShadowTLS\","

  [ "${SHADOWSOCKSX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"shadowsocks\", \"tag\": \"${NODE_NAME} shadowsocks\", \"server\": \"${SERVER_IP}\", \"server_port\": $PORT_SHADOWSOCKS, \"method\": \"aes-128-gcm\", \"password\": \"${UUID}\", \"multiplex\": { \"enabled\": true, \"protocol\": \"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} shadowsocks\","

  [ "${TROJANX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"trojan\", \"tag\": \"${NODE_NAME} trojan\", \"server\": \"${SERVER_IP}\", \"server_port\": $PORT_TROJAN, \"password\": \"${UUID}\", \"tls\": { \"enabled\":true, \"insecure\": true, \"server_name\":\"\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" } }, \"multiplex\": { \"enabled\":true, \"protocol\":\"h2mux\", \"max_connections\": 8, \"min_streams\": 16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} trojan\","

  [ "${VLESS_WSX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} vless-ws-tls\", \"server\":\"${CDN}\", \"server_port\":443, \"uuid\":\"${UUID}\", \"tls\": { \"enabled\":true, \"server_name\":\"${ARGO_DOMAIN}\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" } }, \"transport\": { \"type\":\"ws\", \"path\":\"/${UUID}-vless\", \"headers\": { \"Host\": \"${ARGO_DOMAIN}\" }, \"max_early_data\":2048, \"early_data_header_name\":\"Sec-WebSocket-Protocol\" }, \"multiplex\": { \"enabled\":true, \"protocol\":\"h2mux\", \"max_streams\":16, \"padding\": true, \"brutal\":{ \"enabled\":true, \"up_mbps\":1000, \"down_mbps\":1000 } } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} vless-ws-tls\","

  [ "${H2_REALITYX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} h2-reality\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_H2_REALITY}, \"uuid\":\"${UUID}\", \"tls\": { \"enabled\":true, \"server_name\":\"addons.mozilla.org\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" }, \"reality\":{ \"enabled\":true, \"public_key\":\"${REALITY_PUBLIC}\", \"short_id\":\"\" } }, \"packet_encoding\": \"xudp\", \"transport\": { \"type\": \"http\" } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} h2-reality\","

  [ "${GRPC_REALITYX}" = 'true' ] &&
  local INBOUND_REPLACE+=" { \"type\": \"vless\", \"tag\": \"${NODE_NAME} grpc-reality\", \"server\": \"${SERVER_IP}\", \"server_port\": ${PORT_GRPC_REALITY}, \"uuid\":\"${UUID}\", \"tls\": { \"enabled\":true, \"server_name\":\"addons.mozilla.org\", \"utls\": { \"enabled\":true, \"fingerprint\":\"chrome\" }, \"reality\":{ \"enabled\":true, \"public_key\":\"${REALITY_PUBLIC}\", \"short_id\":\"\" } }, \"packet_encoding\": \"xudp\", \"transport\": { \"type\": \"grpc\", \"service_name\": \"grpc\" } }," &&
  local NODE_REPLACE+="\"${NODE_NAME} grpc-reality\","

  # 模板
  local SING_BOX_JSON1=$(wget -qO- --tries=3 --timeout=2 ${SUBSCRIBE_TEMPLATE}/sing-box-template)

  echo $SING_BOX_JSON1 | sed 's#, {[^}]\+"tun-in"[^}]\+}##' | sed "s#\"<INBOUND_REPLACE>\",#$INBOUND_REPLACE#; s#\"<NODE_REPLACE>\"#${NODE_REPLACE%,}#g" | $WORK_DIR/jq > $WORK_DIR/subscribe/sing-box-pc

  echo $SING_BOX_JSON1 | sed 's# {[^}]\+"mixed"[^}]\+},##; s#, "auto_detect_interface": true##' | sed "s#\"<INBOUND_REPLACE>\",#$INBOUND_REPLACE#; s#\"<NODE_REPLACE>\"#${NODE_REPLACE%,}#g" | $WORK_DIR/jq > $WORK_DIR/subscribe/sing-box-phone

  # 生成二维码 url 文件
  cat > $WORK_DIR/subscribe/qr << EOF
https://${ARGO_DOMAIN}/${UUID}/auto

QRcode:
https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://${ARGO_DOMAIN}/${UUID}/auto

$($WORK_DIR/qrencode "https://${ARGO_DOMAIN}/${UUID}/auto")
EOF

  # 生成配置文件
  EXPORT_LIST_FILE="*******************************************
┌────────────────┐
│                │
│    $(warning "Sing-box")    │
│                │
└────────────────┘
----------------------------

$(info "$(echo "{ \"outbounds\":[ ${INBOUND_REPLACE%,} ] }" | $WORK_DIR/jq)

https://github.com/chika0801/sing-box-examples/tree/main/Tun")
"

EXPORT_LIST_FILE+="*******************************************

$(hint "Index:
https://${ARGO_DOMAIN}/${UUID}/

QR code:
https://${ARGO_DOMAIN}/${UUID}/qr

sing-box for pc:
https://${ARGO_DOMAIN}/${UUID}/sing-box-pc

sing-box for mobile:
https://${ARGO_DOMAIN}/${UUID}/sing-box-phone

*******************************************

$(info " 自适应 Clash / V2rayN / NekoBox / ShadowRocket / SFI / SFA / SFM 客户端:
模版:
https://${ARGO_DOMAIN}/${UUID}/auto

 订阅 QRcode:
模版:
https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://${ARGO_DOMAIN}/${UUID}/auto")

$(hint "模版:")
$($WORK_DIR/qrencode https://${ARGO_DOMAIN}/${UUID}/auto)
"

echo "$EXPORT_LIST_FILE" > $WORK_DIR/list
cat $WORK_DIR/list


# Sing-box 的最新版本
update_sing-box() {
  local ONLINE=$(check_latest_sing-box)
  local LOCAL=$($WORK_DIR/sing-box version | awk '/version/{print $NF}')
  if [ -n "$ONLINE" ]; then
    if [[ "$ONLINE" != "$LOCAL" ]]; then
      wget https://github.com/SagerNet/sing-box/releases/download/v$ONLINE/sing-box-$ONLINE-linux-$SING_BOX_ARCH.tar.gz -O- | tar xz -C $WORK_DIR sing-box-$ONLINE-linux-$SING_BOX_ARCH/sing-box &&
      mv $WORK_DIR/sing-box-$ONLINE-linux-$SING_BOX_ARCH/sing-box $WORK_DIR/sing-box &&
      rm -rf $WORK_DIR/sing-box-$ONLINE-linux-$SING_BOX_ARCH &&
      supervisorctl restart sing-box
      info " Sing-box v${ONLINE} 更新成功！"
    else
      info " Sing-box v${ONLINE} 已是最新版本！"
    fi
  else
    warning " 获取不了在线版本，请稍后再试！"
  fi
}

# 传参
while getopts ":Vv" OPTNAME; do
  case "${OPTNAME,,}" in
    v ) ACTION=update
  esac
done

check_arch

case "$ACTION" in
  update )
    update_sing-box
    ;;
  * )
    install
    # 运行 supervisor 进程守护
    supervisord -c /etc/supervisord.conf
esac