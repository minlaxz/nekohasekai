# Network diagnostics

Command cookbook for diagnosing sing-box tunnels from the macOS client.
Append new commands here whenever a diagnosis session uses one.

Each entry: what it tells you, the command, how to read the output.

## Clash API (sing-box state)

Requires `experimental.clash_api.external_controller` (here `127.0.0.1:9090`).

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

Read: `chains` lists outbounds innermost first, e.g. `['shadowsocks-uot', 'UDP']`
means the `UDP` group picked `shadowsocks-uot`. Shows the real path a
destination takes, which is what you want when a route rule looks right but
traffic behaves wrong.

## Reachability and latency

### RTT to a host

```sh
ping -c 4 -i 0.3 <ip>
```

`-c 4` four probes, `-i 0.3` 300 ms apart. Last line gives min/avg/max. 100%
loss on a public server usually means ICMP filtered, not host down; confirm
with the TCP connect test below.

### TCP port reachable

```sh
nc -z -v -G 5 <ip> <port>
```

`-z` no data, `-v` print result, `-G 5` connect timeout 5 s. Output
`succeeded!` or `Connection refused` / timeout. Goes through the tun like any
other traffic, so it tests the routed path, not raw internet.

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

`-s N` sets ICMP payload bytes. Wire size = N + 8 (ICMP) + 20 (IPv4).
Step sizes until loss or RTT jumps. Example from the OpenVPN case: 1350 passed
at 112 ms, 1400 lost half and took 641 ms, so the tunnel ceiling sat near
1378-1428 bytes.

### Confirm with HTTP

```sh
curl -o /dev/null -s -L -m 90 -w 'url=%{url_effective} connect=%{time_connect} ttfb=%{time_starttransfer} total=%{time_total} size=%{size_download} speed=%{speed_download} code=%{http_code}\n' http://<ip>/
```

Read: `connect` fast and `ttfb` reasonable but `total` hitting `-m` timeout
with small `size` means the first segments arrived and the rest never did.
Run once without `-L` to compare a tiny redirect body against the full page.

### Fix pattern (sing-box OpenVPN endpoint)

`mss_fix` clamps TCP MSS in both directions; `mtu` caps the tunnel interface.
Pick values under the probed ceiling: `"mss_fix": 1350`, `"mtu": 1380`.

### Worked case: OpenVPN client over shadowtls (2026-09-23)

Setup: `openvpn-client` endpoint, `network: tcp`, detoured through a
shadowsocks + shadowtls outbound (OpenVPN signature blocked locally, so the
extra TCP wrap is required). Web server on `192.168.10.1` behind the VPN.

Symptom: ping fine, `curl http://192.168.10.1/` (302, 270 bytes) done in
0.4 s, but `curl -L` to `/login` got 448 bytes then hung until the 90 s
timeout.

Why: endpoint `mtu` defaulted to 1500, so the tunnel's TCP stack advertised
MSS 1460. Segments near that size did not survive the nested path
(OpenVPN inside Shadowsocks inside TLS, plus the server-side LAN). Nothing on
the path sent ICMP "fragmentation needed" back through the userspace stack, so
TCP never shrank the segment size. Result: a classic PMTU blackhole where only
packets under the real ceiling arrive.

Proof: don't-fragment pings passed at 1350-byte payload (112 ms RTT) and half
failed at 1400 (641 ms). Ceiling between 1378 and 1428 bytes on the wire.

Change on the endpoint:

```json
"mss_fix": 1350,
"mtu": 1380
```

`mss_fix` rewrites the MSS option in SYN packets crossing the tunnel, both
directions, so the web server also sends segments the path can carry. `mtu`
backs that up for non-TCP traffic and for any flow that skips the clamp.

After: `curl -L` returned the full 3649-byte page in 2.9 s. Remaining time is
tunnel RTT (~112 ms) multiplied by the handshakes in a TCP-over-TCP path;
expected while the shadowtls wrap stays.

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
python3 -c "import json; json.load(open('<config>.json')); print('json ok')"
sing-box check -c <config>.json      # when the binary is on PATH
```

`sing-box check` catches unknown fields and bad option combinations that plain
JSON parsing cannot.
