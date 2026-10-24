#!/bin/sh
set -e

ROOT="${SING_BOX_ROOT:-/sing-box}"
DEFAULTS="${SING_BOX_DEFAULTS:-/defaults}"   # image copy; lives outside the volume mount
SERVER_IN="$ROOT/server/inbounds.json"
CLIENT_OUT="$ROOT/client/outbounds.json"

die() { echo "entrypoint: $*" >&2; exit 1; }

# Deploy values. Compose refuses to start without them; checked here too for runs outside compose.
for v in SHADOWSOCKS_PORT SHADOWSOCKS_PASSWORD SHADOWTLS_PORT SHADOWTLS_SNI SHADOWTLS_PASSWORD; do
    eval "[ -n \"\${$v:-}\" ]" || die "$v is required"
done

# Both sing-box sides take the SS-2022 server PSK as exactly 16 base64-encoded bytes (#24).
[ "$(printf %s "$SHADOWSOCKS_PASSWORD" | base64 -d 2>/dev/null | wc -c | tr -d ' ')" = 16 ] \
    || die "SHADOWSOCKS_PASSWORD must be 16 base64-encoded bytes: openssl rand -base64 16"

# jq in-place edit
jqi() { # jqi <file> <filter> [jq args...]
    f="$1"; shift
    jq "$@" > "$f.tmp" < "$f" && mv "$f.tmp" "$f"
}

# ---- seed persistent dirs (once) ----
for d in server client cache; do
    if [ ! -f "$ROOT/$d/.initialized" ]; then
        mkdir -p "$ROOT/$d"
        cp -a "$DEFAULTS/$d/." "$ROOT/$d/"
        touch "$ROOT/$d/.initialized"
    fi
done
# pre-#14 images seeded from *.default dirs inside the volume; they are stale and unused now
for d in "$ROOT"/*.default; do
    [ -d "$d" ] && rm -rf "$d" && echo "entrypoint: removed stale $d"
done

# ---- every start: Template refresh (#14) ----
# outbounds.json holds Deploy values and is never refreshed;
# every other client file is copied from the image. Additive: files dropped from the image linger.
for f in "$DEFAULTS"/client/*.json; do
    case "$f" in */outbounds.json) ;; *) cp -a "$f" "$ROOT/client/" ;; esac
done
# outbounds.json: append outbounds the image added (matched by tag) so new groups reach old volumes;
# existing entries and their deploy values are left alone
jqi "$CLIENT_OUT" --slurpfile img "$DEFAULTS/client/outbounds.json" \
    '(.outbounds | map(.tag)) as $have
    | .outbounds += [$img[0].outbounds[] | select(.tag as $t | $have | index($t) | not)]'

# ---- first-init only: ports + SNI ----
if [ ! -f "$ROOT/server/.configured" ]; then
    # ShadowTLS is transport only; one shared handshake password for everyone.
    # Per-user auth happens in the Shadowsocks inbound (ssm-api).
    jqi "$SERVER_IN" \
        --argjson ss "$SHADOWSOCKS_PORT" --argjson stls "$SHADOWTLS_PORT" \
        --arg sni "$SHADOWTLS_SNI" --arg pw "$SHADOWTLS_PASSWORD" \
        '.inbounds[0].listen_port = $ss
        | .inbounds[1].listen_port = $stls
        | .inbounds[1].handshake.server = $sni
        | .inbounds[1].users = [{name: "shadowtls", password: $pw}]'

    # No client reaches the Shadowsocks port directly: ShadowTLS carries it (#30).
    jqi "$CLIENT_OUT" \
        --argjson stls "$SHADOWTLS_PORT" --arg sni "$SHADOWTLS_SNI" --arg pw "$SHADOWTLS_PASSWORD" \
        '(.outbounds[] | select(.tag == "shadowtls")) |= (
            .server_port = $stls | .tls.server_name = $sni | .password = $pw)'

    touch "$ROOT/server/.configured"
    echo "entrypoint: configured ports ss=$SHADOWSOCKS_PORT shadowtls=$SHADOWTLS_PORT sni=$SHADOWTLS_SNI"
fi

# ---- once: Shadowsocks 2022 (#24) ----
# Own gate, so a volume configured before #24 is upgraded on its next start.
# The server PSK comes from .env and is written to the inbound and to the client Shadowsocks
# outbound; the API appends ":<user key>" per Profile config. The ssm-api cache holds users under
# their old keys, which the new method cannot decode, so it is reset; the API reseeds every user
# from users.json on its next start (traffic counters restart from zero).
if [ ! -f "$ROOT/server/.ss2022" ]; then
    method=$(jq -r '.inbounds[0].method' "$DEFAULTS/server/inbounds.json")
    jqi "$SERVER_IN" --arg m "$method" --arg pw "$SHADOWSOCKS_PASSWORD" \
        '(.inbounds[] | select(.tag == "shadowsocks")) |= (.method = $m | .password = $pw)'
    jqi "$CLIENT_OUT" --arg m "$method" --arg pw "$SHADOWSOCKS_PASSWORD" \
        '(.outbounds[] | select(.type == "shadowsocks")) |= (.method = $m | .password = $pw)'
    cp "$DEFAULTS/cache/ssm-cache.json" "$ROOT/cache/ssm-cache.json"
    touch "$ROOT/server/.ss2022"
    echo "entrypoint: configured shadowsocks method=$method"
fi

# ---- every start: public IPv4 ----
ip="$PUBLIC_IP"
if [ -z "$ip" ]; then
    for url in http://checkip.amazonaws.com http://api.ipify.org http://ifconfig.me/ip; do
        ip=$(wget -qO- -T 5 "$url" 2>/dev/null | tr -d '[:space:]') && [ -n "$ip" ] && break
    done
fi
echo "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' \
    || die "could not detect public IPv4 (got '$ip'); set PUBLIC_IP to override"
jqi "$CLIENT_OUT" --arg ip "$ip" \
    '(.outbounds[] | select(.tag == "shadowtls")).server = $ip'
echo "entrypoint: public ip $ip"

exec sing-box run -C "$ROOT/server"
