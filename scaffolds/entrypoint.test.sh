#!/bin/sh
# Runs entrypoint.sh twice against temp dirs with a stubbed sing-box.
# Asserts: once-only seed + deploy values persist; non-outbounds client files
# refresh from the image defaults on every start (issue #14).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/bin" "$tmp/defaults"
printf '#!/bin/sh\nexit 0\n' > "$tmp/bin/sing-box"; chmod +x "$tmp/bin/sing-box"
for d in cache server client; do cp -R "$here/$d" "$tmp/defaults/$d"; done

run() {
    PATH="$tmp/bin:$PATH" SING_BOX_ROOT="$tmp/root" SING_BOX_DEFAULTS="$tmp/defaults" \
    SHADOWSOCKS_PORT="$1" SHADOWTLS_PORT=2222 SHADOWTLS_SNI=x.org SHADOWTLS_PASSWORD=pw PUBLIC_IP=1.2.3.4 \
    sh "$here/entrypoint.sh" >/dev/null
}
q() { jq -r "$2" "$tmp/root/client/$1"; }

run 1111
[ "$(q outbounds.json '.outbounds[1].server_port')" = 1111 ]
[ "$(q outbounds.json '.outbounds[1].server')" = 1.2.3.4 ]

# image update: new route.json + new outbounds.json in defaults
jq '.marker = "v2"' "$tmp/defaults/client/route.json" > "$tmp/r" && mv "$tmp/r" "$tmp/defaults/client/route.json"
jq '.marker = "v2"' "$tmp/defaults/client/outbounds.json" > "$tmp/o" && mv "$tmp/o" "$tmp/defaults/client/outbounds.json"

run 9999
[ "$(q route.json '.marker')" = v2 ]                          # refreshed from image
[ "$(q outbounds.json '.marker')" = null ]                    # not overwritten
[ "$(q outbounds.json '.outbounds[1].server_port')" = 1111 ]  # deploy value survives
[ -f "$tmp/root/server/.configured" ]
echo "entrypoint.test: ok"
