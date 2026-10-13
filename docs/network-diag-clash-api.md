# Network diagnostics: Clash API

Index: [network-diag.md](network-diag.md).

Requires `experimental.clash_api.external_controller` (here `127.0.0.1:9090`).
If `clash_api.secret` is set, add `-H 'Authorization: Bearer <secret>'` to
each `curl`; without it the API answers `401`.

## Which member each group selected, and last measured delay

```sh
curl -s 127.0.0.1:9090/proxies | python3 -c "
import sys, json
d = json.load(sys.stdin)['proxies']
for k, v in d.items():
    print(k, v.get('type'), v.get('now', ''), [h.get('delay') for h in v.get('history', [])][-1:])
"
```

Read: `now` is the active member of a selector/urltest. Empty `[]` delay on an
endpoint (OpenVPN, Tailscale, WireGuard) is normal; endpoints are not url-tested.

## Active connections, with outbound chain and matched rule

```sh
curl -s 127.0.0.1:9090/connections | python3 -c "
import sys, json
d = json.load(sys.stdin)
for c in d.get('connections', []):
    m = c['metadata']
    print(m.get('destinationIP'), m.get('destinationPort'), m.get('host'), c['chains'], c.get('rule'), c.get('upload'), c.get('download'))
" | sort | uniq -c | sort -rn | head -40
```

Read: `chains` lists the final outbound first and the group last, e.g.
`['shadowsocks-uot', 'UDP']` means the `UDP` group picked `shadowsocks-uot`. Shows the real path a
destination takes, which is what you want when a route rule looks right but
traffic behaves wrong.
