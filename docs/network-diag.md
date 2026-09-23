# Network diagnostics

Command cookbook for diagnosing sing-box tunnels from the macOS client.
Append new commands here whenever a diagnosis session uses one.

Each entry: what it tells you, the command, how to read the output.

## Clash API (sing-box state)

Requires `experimental.clash_api.external_controller` (here `127.0.0.1:9090`).
If `clash_api.secret` is set, add `-H 'Authorization: Bearer <secret>'` to
each `curl`; without it the API answers `401`.

### Which member each group selected, and last measured delay

```sh
curl -s 127.0.0.1:9090/proxies | python3 -c "
import sys, json
d = json.load(sys.stdin)['proxies']
for k, v in d.items():
    print(k, v.get('type'), v.get('now', ''), [h.get('delay') for h in v.get('history', [])][-1:])
"
```

Read: `now` is the active member of a selector/urltest. Empty `[]` delay on an
endpoint (OpenVPN, Tailscale) is normal; endpoints are not url-tested.

### Active connections, with outbound chain and matched rule

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

## Reachability and latency

### RTT to a host

```sh
ping -c 4 -i 0.3 <ip>
```

`-c 4` four probes, `-i 0.3` 300 ms apart. Last line gives min/avg/max. 100%
loss on a public server often means ICMP is filtered, not that the host is
down. Confirm with an HTTP request (next section), not only with `nc`.

### TCP port reachable

```sh
nc -z -v -G 5 <ip> <port>
```

`-z` no data, `-v` print result, `-G 5` connect timeout 5 s. Output
`succeeded!` or `Connection refused` / timeout.

Caveat under the sing-box tun: the tun stack completes the TCP handshake
locally, then dials the outbound. So `succeeded!` proves only that the route
matched. The remote port can still be closed or unreachable. Proof of the
remote end needs data back: use the `curl` line below, or read the sing-box
log for the outbound dial error. `Connection refused` or a timeout is still a
real failure.

### TCP works but an app says "connection refused"

`nc` does not prove the remote end (see above). An app can also fail where
`curl` works because of proxy env vars.

```sh
env | grep -i -E '^(http|https|all|no)_proxy='
curl -sv --noproxy '*' http://<ip>:<port>/ -o /dev/null 2>&1 | grep -E '^(< HTTP|\* Connected|curl:)'
NODE_USE_ENV_PROXY=1 node -e "fetch('http://<ip>:<port>/').then(r=>console.log(r.status)).catch(e=>console.error(e.cause||e))"
```

Line 1: any `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` makes Claude Code connect to
the proxy instead of `<ip>`. A dead proxy gives `ECONNREFUSED` on the proxy
port, reported as "firewall or proxy might be blocking". Fix: `unset` them or
add `<ip>` to `NO_PROXY`. Line 2: `--noproxy '*'` bypasses env proxies. An
`< HTTP` line proves the remote answered on the routed path. Line 3: plain
Node `fetch` ignores proxy env vars; `NODE_USE_ENV_PROXY=1` (Node 22.21+ or
24+) makes it use them, as Claude Code does. The printed `cause` names the
real address and errno. Drop the variable to test the direct path.

## MTU / MSS blackhole

Symptom: small responses arrive, large ones stall. Tiny 302 redirect loads,
real page hangs until timeout. Ping works. That is a path MTU problem.

### Find the largest packet that passes without fragmentation

```sh
ping -c 4 <ip>                     # 56-byte payload (macOS default)
ping -D -s 1000 -c 4 <ip>          # 1000-byte payload, -D = don't fragment
ping -D -s 1350 -c 4 <ip>
ping -D -s 1400 -c 4 <ip>
```

`-s N` sets ICMP payload bytes. IP packet size = N + 8 (ICMP) + 20 (IPv4).
Step sizes until loss or RTT jumps, then bisect between the last pass and the
first fail. A clean limit gives 100% loss above it. `ping: sendto: Message too
long` means a local interface MTU refused the packet before it left the Mac.
Example from the OpenVPN case: 1350 passed at 112 ms, 1400 lost half and took
641 ms. Partial loss suggests the limit sits near 1400; probing 1370, 1380,
1390 would have narrowed it.

### Confirm with HTTP

```sh
curl -o /dev/null -s -L -m 90 -w 'url=%{url_effective} connect=%{time_connect} ttfb=%{time_starttransfer} total=%{time_total} size=%{size_download} speed=%{speed_download} code=%{http_code}\n' http://<ip>/
```

Read: `connect` fast and `ttfb` reasonable but `total` hitting `-m` timeout
with small `size` means the first segments arrived and the rest never did.
Run once without `-L` to compare a tiny redirect body against the full page.

### Fix pattern (sing-box OpenVPN endpoint)

`mss_fix` clamps TCP MSS in both directions; `mtu` caps the tunnel interface.
Pick `mtu` under the probed ceiling, then MSS = MTU - 40 (20 IPv4 + 20 TCP
header bytes). Example: `"mtu": 1380`, `"mss_fix": 1340`.

### Worked case: OpenVPN client over shadowtls (2026-09-23)

Setup: `openvpn-client` endpoint, `network: tcp`, detoured through a
shadowsocks + shadowtls outbound (OpenVPN signature blocked locally, so the
extra TCP wrap is required). Web server on `192.168.10.1` behind the VPN.

Symptom: ping fine, `curl http://192.168.10.1/` (302, 270 bytes) done in
0.4 s, but `curl -L` to `/login` got 448 bytes then hung until the 90 s
timeout.

Why: endpoint `mtu` defaulted to 1500, so the tunnel's TCP stack advertised
MSS 1460, and the web server sent segments up to 1500 bytes. The outer
transport is TCP, which splits any inner packet into its own stream, so the
Mac-to-server leg cannot drop packets for size. The limit is past the
OpenVPN server: its tun MTU or the server-side LAN. No ICMP "fragmentation
needed" reached the sender, so TCP never shrank the segment size (not
verified where the ICMP was lost). Result: a PMTU blackhole where only
packets under the real ceiling arrive.

Proof: don't-fragment pings passed at 1350-byte payload (112 ms RTT) and half
failed at 1400 (641 ms). Ceiling between 1378 and 1428 bytes per IP packet.

Change on the endpoint:

```json
"mss_fix": 1350,
"mtu": 1380
```

`mss_fix` rewrites the MSS option in SYN packets crossing the tunnel, both
directions, so the web server also sends segments the path can carry. `mtu`
backs that up for non-TCP traffic and for any flow that skips the clamp.

Note: MSS 1350 allows 1390-byte packets, 10 over `mtu` 1380. It worked, so
the real ceiling is at least 1390 bytes. The consistent pair is
`"mss_fix": 1340` with `"mtu": 1380`; use it if large responses stall again.

After: `curl -L` returned the full 3649-byte page in 2.9 s. That is about 26
tunnel RTTs (~112 ms each). Likely cause: a redirect plus a new connection,
each with TCP and HTTP round trips, over a TCP-over-TCP path. Not measured
per phase; use the `-w` timings above to split it.

Also changed `detour` from the `UDP` urltest group to `TCP`: the endpoint
speaks TCP, and `UDP` held a udp-only shadowsocks member that could never
carry it. Cosmetic, not part of the fix.

## Local interfaces

### MTU of every utun

```sh
ifconfig | grep -A3 utun | grep -E 'utun|mtu|inet '
```

The sing-box tun is the one carrying the tun inbound address (here
`10.10.10.1`). Other utuns belong to Tailscale, VPN apps, iCloud Private Relay.

## Config sanity

```sh
sing-box check -c <config>.jsonc     # when the binary is on PATH
python3 -c "import json; json.load(open('<config>.json')); print('json ok')"
```

`sing-box check` accepts JSONC (comments, trailing commas). It catches
unknown fields and bad option combinations that plain JSON parsing cannot.
The `python3` line is only for pure `.json` files: it fails on any comment,
so a `.jsonc` config gives a false error.
