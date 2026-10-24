#!/bin/sh
# Runs entrypoint.sh against temp dirs with `sing-box run` stubbed.
# `check` uses a real binary when SING_BOX names one (or sing-box is on PATH);
# without one the `sing-box check` assertions are skipped.
# Asserts: once-only seed + deploy values persist; non-outbounds client files refresh from the
# image defaults on every start (#14); ShadowTLS as the sole transport without Hysteria2
# settings; SS-2022 on a fresh volume and on a volume configured
# before #24: method, server PSK on both sides, cache reset (#24).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
real=${SING_BOX:-$(command -v sing-box || true)}

sspw=AAAAAAAAAAAAAAAAAAAAAA==  # 16 zero bytes: a well-formed SS-2022 server PSK
mkdir -p "$tmp/bin" "$tmp/defaults"
cat > "$tmp/bin/sing-box" <<EOF
#!/bin/sh
[ "\$1" = run ] && exit 0
[ -n "$real" ] && exec "$real" "\$@"
echo "entrypoint.test: unexpected sing-box command: \$*" >&2
exit 1
EOF
chmod +x "$tmp/bin/sing-box"
for d in cache server client; do cp -R "$here/$d" "$tmp/defaults/$d"; done

run() { # run <root> <shadowsocks port>
    PATH="$tmp/bin:$PATH" SING_BOX_ROOT="$1" SING_BOX_DEFAULTS="$tmp/defaults" \
    SHADOWSOCKS_PORT="$2" SHADOWSOCKS_PASSWORD="${SHADOWSOCKS_PASSWORD-$sspw}" \
    SHADOWTLS_PORT=2222 SHADOWTLS_SNI=x.org SHADOWTLS_PASSWORD=pw \
    PUBLIC_IP=1.2.3.4 \
    sh "$here/entrypoint.sh" >/dev/null
}
is() { # is <file> <jq filter> <want>
    got=$(jq -c "$2" "$1" | tr -d '"')
    [ "$got" = "$3" ] || { echo "entrypoint.test: FAIL $1: $2 = $got, want $3" >&2; exit 1; }
}
no() { # no <grep -E pattern> <file>...
    if grep -Eq "$@"; then echo "entrypoint.test: FAIL found $1" >&2; exit 1; fi
}
ob() { echo ".outbounds[] | select(.tag == \"$1\")"; }
check() { # real binary only: sing-box check on the Server config
    [ -n "$real" ] || return 0
    (cd "$1" && "$real" check -C server)
}
# SS-2022 state both sides must agree on (#24)
ss2022_ok() { # ss2022_ok <root>
    srv="$1/server/inbounds.json"; cli="$1/client/outbounds.json"
    is "$srv" '.inbounds[0] | [.tag, .method, .password, .managed]' "[shadowsocks,2022-blake3-aes-128-gcm,$sspw,true]"
    is "$cli" '[.outbounds[] | select(.type == "shadowsocks") | [.method, .password]] | unique' "[[2022-blake3-aes-128-gcm,$sspw]]"
    is "$1/cache/ssm-cache.json" '.endpoints["/"] | [.users, .user_uplink, .global_uplink]' '[{},{},0]'
    no xchacha20 "$srv" "$cli"
}
# Retirement must not require any Hysteria2 deploy values.
unset HYSTERIA2_PORT HYSTERIA2_PASSWORD HYSTERIA2_OBFS_PASSWORD

# ---- fresh volume ----
root="$tmp/root"; out="$root/client/outbounds.json"
if (SHADOWSOCKS_PASSWORD= run "$tmp/nopw" 1111) 2>"$tmp/err"; then echo "entrypoint.test: FAIL start without SHADOWSOCKS_PASSWORD" >&2; exit 1; fi
grep -q "SHADOWSOCKS_PASSWORD is required" "$tmp/err" || { echo "entrypoint.test: FAIL wrong error: $(cat "$tmp/err")" >&2; exit 1; }

if (SHADOWSOCKS_PASSWORD=short run "$tmp/badpw" 1111) 2>"$tmp/err"; then echo "entrypoint.test: FAIL start with a short SHADOWSOCKS_PASSWORD" >&2; exit 1; fi
grep -q "16 base64-encoded bytes" "$tmp/err" || { echo "entrypoint.test: FAIL wrong error: $(cat "$tmp/err")" >&2; exit 1; }

run "$root" 1111
is "$out" "$(ob shadowtls) | [.server, .server_port, .tls.server_name, .password]" '[1.2.3.4,2222,x.org,pw]'
is "$out" '[.outbounds[].tag]' '[shadowsocks-uot,shadowtls,direct,Proxy,All,Remote DNS Detour]'
is "$root/server/inbounds.json" '.inbounds[0] | [.tag, .listen]' '[shadowsocks,127.0.0.1]'
is "$root/server/route.json" '.route.rules[0]' '{inbound:shadowsocks,ip_is_private:true,action:reject}'
is "$root/server/inbounds.json" '[.inbounds[].tag]' '[shadowsocks,shadowtls]'
is "$out" "$(ob Proxy) | .outbounds" '[shadowsocks-uot]'
is "$out" "$(ob All) | .outbounds" '[direct,shadowsocks-uot]'
is "$out" "$(ob shadowsocks-uot) | [.detour, .udp_over_tcp.enabled]" '[shadowtls,true]'
no hysteria2 "$root/server/inbounds.json" "$root/server/route.json" "$out"
ss2022_ok "$root"
check "$root"
cp "$root/server/inbounds.json" "$tmp/in1"; cp "$root/server/route.json" "$tmp/route1"

# image update: new route.json + new outbounds.json in defaults
jq '.marker = "v2"' "$tmp/defaults/client/route.json" > "$tmp/r" && mv "$tmp/r" "$tmp/defaults/client/route.json"
jq '.marker = "v2" | .outbounds += [{type: "selector", tag: "NEW", outbounds: ["direct"]}]' "$tmp/defaults/client/outbounds.json" > "$tmp/o" && mv "$tmp/o" "$tmp/defaults/client/outbounds.json"
n=$(jq '.outbounds | length' "$out")

run "$root" 9999
is "$root/client/route.json" '.marker' v2      # refreshed from image
is "$out" '.marker' null                       # not overwritten
is "$out" "$(ob shadowtls) | .server_port" 2222  # deploy value survives
is "$out" '.outbounds[-1].tag' NEW             # new outbound appended by tag
is "$out" '.outbounds | length' $((n + 1))
cp "$out" "$tmp/out2"
run "$root" 9999
cmp "$out" "$tmp/out2"                         # idempotent
cmp "$root/server/inbounds.json" "$tmp/in1"    # same password, same port
cmp "$root/server/route.json" "$tmp/route1"
ss2022_ok "$root"
[ -f "$root/server/.configured" ]

# ---- SS-2022 upgrade for an older ShadowTLS-only volume (#24) ----
old="$tmp/old"; out="$old/client/outbounds.json"
for d in cache server client; do mkdir -p "$old"; cp -R "$here/$d" "$old/$d"; touch "$old/$d/.initialized"; done
touch "$old/server/.configured"
is "$here/server/inbounds.json" '[.inbounds[].tag]' '[shadowsocks,shadowtls]'  # scaffold shows the full shape
is "$here/server/route.json" '[.route.rules[].inbound]' '[shadowsocks]'
jq 'del(.inbounds[0].password)
    | .inbounds[0].method = "xchacha20-ietf-poly1305" | .inbounds[0].listen_port = 5555 | .inbounds[1].listen_port = 6666 | .inbounds[1].handshake.server = "old.org"
    | .inbounds[1].users = [{name: "shadowtls", password: "oldpw"}]' "$here/server/inbounds.json" > "$old/server/inbounds.json"
jq 'del(.route.rules)' "$here/server/route.json" > "$old/server/route.json"
no hysteria2 "$old/server/inbounds.json" "$old/server/route.json"
jq '(.outbounds[] | select(.type == "shadowsocks")).method = "xchacha20-ietf-poly1305"
    | (.outbounds[] | select(.tag == "shadowtls")) |= (.server_port = 6666 | .tls.server_name = "old.org" | .password = "oldpw")' \
    "$here/client/outbounds.json" > "$out"
no hysteria2 "$out"
jq '.endpoints["/"] |= (.users = {alice: "a"} | .user_uplink = {alice: 7} | .global_uplink = 7)' \
    "$here/cache/ssm-cache.json" > "$old/cache/ssm-cache.json"

unchanged() {
    is "$old/server/inbounds.json" '.inbounds[:2] | [.[0].listen_port, .[1].listen_port, .[1].handshake.server, .[1].users[0].password]' '[5555,6666,old.org,oldpw]'
    is "$out" "$(ob shadowtls) | [.server, .server_port, .tls.server_name, .password]" '[1.2.3.4,6666,old.org,oldpw]'
}
run "$old" 9999
unchanged
ss2022_ok "$old"
check "$old"
for f in server/inbounds.json server/route.json client/outbounds.json; do cp "$old/$f" "$tmp/$(basename "$f").old"; done
run "$old" 9999; run "$old" 9999
for f in server/inbounds.json server/route.json client/outbounds.json; do cmp "$old/$f" "$tmp/$(basename "$f").old"; done
unchanged

echo "entrypoint.test: ok${real:+ (real sing-box)}"
