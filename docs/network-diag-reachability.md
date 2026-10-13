# Network diagnostics: reachability and latency

Index: [network-diag.md](network-diag.md).

## RTT to a host

```sh
ping -c 4 -i 0.3 <ip>
```

`-c 4` four probes, `-i 0.3` 300 ms apart. Last line gives min/avg/max. 100%
loss on a public server often means ICMP is filtered, not that the host is
down. Confirm with an HTTP request, not only with `nc`.

Under the sing-box tun, which path the ping takes depends on the route:

- ICMP routed to `direct` (no rule matches ICMP, so `route.final: direct`
  catches it): sing-box sends a real echo out the physical interface. The
  reply is honest, but it tests the direct path, not the proxy.
- ICMP routed to an outbound that cannot carry ICMP (Shadowsocks and most
  proxies) on the `gvisor` stack: gVisor answers the echo itself. Every IP
  "replies" [sing-tun `stack_gvisor_icmp.go:121-154`]. The `system` stack also
  fakes ping.

Control test: ping an address that never answers. A reply means it is faked.

```sh
ping -c 2 192.0.2.1    # TEST-NET-1, reserved, nothing should answer
```

Seen 2026-10-01 (sing-box 1.14.2, `gvisor`): 192.0.2.1 got 100% loss, 1.1.1.1
replied, so ping was real and went out direct. A cloud VPS got 100% loss:
its provider firewall blocks ICMP until a "Ping" rule is added.

## TCP port reachable

```sh
nc -z -v -G 5 <ip> <port>
```

`-z` no data, `-v` print result, `-G 5` connect timeout 5 s (BSD `nc`; GNU
uses `-w`). Output `succeeded!` or `Connection refused` / timeout.

Caveat under the sing-box tun: `succeeded!` does not prove the remote port.
The `system` / `mixed` stacks complete the handshake before any dial. The
`gvisor` stack waits for the outbound dial, but a proxy outbound (Shadowsocks
and most others) "succeeds" once the proxy server is up, not the target. See
"When does the app's `connect()` succeed?" in
[concepts/tun-inbound.md](concepts/tun-inbound.md). Proof of the
remote end needs data back: use `curl`, or read the sing-box log for the
outbound dial error. `Connection refused` or a timeout is still a real
failure.

Control test: probe a port that is surely closed. If it also says
`succeeded!`, the tun or the proxy answered, not the remote.

```sh
nc -z -v -G 5 <ip> 1
```

Seen 2026-10-01: port 1 on a cloud VPS reported `succeeded!`, and so did
443, which the provider firewall blocks. Stack was `gvisor`; the IP routed
to the `TCP` urltest (Shadowsocks), so the probe only proved the Shadowsocks
server was reachable. To test the real path, stop sing-box
or add `"route_exclude_address": ["<ip>/32"]` to the tun inbound, then repeat.
A firewall drop then shows as a timeout.

## UDP port reachable

`nc -u -G 5 ...` fails on BSD `nc` with `nc: TCP_CONNECTIONTIMEOUT: Invalid argument`:
`-G` is a TCP-only option. Drop it. A bare `nc -u -v <host> <port>` still
proves nothing: UDP has no handshake, so nc reports success without sending a
packet. A server that ignores junk (any QUIC server, e.g. `google.com:443`)
also stays silent, so silence is not a block either.

Proof needs a reply. Run a listener on your own VPS and send a line from the
client. Stop sing-box first, or the tun carries the UDP through the proxy.

```sh
# VPS (open the port in the cloud firewall first)
nc -u -l <port>
# client: type a line, press Enter; it must appear on the VPS
nc -u <vps-ip> <port>
```

Line appears: UDP to that port works. Nothing: UDP blocked on that port, or a
firewall in between. Try several ports (443, 8443, a high one). Blocking only
some ports suggests a per-port rule; Hysteria2 port hopping targets that.

QUIC to a real HTTP/3 site, if your curl was built with HTTP/3 (`curl -V`
lists `HTTP3`; the OS-bundled curl may not):

```sh
curl --http3-only -sI https://www.google.com -o /dev/null -w '%{http_version}\n'
```

`3` means QUIC passed. An error or timeout while the same URL over TCP works
means QUIC (UDP 443) is blocked or throttled.

## TCP works but an app says "connection refused"

`nc` does not prove the remote end (see above). An app can also fail where
`curl` works because of proxy env vars.

```sh
env | grep -i -E '^(http|https|all|no)_proxy='
curl -sv --noproxy '*' http://<ip>:<port>/ -o /dev/null 2>&1 | grep -E '^(< HTTP|\* Connected|curl:)'
NODE_USE_ENV_PROXY=1 node -e "fetch('http://<ip>:<port>/').then(r=>console.log(r.status)).catch(e=>console.error(e.cause||e))"
```

Line 1: any `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` makes an app that honors
them connect to the proxy instead of `<ip>`. A dead proxy gives
`ECONNREFUSED` on the proxy port, often reported as "firewall or proxy might
be blocking". Fix: `unset` them or add `<ip>` to `NO_PROXY`. Line 2:
`--noproxy '*'` bypasses env proxies. An `< HTTP` line proves the remote
answered on the routed path. Line 3: plain Node `fetch` ignores proxy env
vars; `NODE_USE_ENV_PROXY=1` (Node 22.21+ or 24+) makes it use them, as
Node-based CLI tools often do. The printed `cause` names the real address
and errno. Drop the variable to test the direct path.

## MTU of every utun

```sh
ifconfig | grep -A3 utun | grep -E 'utun|mtu|inet '
```

The sing-box tun is the one carrying the tun inbound address (here
`10.10.10.1`). Other utuns belong to Tailscale, VPN apps, iCloud Private Relay.
