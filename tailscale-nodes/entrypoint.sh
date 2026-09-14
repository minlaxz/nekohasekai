#!/bin/sh
# Fill ${TSN_*} placeholders in config.json from env, check, run.
# TSN_ not TS_: the embedded tailscale reads TS_* env vars on its own.
set -e

TMPL="${TSN_CONFIG_TEMPLATE:-/config.json.tmpl}"
OUT="${TSN_CONFIG_OUT:-/tmp/config.json}"
VARS="TSN_AUTH_KEY TSN_CONTROL_URL TSN_HOSTNAME"

# Ephemeral node + tmpfs state: every start registers anew, so the key is always required.
for v in $VARS; do
    eval "[ -n \"\$$v\" ]" || { echo "entrypoint: $v is required" >&2; exit 1; }
done

cp "$TMPL" "$OUT"
# ponytail: sed, not jq; base image has no jq. Values must not contain | & or ".
for v in $VARS; do
    eval "val=\$$v"
    sed -i "s|\${$v}|$val|g" "$OUT"
done

sing-box check -c "$OUT"
exec sing-box run -c "$OUT"
