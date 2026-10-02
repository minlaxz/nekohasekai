#!/bin/sh
# Runs entrypoint.sh against temp dirs with `sing-box run` stubbed.
# `generate` and `check` use a real binary when SING_BOX names one (or sing-box is on PATH);
# without one they are faked and the `sing-box check` assertions are skipped.
# Asserts: once-only seed + deploy values persist; non-outbounds client files refresh from the
# image defaults on every start (#14); Hysteria2 setup on a fresh volume, on a volume configured
# before #22, and its idempotence (#22).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
real=${SING_BOX:-$(command -v sing-box || true)}

mkdir -p "$tmp/bin" "$tmp/defaults"
cat > "$tmp/bin/sing-box" <<EOF
#!/bin/sh
[ "\$1" = run ] && exit 0
[ -n "$real" ] && exec "$real" "\$@"
case "\$2" in
    rand) echo "rand-\$\$" ;;  # differs per call, like the real one
    tls-keypair) printf -- '-----BEGIN PRIVATE KEY-----\nkey-%s\n-----END PRIVATE KEY-----\n\n-----BEGIN CERTIFICATE-----\ncert-%s\n-----END CERTIFICATE-----\n' \$\$ \$\$ ;;
esac
EOF
chmod +x "$tmp/bin/sing-box"
for d in cache server client; do cp -R "$here/$d" "$tmp/defaults/$d"; done

run() { # run <root> <shadowsocks port> <hysteria2 port>
    PATH="$tmp/bin:$PATH" SING_BOX_ROOT="$1" SING_BOX_DEFAULTS="$tmp/defaults" \
    SHADOWSOCKS_PORT="$2" SHADOWTLS_PORT=2222 SHADOWTLS_SNI=x.org SHADOWTLS_PASSWORD=pw \
    HYSTERIA2_PORT="$3" PUBLIC_IP=1.2.3.4 \
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
check() { # real binary only: sing-box check on the Server config; certificate outlives the volume
    [ -n "$real" ] || return 0
    (cd "$1" && "$real" check -C server)
    jq -r '.inbounds[-1].tls.certificate | join("\n")' "$1/server/inbounds.json" \
        | openssl x509 -noout -checkend $((60 * 365 * 86400)) >/dev/null \
        || { echo "entrypoint.test: FAIL $1: certificate expires within 60 years" >&2; exit 1; }
}
# Hysteria2 state both sides must agree on; ss = the volume's Shadowsocks port
hysteria2_ok() { # hysteria2_ok <root> <shadowsocks port> <hysteria2 port>
    srv="$1/server/inbounds.json"; cli="$1/client/outbounds.json"
    is "$srv" '[.inbounds[] | select(.tag == "hysteria2")] | length' 1
    is "$srv" '.inbounds[-1] | [.type, .listen_port, .obfs.type, .tls.enabled]' "[hysteria2,$3,salamander,true]"
    is "$srv" '.inbounds[-1] | [.users[0].password, .obfs.password, .tls.key[0], .tls.certificate[0]] | map(length > 0) | all' true
    is "$srv" '.inbounds[-1] | .users[0].password != .obfs.password' true
    is "$1/server/route.json" '.route.rules' \
        "[{inbound:hysteria2,ip_cidr:[127.0.0.1/32],port:$2,action:route,outbound:direct-out},{inbound:hysteria2,action:reject}]"
    is "$1/server/route.json" '.route.final' direct-out

    is "$cli" "[$(ob hysteria2)] | length" 1
    is "$cli" "$(ob hysteria2) | [.server, .server_port, .obfs.type, .tls.server_name]" "[1.2.3.4,$3,salamander,hysteria2.internal]"
    is "$cli" "[$(ob shadowsocks-hy2)] | length" 1
    is "$cli" "$(ob shadowsocks-hy2) | [.server, .server_port, .detour, .password]" "[127.0.0.1,$2,hysteria2,]"
    is "$cli" "$(ob shadowsocks-hy2) | has(\"multiplex\") or has(\"network\")" false
    is "$cli" "[.outbounds[] | select(.tag == \"UDP\" or .tag == \"all-outbounds\").outbounds | map(select(. == \"shadowsocks-hy2\")) | length]" '[1,1]'
    is "$cli" "$(ob TCP) | .outbounds | index(\"shadowsocks-hy2\")" null
    # client carries the server's secrets and its certificate as the trust anchor
    jq -s '.[0].inbounds[-1] as $s | .[1].outbounds[] | select(.tag == "hysteria2")
        | [.password == $s.users[0].password, .obfs.password == $s.obfs.password, .tls.certificate == $s.tls.certificate] | all' \
        "$srv" "$cli" | grep -qx true || { echo "entrypoint.test: FAIL $1: client and server secrets differ" >&2; exit 1; }
    no 'up_mbps|down_mbps|ignore_client_bandwidth|"insecure"' "$srv" "$cli"
}

# ---- fresh volume ----
root="$tmp/root"; out="$root/client/outbounds.json"
if run "$tmp/nohy2" 1111 "" 2>"$tmp/err"; then echo "entrypoint.test: FAIL start without HYSTERIA2_PORT" >&2; exit 1; fi
grep -q 'HYSTERIA2_PORT is required' "$tmp/err" || { echo "entrypoint.test: FAIL wrong error: $(cat "$tmp/err")" >&2; exit 1; }

run "$root" 1111 3333
is "$out" '.outbounds[1].server_port' 1111
is "$out" '.outbounds[1].server' 1.2.3.4
hysteria2_ok "$root" 1111 3333
check "$root"
cp "$root/server/inbounds.json" "$tmp/in1"; cp "$root/server/route.json" "$tmp/route1"

# image update: new route.json + new outbounds.json in defaults
jq '.marker = "v2"' "$tmp/defaults/client/route.json" > "$tmp/r" && mv "$tmp/r" "$tmp/defaults/client/route.json"
jq '.marker = "v2" | .outbounds += [{type: "selector", tag: "NEW", outbounds: ["direct"]}]' "$tmp/defaults/client/outbounds.json" > "$tmp/o" && mv "$tmp/o" "$tmp/defaults/client/outbounds.json"
n=$(jq '.outbounds | length' "$out")

run "$root" 9999 4444
is "$root/client/route.json" '.marker' v2      # refreshed from image
is "$out" '.marker' null                       # not overwritten
is "$out" '.outbounds[1].server_port' 1111     # deploy value survives
is "$out" '.outbounds[-1].tag' NEW             # new outbound appended by tag
is "$out" '.outbounds | length' $((n + 1))
cp "$out" "$tmp/out2"
run "$root" 9999 4444
cmp "$out" "$tmp/out2"                         # idempotent
cmp "$root/server/inbounds.json" "$tmp/in1"    # same secrets, same certificate, same port
cmp "$root/server/route.json" "$tmp/route1"
hysteria2_ok "$root" 1111 3333
[ -f "$root/server/.configured" ]

# ---- volume configured before #22: pre-#22 shape, deploy values at the old positions ----
old="$tmp/old"; out="$old/client/outbounds.json"
for d in cache server client; do mkdir -p "$old"; cp -R "$here/$d" "$old/$d"; touch "$old/$d/.initialized"; done
touch "$old/server/.configured"
is "$here/server/inbounds.json" '[.inbounds[].tag]' '[shadowsocks,shadowtls,hysteria2]'  # scaffold shows the full shape
is "$here/server/route.json" '[.route.rules[].inbound]' '[hysteria2,hysteria2]'
jq 'del(.inbounds[] | select(.tag == "hysteria2"))
    | .inbounds[0].listen_port = 5555 | .inbounds[1].listen_port = 6666 | .inbounds[1].handshake.server = "old.org"
    | .inbounds[1].users = [{name: "shadowtls", password: "oldpw"}]' "$here/server/inbounds.json" > "$old/server/inbounds.json"
jq 'del(.route.rules)' "$here/server/route.json" > "$old/server/route.json"
no hysteria2 "$old/server/inbounds.json" "$old/server/route.json"
jq 'del(.outbounds[] | select(.tag == "hysteria2" or .tag == "shadowsocks-hy2"))
    | (.outbounds[] | select(.type == "urltest").outbounds) -= ["shadowsocks-hy2"]
    | .outbounds[1].server_port = 5555 | .outbounds[3].server_port = 6666
    | .outbounds[3].tls.server_name = "old.org" | .outbounds[3].password = "oldpw"' "$here/client/outbounds.json" > "$out"
no hy "$out"
is "$out" '.outbounds[3].tag' shadowtls

unchanged() {
    is "$old/server/inbounds.json" '.inbounds[:2] | [.[0].listen_port, .[1].listen_port, .[1].handshake.server, .[1].users[0].password]' '[5555,6666,old.org,oldpw]'
    is "$out" '.outbounds | [.[1].server_port, .[3].server_port, .[3].tls.server_name, .[3].password]' '[5555,6666,old.org,oldpw]'
    is "$out" '.outbounds | [.[1].tag, .[3].tag, .[1].server, .[3].server]' '[shadowsocks-udp,shadowtls,1.2.3.4,1.2.3.4]'
}
run "$old" 9999 4444
unchanged
hysteria2_ok "$old" 5555 4444
check "$old"
for f in server/inbounds.json server/route.json client/outbounds.json; do cp "$old/$f" "$tmp/$(basename "$f").old"; done
run "$old" 9999 7777; run "$old" 9999 7777
for f in server/inbounds.json server/route.json client/outbounds.json; do cmp "$old/$f" "$tmp/$(basename "$f").old"; done
unchanged

echo "entrypoint.test: ok${real:+ (real sing-box)}"
