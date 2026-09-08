#!/bin/sh
# Fill ${MUX_*} placeholders in config.json from env, check, run.
set -e

TMPL="${MUX_CONFIG_TEMPLATE:-/config.json.tmpl}"
OUT="${MUX_CONFIG_OUT:-/tmp/config.json}"

for v in MUX_TS_CONTROL_URL MUX_TS_HOSTNAME; do
    eval "[ -n \"\$$v\" ]" || { echo "entrypoint: $v is required" >&2; exit 1; }
done
# MUX_TS_AUTH_KEY may be empty once /data/tailscale holds state.

# MUX_USER_<NAME>_TOKEN=<token>  ->  {"name":"<name>","token":"<token>"}
users=""
for kv in $(env | grep '^MUX_USER_[A-Za-z0-9]*_TOKEN=.' | sort); do
    name=$(echo "${kv%%=*}" | sed 's/^MUX_USER_//; s/_TOKEN$//' | tr 'A-Z' 'a-z')
    users="$users{\"name\":\"$name\",\"token\":\"${kv#*=}\"},"
done
[ -n "$users" ] || { echo "entrypoint: no MUX_USER_<NAME>_TOKEN set" >&2; exit 1; }
users="[${users%,}]"

cp "$TMPL" "$OUT"
# ponytail: sed, not jq; base image has no jq. Values must not contain | & or ".
sed -i "s|\"\${MUX_USERS}\"|$users|g" "$OUT"
for v in MUX_TS_AUTH_KEY MUX_TS_CONTROL_URL MUX_TS_HOSTNAME; do
    eval "val=\$$v"
    sed -i "s|\${$v}|$val|g" "$OUT"
done

sing-box check -c "$OUT"
exec sing-box run -c "$OUT"
