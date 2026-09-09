# TUN inbound: how a packet gets from an app to the destination and back

Applies to: sing-box `inbounds[].type: "tun"`. Verified against sing-box v1.14.0
and sing-tun v0.9.0-beta.4. Source cites live in
[docs/research/sing-box-tun-inbound.md](../research/sing-box-tun-inbound.md).

Assumes you have read [inbound-tls](inbound-tls.md) (what an inbound is).

## One idea

A TUN is a **fake network card**. The kernel thinks it is a real NIC and sends
raw IP packets into it. On the other end of that "card" is not a cable but a
program: sing-box. It reads the packets, rebuilds the TCP/UDP conversation in
user space, decides where it should go, and opens a *real* connection out of
the *real* NIC on the app's behalf.

```
 app  ──▶  kernel  ──▶  tun0 (fake NIC)  ──▶  sing-box  ──▶  en0 (real NIC)  ──▶  world
                                                 │
                                          user-space TCP/IP
                                          + routing rules
```

Every other inbound (`mixed`, `socks`, `http`) needs the app to *opt in*
by pointing at a proxy address. TUN needs nothing from the app. That is the
whole reason it exists.

## Without TUN: the app must cooperate

```
 curl --proxy socks5://127.0.0.1:1080 https://example.com
          │
          ▼
   127.0.0.1:1080  ◀── mixed inbound ── sing-box ── en0 ──▶ example.com

 curl https://example.com          (no --proxy)
          │
          ▼
   kernel default route ──▶ en0 ──▶ example.com   (sing-box never sees it)
```

Consequences:

- Any app that ignores proxy settings (games, CLI tools, system services,
  DNS) goes straight out.
- DNS is almost always leaked, because the resolver is not the app.

## With TUN: the kernel is tricked into cooperating

```
 curl https://example.com          (no --proxy, knows nothing)
          │
          ▼
   kernel routing table:
     0.0.0.0/1     via tun0   ◀── installed by sing-box (auto_route)
     128.0.0.0/1   via tun0   ◀── installed by sing-box (auto_route)
     0.0.0.0/0     via en0    ◀── your real default route, still there
          │
          ▼  (two /1 routes are "more specific" than /0, so they win)
        tun0
          │
          ▼
      sing-box
```

Consequences:

- Every app, every protocol, no configuration on the app side.
- sing-box must now *avoid catching itself*: its own outgoing sockets would
  also match those routes. See "Loop avoidance" below.
- sing-box must now *speak TCP/IP itself*, because what arrives from `tun0`
  is a raw packet, not a socket. See "The user-space stack" below.

## Why two /1 routes instead of replacing the default route

Longest prefix wins. `0.0.0.0/1` and `128.0.0.0/1` together cover every
address, and both are longer than `/0`. So they win without deleting the real
default route. That surviving `/0` is how sing-box later finds the real NIC
to bind to. Deleting it would blind sing-box.

## Loop avoidance: how sing-box escapes its own trap

Common belief: "sing-box marks its packets with a firewall mark." Wrong for
the default setup. It is a **socket option**, set when sing-box creates each
outgoing socket:

```
 sing-box wants to connect to 1.2.3.4:443

   socket()
   setsockopt(bind to interface en0)   ◀── route.auto_detect_interface
   connect(1.2.3.4:443)
          │
          ▼
   kernel: "this socket is pinned to en0, skip the routing table"
          │
          ▼
        en0 ──▶ 1.2.3.4
```

| OS      | socket option                          |
|---------|----------------------------------------|
| Linux   | `SO_BINDTOIFINDEX` / `SO_BINDTODEVICE` |
| macOS   | `IP_BOUND_IF`                          |
| Windows | `IP_UNICAST_IF`                        |

Without it:

```
   sing-box connect(1.2.3.4:443)
          │
          ▼  routing table says tun0
        tun0
          │
          ▼
      sing-box  ──▶ connect(1.2.3.4:443) ──▶ tun0 ──▶ sing-box ──▶ ...
```

An infinite loop that eats CPU and connects to nothing. `direct` outbound
also refuses to dial into the TUN's own address range as a last-line guard.

Where the "real interface" comes from: sing-box watches the OS routing table
and picks whatever interface the surviving `0.0.0.0/0` points at. If Wi-Fi
drops and Ethernet takes over, the binding follows.

## The user-space stack: turning packets back into connections

An app calls `write()` on a socket. The kernel turns that into TCP segments
inside IP packets and pushes them into `tun0`. sing-box now holds bytes that
look like this:

```
 ┌──────────┬──────────┬──────────────┐
 │ IP header│TCP header│  payload     │
 │ src/dst  │ ports,   │ "GET / ..."  │
 │ addresses│ SYN/ACK  │              │
 └──────────┴──────────┴──────────────┘
```

sing-box's router does not want packets. It wants a `net.Conn` with a
source, a destination, and readable bytes. Something has to do the kernel's
job in reverse. That is the `stack` option.

### `stack: gvisor` — a full TCP/IP implementation in Go

```
 tun0 ──▶ gVisor netstack ──▶ TCP forwarder ──▶ net.Conn ──▶ router
             (parses IP,
              tracks seq/ack,
              retransmits, …)
```

Notable quirk: **lazy handshake**. When the app's SYN arrives, gVisor does
*not* reply SYN-ACK yet. It first hands the connection to the router, which
dials the outbound. Only when that dial succeeds does gVisor answer the app.

```
 app SYN ──▶ tun0 ──▶ gVisor ──▶ router ──▶ outbound dial ──▶ 1.2.3.4
                                                 │
                              success ◀──────────┘
                                 │
 app ◀── SYN-ACK ◀── tun0 ◀── gVisor

 (dial failed?)   app ◀── RST ◀── tun0 ◀── gVisor
```

Consequence: the app sees a *refused* connection, not "connected then hung
up". Closer to what a direct connection would do.

### `stack: system` — let the kernel do TCP, rewrite addresses

sing-box does not implement TCP here. Instead it opens one real listening
socket on the TUN address and **rewrites every packet** so the kernel thinks
the app is talking to that listener.

```
 app ──▶ [src=app:5000  dst=1.2.3.4:443] ──▶ tun0 ──▶ sing-box
                                                        │ rewrite + remember
                                                        │ "port 10001 = app:5000→1.2.3.4:443"
                                                        ▼
 kernel listener ◀── [src=10.10.10.1:10001  dst=10.10.10.0:tcpPort] ◀── tun0
        │
        ▼ accept()
      net.Conn  ──▶ lookup port 10001 ──▶ "ah, this is app:5000→1.2.3.4:443"
        │
        ▼
      router
```

Replies go through the same table backwards. The kernel does all the TCP
work. sing-box does address arithmetic.

Consequences:

- Handshake completes *immediately*, before the outbound dial. A failed dial
  shows up later as a reset on an already-open socket.
- UDP does not use the kernel here at all; it is handled in user space.
- Ping through a `system` stack is faked locally: sing-box just swaps
  addresses and echoes.

### `stack: mixed` — system for TCP, gVisor for UDP

Default in release builds. Takes the kernel's fast TCP and gVisor's better
UDP handling.

## The fast path: some packets never become connections

Before either stack sees a packet, a **flow dispatcher** looks at the first
packet of every new 5-tuple (a TCP SYN, or the first UDP datagram) and asks
the router: "based on IP and port alone, where would this go?"

```
 first packet ──▶ dispatcher ──▶ router.PreMatch (rules on IP-only metadata)
                                        │
             ┌──────────────────────────┼─────────────────────┐
             ▼                          ▼                     ▼
      outbound is a              outbound is a          rule says
      WireGuard/Tailscale        normal proxy           reject
      endpoint                        │                     │
             │                        ▼                     ▼
      NAT-rewrite and             "accept":            RST / ICMP
      forward raw packets         continue into        unreachable,
      at layer 3, no              the stack            no conn ever
      net.Conn ever made
```

Why it matters: a WireGuard peer already speaks IP. Rebuilding TCP in user
space only to re-encapsulate it as IP again is waste. The fast path skips
that. Also, a `reject` rule fires before any connection object is allocated.

## DNS: the special guest

Two things happen to DNS on a TUN, one automatic and one you configure.

### Automatic: the TUN's own resolver address

sing-box derives a DNS address from the TUN address: `address + 1`. For
`10.10.10.0/24` that is `10.10.10.1`. Anything sent there is answered by
sing-box's DNS module **before any route rule runs**.

```
 app ──▶ UDP to 10.10.10.1:53 ──▶ tun0 ──▶ dispatcher
                                              │ "that is my DNS address"
                                              ▼
                                       DNS module ──▶ upstream servers
                                              │
 app ◀── synthesised reply packet ◀── tun0 ◀──┘

 (no NAT entry, no net.Conn, no route rule, no stack)
```

Catch: this only helps if the OS actually *uses* `10.10.10.1` as its
resolver. Linux and Windows get it installed automatically. macOS command-line
sing-box does **not** set system DNS. If the Mac's resolver is the LAN router
(`192.168.1.1`), the directly-connected `/24` route to the LAN beats the `/1`
TUN routes, and DNS leaves through `en0` untouched.

```
 macOS, resolver = 192.168.1.1

   0.0.0.0/1       via tun0        (auto_route)
   192.168.1.0/24  via en0         (LAN, longer prefix, wins)
        │
        ▼
   DNS ──▶ en0 ──▶ 192.168.1.1     sing-box never sees it
```

### Configured: hijack any resolver

A rule like `{ "port": 53, "action": "hijack-dns" }` catches DNS to *any*
address that does reach the TUN and feeds it to the same DNS module. For UDP
this is also handled inline by the dispatcher, again with no connection made.

### Reverse mapping: how a domain rule can match an IP-only connection

A TUN connection carries only IPs. Yet you write rules like
`"domain_suffix": ".google.com"`. Two ways this works:

1. **Reverse mapping.** When the DNS module answers `google.com → 142.250.x.x`,
   it remembers that pair. A later connection to `142.250.x.x` gets
   `Domain = google.com` attached before the rules run.
2. **Sniffing.** A `sniff` action peeks at the first bytes (TLS SNI, HTTP
   Host, QUIC) and fills in the domain that way.

Both require the DNS answer or the first payload to have passed through
sing-box. If DNS leaked (see above), only sniffing is left.

### Fake-IP: the other design

Instead of returning the real IP, the DNS module returns a made-up address
from a private range (`198.18.0.0/15`) and remembers `fake → domain`. When
the app connects to the fake address, sing-box swaps it back to the domain
and lets the *outbound* resolve it, possibly on the far side of the proxy.

```
 app: "resolve google.com"  ──▶ sing-box DNS ──▶ 198.18.0.5  (fake)
 app: connect(198.18.0.5)   ──▶ tun0 ──▶ router: "198.18.0.5 = google.com"
                                              │
                                              ▼
                                        outbound connects to google.com
                                        (resolved wherever the outbound is)
```

Trade: domain rules always match, DNS answers never reveal the real server.
Cost: apps that cache the fake IP across a sing-box restart break unless the
mapping is persisted.

## Full hop list, TCP

```
 1. app connect(1.2.3.4:443)
 2. kernel: 1.2.3.4 matches 0.0.0.0/1 via tun0 ──▶ SYN written to tun0
 3. sing-tun reads packet from the tun fd
 4. dispatcher: first packet ──▶ router.PreMatch ──▶ "accept"
 5. stack (gVisor here) parses IP+TCP ──▶ net.Conn with Source/Destination
 6. router: DNS check ──▶ reverse-map / fake-ip ──▶ sniff ──▶ rules ──▶ outbound X
 7. X dials 1.2.3.4:443 on a socket bound to en0  (loop avoidance)
 8. dial succeeds ──▶ gVisor sends SYN-ACK ──▶ app's connect() returns
 9. app write() ──▶ tun0 ──▶ gVisor ──▶ copy loop ──▶ en0 ──▶ 1.2.3.4
10. 1.2.3.4 reply ──▶ en0 ──▶ copy loop ──▶ gVisor segments ──▶ tun0 ──▶ app read()
11. either side EOF ──▶ half-close the other; error ──▶ close both
```

## Full hop list, UDP

```
 1. app sendto(1.2.3.4:5000)
 2. kernel ──▶ tun0
 3. dispatcher: first datagram ──▶ router.PreMatch ──▶ "accept"
    (if dst is 10.10.10.1:53 ──▶ answered inline, stop here)
 4. stack: UDP NAT table, keyed by app's source addr:port ──▶ new "packet conn"
    first datagram queued in a 64-slot channel
 5. router: DNS check ──▶ sniff (reads queued packet) ──▶ rules ──▶ outbound X
 6. X opens a UDP socket bound to en0 ──▶ WriteTo(1.2.3.4:5000)
 7. reply ──▶ en0 ──▶ copy loop ──▶ stack builds IP+UDP header ──▶ tun0 ──▶ app
 8. no packets for udp_timeout (5 min) ──▶ NAT entry evicted ──▶ closed
```

Two UDP traps:

- The 64-slot channel **silently drops** packets when full. A burst before the
  outbound is ready loses data.
- Both stacks **drop IP fragments**. A datagram larger than the TUN MTU never
  arrives. Set MTU with that in mind, or keep the default large value.

## The knobs, and what each one moves

| key                      | what it changes                                                        |
|--------------------------|------------------------------------------------------------------------|
| `address`                | TUN's own address. `+1` becomes the auto DNS address.                  |
| `auto_route`             | install the `/1` routes (and per-OS policy rules).                     |
| `strict_route`           | Linux: stricter policy rules. Windows: firewall-block everything not via TUN, including all port 53. macOS: nothing. |
| `auto_redirect`          | Linux only: move routing to nftables with marks. Docs say "always recommended". |
| `stack`                  | `system` / `gvisor` / `mixed` as above.                                |
| `mtu`                    | max packet size; fragments are dropped, so this caps UDP.              |
| `udp_timeout`            | NAT lifetime. Also, surprisingly, the `system` stack's TCP NAT idle timeout. |
| `dns_address` (1.14)     | set explicit resolver; turns *off* the auto `+1` hijack.               |
| `route.auto_detect_interface` | the socket binding that prevents loops. Required.                 |
| `dns.reverse_mapping`    | IP→domain memory so domain rules match on TUN.                         |

## Mental model to keep

```
 kernel's job              sing-box's job                    kernel's job again
 ──────────────            ───────────────────────────       ──────────────────
 app socket ──▶ packets ──▶ packets ──▶ conn ──▶ decide ──▶ new socket ──▶ en0
                 (tun0)      (stack)   (router)  (outbound)  (bound to en0)
```

The TUN turns a socket into packets. The stack turns packets back into a
socket. The router decides. A second, interface-pinned socket carries it out.
Everything else is detail about which of those four steps a knob touches.
