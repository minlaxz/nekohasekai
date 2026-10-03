#!/bin/sh
set -e

ROOT="${SING_BOX_ROOT:-/sing-box}"
DEFAULTS="${SING_BOX_DEFAULTS:-/defaults}"   # image copy; lives outside the volume mount
SERVER_IN="$ROOT/server/inbounds.json"
CLIENT_OUT="$ROOT/client/outbounds.json"
# Never on the wire (Salamander hides the handshake); it only has to match the certificate's SAN.
HYSTERIA2_CERT_NAME=hysteria2.internal

die() { echo "entrypoint: $*" >&2; exit 1; }

# Deploy values. Compose refuses to start without them; checked here too for runs outside compose.
for v in SHADOWSOCKS_PORT SHADOWSOCKS_PASSWORD SHADOWTLS_PORT HYSTERIA2_PORT HYSTERIA2_PASSWORD \
         HYSTERIA2_OBFS_PASSWORD SHADOWTLS_SNI SHADOWTLS_PASSWORD; do
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
# outbounds.json holds Deploy values and the Hysteria2 certificate and is never refreshed;
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

    # No client reaches the Shadowsocks port directly: only the two Transports carry it (#30).
    jqi "$CLIENT_OUT" \
        --argjson stls "$SHADOWTLS_PORT" --arg sni "$SHADOWTLS_SNI" --arg pw "$SHADOWTLS_PASSWORD" \
        '(.outbounds[] | select(.tag == "shadowtls")) |= (
            .server_port = $stls | .tls.server_name = $sni | .password = $pw)'

    touch "$ROOT/server/.configured"
    echo "entrypoint: configured ports ss=$SHADOWSOCKS_PORT shadowtls=$SHADOWTLS_PORT sni=$SHADOWTLS_SNI"
fi

# ---- once: Hysteria2 transport (#22) ----
# Own gate, not .configured, so a volume configured before #22 is upgraded on its next start.
# Transport only, like ShadowTLS: one shared password, Shadowsocks runs inside.
# The two passwords come from .env, like the ShadowTLS password; the certificate is generated.
# All three are written once and kept in the volume.
if [ ! -f "$ROOT/server/.hysteria2" ]; then
    ss=$(jq '.inbounds[] | select(.tag == "shadowsocks").listen_port' "$SERVER_IN")  # the volume's port, not .env's
    pw="$HYSTERIA2_PASSWORD"
    obfs="$HYSTERIA2_OBFS_PASSWORD"
    # RSA, 100 years: the Client template pins this certificate, and Ed25519 breaks the QUIC parrot.
    pem=$(sing-box generate tls-keypair "$HYSTERIA2_CERT_NAME" -m 1200)
    key=$(echo "$pem" | sed -n '/BEGIN PRIVATE KEY/,/END PRIVATE KEY/p')
    cert=$(echo "$pem" | sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p')
    [ -n "$key" ] && [ -n "$cert" ] || die "could not generate the Hysteria2 certificate"

    # Server config is never refreshed, so a volume seeded before #22 lacks the scaffold's
    # hysteria2 inbound and route rules: take them from the image, then fill in the values.
    jqi "$SERVER_IN" --slurpfile img "$DEFAULTS/server/inbounds.json" --argjson port "$HYSTERIA2_PORT" \
        --arg pw "$pw" --arg obfs "$obfs" --arg key "$key" --arg cert "$cert" \
        '.inbounds |= map(select(.tag != "hysteria2")) + [$img[0].inbounds[] | select(.tag == "hysteria2")]
        | (.inbounds[] | select(.tag == "hysteria2")) |= (
            .listen_port = $port | .users = [{name: "hysteria2", password: $pw}] | .obfs.password = $obfs
            | .tls.certificate = ($cert | split("\n")) | .tls.key = ($key | split("\n")))'

    # The shared password alone reaches nothing but the Shadowsocks inbound (TCP and UDP).
    jqi "$ROOT/server/route.json" --slurpfile img "$DEFAULTS/server/route.json" --argjson ss "$ss" \
        '.route.rules = [$img[0].route.rules[] | select(.inbound == "hysteria2")]
            + [(.route.rules // [])[] | select(.inbound != "hysteria2")]
        | (.route.rules[] | select(.inbound == "hysteria2" and .action == "route")).port = $ss'

    jqi "$CLIENT_OUT" --argjson port "$HYSTERIA2_PORT" --argjson ss "$ss" \
        --arg pw "$pw" --arg obfs "$obfs" --arg cert "$cert" --arg name "$HYSTERIA2_CERT_NAME" \
        '(.outbounds[] | select(.tag == "hysteria2")) |= (
            .server_port = $port | .password = $pw | .obfs.password = $obfs
            | .tls.server_name = $name | .tls.certificate = ($cert | split("\n")))
        | (.outbounds[] | select(.tag == "shadowsocks-hy2")).server_port = $ss
        | (.outbounds[] | select(.tag == "Proxy").outbounds)
            |= if index("shadowsocks-hy2") then . else . + ["shadowsocks-hy2"] end'

    touch "$ROOT/server/.hysteria2"
    echo "entrypoint: configured hysteria2 port=$HYSTERIA2_PORT"
fi

# ---- once: Shadowsocks 2022 (#24) ----
# Own gate, so a volume configured before #24 is upgraded on its next start.
# The server PSK comes from .env and is written to the inbound and to both client Shadowsocks
# outbounds; the API appends ":<user key>" per Profile config. The ssm-api cache holds users under
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
    '(.outbounds[] | select(.tag == "shadowtls" or .tag == "hysteria2")).server = $ip'
echo "entrypoint: public ip $ip"

exec sing-box run -C "$ROOT/server"
