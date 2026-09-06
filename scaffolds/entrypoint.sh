#!/bin/sh
set -e

ROOT="${SING_BOX_ROOT:-/sing-box}"
USERS_FILE="${USERS_FILE:-/users.json}"
SERVER_IN="$ROOT/server/inbounds.json"
CLIENT_OUT="$ROOT/client/outbounds.json"

die() { echo "entrypoint: $*" >&2; exit 1; }

# jq in-place edit
jqi() { # jqi <file> <filter> [jq args...]
    f="$1"; shift
    jq "$@" > "$f.tmp" < "$f" && mv "$f.tmp" "$f"
}

# ---- seed persistent dirs (once) ----
for d in server client cache; do
    if [ ! -f "$ROOT/$d/.initialized" ]; then
        mkdir -p "$ROOT/$d"
        cp -a "$ROOT/$d.default/." "$ROOT/$d/"
        touch "$ROOT/$d/.initialized"
    fi
done

# ---- first-init only: ports + SNI ----
if [ ! -f "$ROOT/server/.configured" ]; then
    : "${SHADOWSOCKS_PORT:?SHADOWSOCKS_PORT is required}"
    : "${SHADOWTLS_PORT:?SHADOWTLS_PORT is required}"
    : "${SHADOWTLS_SNI:?SHADOWTLS_SNI is required}"

    jqi "$SERVER_IN" \
        --argjson ss "$SHADOWSOCKS_PORT" --argjson stls "$SHADOWTLS_PORT" --arg sni "$SHADOWTLS_SNI" \
        '.inbounds[0].listen_port = $ss
        | .inbounds[1].listen_port = $stls
        | .inbounds[1].handshake.server = $sni'

    jqi "$CLIENT_OUT" \
        --argjson ss "$SHADOWSOCKS_PORT" --argjson stls "$SHADOWTLS_PORT" --arg sni "$SHADOWTLS_SNI" \
        '.outbounds[1].server_port = $ss
        | .outbounds[3].server_port = $stls
        | .outbounds[3].tls.server_name = $sni'

    touch "$ROOT/server/.configured"
    echo "entrypoint: configured ports ss=$SHADOWSOCKS_PORT shadowtls=$SHADOWTLS_PORT sni=$SHADOWTLS_SNI"
fi

# ---- every start: shadowtls users from users.json ----
[ -f "$USERS_FILE" ] || die "$USERS_FILE not found (mount ./users.json)"
users=$(jq -c '[.users[] | {name, password}]' "$USERS_FILE") || die "$USERS_FILE is not valid JSON"
[ "$users" = "[]" ] && echo "entrypoint: warning: no users in $USERS_FILE" >&2
jqi "$SERVER_IN" --argjson u "$users" '.inbounds[1].users = $u'

# ---- every start: public IPv4 ----
ip="$PUBLIC_IP"
if [ -z "$ip" ]; then
    for url in http://checkip.amazonaws.com http://api.ipify.org http://ifconfig.me/ip; do
        ip=$(wget -qO- -T 5 "$url" 2>/dev/null | tr -d '[:space:]') && [ -n "$ip" ] && break
    done
fi
echo "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' \
    || die "could not detect public IPv4 (got '$ip'); set PUBLIC_IP to override"
jqi "$CLIENT_OUT" --arg ip "$ip" '.outbounds[1].server = $ip | .outbounds[3].server = $ip'
echo "entrypoint: public ip $ip"

exec sing-box run -C "$ROOT/server"
