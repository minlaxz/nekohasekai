# Network diagnostics: OpenVPN endpoint, MTU / MSS blackhole

Index: [network-diag.md](network-diag.md).

Symptom: small responses arrive, large ones stall. Tiny 302 redirect loads,
real page hangs until timeout. Ping works. That is a path MTU problem.

## Find the largest packet that passes without fragmentation

```sh
ping -c 4 <ip>                     # 56-byte payload (BSD default)
ping -D -s 1000 -c 4 <ip>          # 1000-byte payload, -D = don't fragment (BSD; Linux: -M do)
ping -D -s 1350 -c 4 <ip>
ping -D -s 1400 -c 4 <ip>
```

`-s N` sets ICMP payload bytes. IP packet size = N + 8 (ICMP) + 20 (IPv4).
Step sizes until loss or RTT jumps, then bisect between the last pass and the
first fail. A clean limit gives 100% loss above it. `ping: sendto: Message too
long` means a local interface MTU refused the packet before it left the host.
Example from the case below: 1350 passed at 112 ms, 1400 lost half and took
641 ms. Partial loss suggests the limit sits near 1400; probing 1370, 1380,
1390 would have narrowed it.

## Confirm with HTTP

```sh
curl -o /dev/null -s -L -m 90 -w 'url=%{url_effective} connect=%{time_connect} ttfb=%{time_starttransfer} total=%{time_total} size=%{size_download} speed=%{speed_download} code=%{http_code}\n' http://<ip>/
```

Read: `connect` fast and `ttfb` reasonable but `total` hitting `-m` timeout
with small `size` means the first segments arrived and the rest never did.
Run once without `-L` to compare a tiny redirect body against the full page.

## Fix pattern (sing-box OpenVPN endpoint)

`mss_fix` clamps TCP MSS in both directions; `mtu` caps the tunnel interface.
Pick `mtu` under the probed ceiling, then MSS = MTU - 40 (20 IPv4 + 20 TCP
header bytes). Example: `"mtu": 1380`, `"mss_fix": 1340`.

## Worked case: OpenVPN client over shadowtls (2026-09-23)

Setup: `openvpn-client` endpoint, `network: tcp`, detoured through a
shadowsocks + shadowtls outbound (OpenVPN signature blocked locally, so the
extra TCP wrap is required). Web server on `192.168.10.1` behind the VPN.

Symptom: ping fine, `curl http://192.168.10.1/` (302, 270 bytes) done in
0.4 s, but `curl -L` to `/login` got 448 bytes then hung until the 90 s
timeout.

Why: endpoint `mtu` defaulted to 1500, so the tunnel's TCP stack advertised
MSS 1460, and the web server sent segments up to 1500 bytes. The outer
transport is TCP, which splits any inner packet into its own stream, so the
host-to-server leg cannot drop packets for size. The limit is past the
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
