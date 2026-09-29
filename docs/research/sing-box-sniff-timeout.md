# sing-box `sniff` timeout: does a 500ms-ping network break domain routing?

Research note, 2026-09-29. Checked against these pinned versions:

- **sing-box v1.14.0**, the version pinned in `tailscale-nodes/docker-compose.yaml` and used in `magicdns-headscale.md`, commit `0b899587`. Prefix: `https://github.com/SagerNet/sing-box/blob/v1.14.0/`
- **SagerNet/sing-tun v0.9.0-beta.4**, the version pinned in sing-box `go.mod:58`, commit `f4c1f3a`. Prefix: `https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/`
- **SagerNet/sing v0.9.0-beta.4**, pinned in sing-box `go.mod:48`, commit `3f8f790`. Prefix: `https://github.com/SagerNet/sing/blob/v0.9.0-beta.4/`
- **SagerNet/gvisor v0.0.0-20260727.0-sing-box-mod.1**, pinned in sing-tun `go.mod:11`. Prefix: `https://github.com/SagerNet/gvisor/blob/v0.0.0-20260727.0-sing-box-mod.1/`
- The sing-box docs at `docs/` in the same tag, rendered at https://sing-box.sagernet.org/.

Source links point at a tag plus a line anchor. Anything not read directly in source or official docs is marked **inferred** or **unverified**.

Scope: this note answers one question about `scaffolds/client/route.json` line 252, a bare `{"action": "sniff"}` with no `timeout`. It does not change any config.

## Questions

1. What does the sniff `timeout` measure? Is it the wait for the client's first payload on the local side, or does it include the remote round trip? For TCP, is the remote connection opened before sniffing?
2. What happens when the timeout expires? Does the connection fail, or does it continue without a sniffed domain? Is anything logged?
3. In this config, which rules miss if sniffing yields nothing, and can the domain still be known some other way (FakeIP, DNS reverse mapping, the inbound's own destination)?
4. When can the client's first payload arrive more than 300ms after the connection opens? Which protocols can sing-box sniff at all?
5. Should the timeout be raised, to what, and what does it cost?

## Short answer / recommendation

- **A 500ms WAN ping does not affect sniffing on this setup.** The timeout only covers the time between sing-box accepting the connection locally and the app sending its first bytes (TLS ClientHello, HTTP request, QUIC Initial). With the `tun` inbound on the gVisor stack, sing-box completes the TCP handshake with the app itself and dials the remote only *after* routing has finished. The remote server, and therefore the WAN latency, is not in the path while sing-box sniffs.
- **A timeout is not an error.** For TCP, the sniff error is stored on the connection metadata and rule matching simply continues. For UDP, a read timeout is explicitly treated as non-fatal. Nothing is logged at any level when sniffing fails; only a successful sniff produces a debug line.
- **What a failed sniff costs in this config:** the domain-based `rule_set` and `domain_suffix` rules after line 252 cannot match unless the domain is known another way. The connection then falls to `final: direct`. There is no FakeIP here. `dns.reverse_mapping: true` can still supply the domain, but only when the app resolved the name through sing-box.
- **When the 300ms budget can really run out:** server-first protocols that sing-box does not already skip (for example MySQL on 3306 or FTP on 21), where every new connection stalls for the full timeout before being routed; and the case where sing-box runs as a gateway for *other* devices over a slow Wi-Fi link, because the local TCP handshake then counts against the budget (inferred).
- **Recommendation: leave the default.** For a TUN on the same machine as the apps, as here, raising the timeout gains nothing and makes every server-first connection wait longer. Raise it (to about `1s`) only if sing-box is run as a gateway for devices on a high-latency LAN or Wi-Fi link.

---

## 1. What the timeout measures

### 1.1 Where the value comes from

- The docs say only: "Timeout for sniffing. `300ms` is used by default" ([`docs/configuration/route/rule_action.md:299-303`](https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/route/rule_action.md#L299-L303), rendered at [rule_action/#sniff](https://sing-box.sagernet.org/configuration/route/rule_action/#sniff)). They do not say what the clock starts on.
- The default is the constant `ReadPayloadTimeout = 300 * time.Millisecond` ([`constant/timeout.go:10`](https://github.com/SagerNet/sing-box/blob/v1.14.0/constant/timeout.go#L10)). The name already hints that it is a *read* timeout on the incoming side.

### 1.2 TCP: one deadline for reading the client's bytes

- The `sniff` rule action calls `actionSniff` from `matchRule` ([`route/route.go:660-670`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L660-L670)). For a stream it passes the **inbound** connection (`inputConn`) and `action.Timeout` to `sniff.PeekStream` ([`route/route.go:729-738`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L729-L738)).
- `PeekStream` replaces a zero timeout with `ReadPayloadTimeout`, computes **one absolute deadline** (`time.Now().Add(timeout)`), and then reads from the inbound connection in a loop until a sniffer succeeds, a sniffer fails with something other than "need more data", or a read fails ([`common/sniff/sniff.go:41-76`](https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/sniff.go#L41-L76)). The deadline is shared by every loop iteration, so a ClientHello split over several TCP segments must arrive in full within the same 300ms.
- So the timeout measures **how long sing-box waits for the local client to send enough bytes to identify the protocol and domain.** It is not a round trip to anywhere.

### 1.3 TCP: the remote is not dialed until routing is done

- In `routeConnection`, rule matching (including the sniff) runs first ([`route/route.go:108`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L108)). The outbound is picked from the matched rule, the sniffed bytes are pushed back in front of the connection with `bufio.NewCachedConn` ([`route/route.go:163-165`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L163-L165)), and only then is the connection handed to the outbound ([`route/route.go:172-177`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L172-L177)).
- The `ConnectionManager` is what dials the remote (`DialSerialNetwork` / `DialContext`, [`route/conn.go:95-105`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/conn.go#L95-L105)) and then reports handshake success back to the inbound ([`route/conn.go:122`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/conn.go#L122)). This happens after `matchRule` has returned.
- Nothing is sent to the remote server, and nothing is received from it, while sniffing. **WAN latency is not part of the 300ms.**

### 1.4 How the app gets to send its first bytes before the remote is dialed

An app will not send a ClientHello until its own TCP handshake is complete, so something local must complete it.

- **`tun` inbound, gVisor stack (this config, `inbounds.json`).** sing-tun's TCP forwarder wraps each incoming SYN in a `gLazyConn` and hands it to sing-box right away, without answering the SYN yet ([`stack_gvisor_tcp.go:77-96`](https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_tcp.go#L77-L96)). The first `Read` or `SetReadDeadline` on that conn calls `HandshakeContext`, which calls `request.CreateEndpoint` ([`stack_gvisor_lazy.go:31-71`](https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_lazy.go#L31-L71), [`:101-107`](https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_lazy.go#L101-L107), [`:133-139`](https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_lazy.go#L133-L139)). gVisor documents `CreateEndpoint` as "performing the 3-way handshake in the process" ([`pkg/tcpip/transport/tcp/forwarder.go:147-149`](https://github.com/SagerNet/gvisor/blob/v0.0.0-20260727.0-sing-box-mod.1/pkg/tcpip/transport/tcp/forwarder.go#L147-L149)). The SYN-ACK goes back to the app through the TUN device, and the app then sends its first payload.
- **A detail that matters for gateways.** `PeekStream` computes its deadline *before* calling `SetReadDeadline` ([`sniff.go:45-48`](https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/sniff.go#L45-L48)), and that call is what triggers the lazy handshake. The local SYN-ACK/ACK round trip therefore counts against the 300ms. On the same machine this is a trip through the kernel and takes well under a millisecond. It becomes significant only if the "app" is on another device (see §4.3).
- **`mixed` inbound (HTTP CONNECT).** sing writes `200 Connection established` to the client before routing ([`protocol/http/handshake.go:70-84`](https://github.com/SagerNet/sing/blob/v0.9.0-beta.4/protocol/http/handshake.go#L70-L84)), so the client sends its ClientHello right away.
- **`mixed` inbound (SOCKS5).** The SOCKS success reply is sent lazily on the first `Read` or `Write` ([`protocol/socks/lazy.go:71-79`](https://github.com/SagerNet/sing/blob/v0.9.0-beta.4/protocol/socks/lazy.go#L71-L79)), so, as with the TUN, the sniff's own read unblocks the client.

### 1.5 UDP

- For UDP, the TUN's pre-match step sniffs the **first packet it already holds**, with no waiting at all ([`route/route.go:337-381`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L337-L381)).
- In the full routing path, `actionSniff` first sniffs any packets already buffered. It reads further packets from the inbound only when a QUIC ClientHello is fragmented over several Initial packets (`ErrNeedMoreData`). Each such read uses a fresh deadline of `ReadPayloadTimeout`, or `action.Timeout` if set ([`route/route.go:779-850`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L779-L850), deadline at [`:810-815`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L810-L815)). These are packets from the local app, sent back to back. The remote is not involved.

## 2. What happens on timeout

- **TCP: the connection continues, unsniffed.** `actionSniff` stores the error in `metadata.SniffError` and returns no `fatalErr` for the stream branch ([`route/route.go:739-761`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L739-L761)). `matchRule` aborts only on `fatalErr` ([`route/route.go:667-670`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L667-L670)), so it goes on to the next rule with `metadata.Domain` and `metadata.Protocol` unset. Any bytes that did arrive are kept and replayed to the outbound (`sniffBuffer` is returned when not empty, [`route/route.go:757-761`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L757-L761)), so no data is lost.
- **UDP: also non-fatal.** A read error is fatal only when it is *not* a timeout: `if !E.IsTimeout(err) { fatalErr = err }` ([`route/route.go:827-832`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L827-L832)). On a timeout the loop jumps to `finally` and routing continues.
- **The only fatal UDP cases** are a read error that is not a timeout (above) and cancellation of the connection context, which closes the conn and returns `ctx.Err()` ([`route/route.go:820-825`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L820-L825)).
- **Logging.** Success is logged at debug level ("sniffed protocol: ..., domain: ...", [`route/route.go:748-755`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L748-L755)). A failed or timed-out sniff logs **nothing**. The only visible trace is which `match[N]` rule fires next in the debug log ([`route/route.go:600-605`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L600-L605)). To spot sniff misses, run with `log.level: debug` and look for connections to domain-routed sites that show no "sniffed protocol" line before their `match[...] => route(direct)`.
- **No retry.** Once a sniff with the same sniffer set has failed with anything other than "need more data", a later `sniff` action on the same connection is skipped ("packet sniff skipped due to previous error", [`route/route.go:712-714`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L712-L714)).

## 3. Consequences for this config

### 3.1 The rule flow (`scaffolds/client/route.json`)

| Line | Rule | Needs a domain? |
|---|---|---|
| 214-217 | `ip_cidr 100.64.0.0/10` → `ts-ep` | No |
| 218-221 | `port 53` → `hijack-dns` | No |
| 222-236 | TCP 5222/853, or listed IPs → reject (drop) | No |
| 237-240 | `rule_set mm-ip-rules` (GeoIP MM) → `direct` | No |
| 241-250 | `clash_mode Full` → `TCP` / `UDP` | No |
| **251-253** | **`sniff`** | — |
| 254-304 | TCP + (`rule_set` list or `domain_suffix gstatic.com`) + `clash_mode Partial` → `TCP` | **Yes** (geosite sets are domain lists) |
| 305-355 | same for UDP → `UDP` | **Yes** |
| 357 | `final: direct` | — |

- The sniff result only matters in **`Partial`** mode (the default, `experimental.json`). In `Full` mode everything has already been routed to the proxy by lines 241-250.
- The geosite rule sets match on the domain. `DomainItem.Match` uses `metadata.Domain` if it is set, and falls back to `metadata.Destination.Fqdn` ([`route/rule/rule_item_domain.go:61-72`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/rule/rule_item_domain.go#L61-L72)). With neither set, the rule cannot match, and the connection reaches `final: direct`. The practical failure is **"a site that should go through the proxy goes direct"**, not a broken connection. For sites that are blocked locally, that looks like a timeout or a reset from the direct path.
- `my-rules` is a custom rule set and may contain IP rules as well (not checked). IP entries match without a sniffed domain.

### 3.2 Other ways the domain can be known

`prepareMatchMetadata` runs before any rule ([`route/route.go:534-580`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L534-L580)) and can fill in the domain without sniffing:

- **FakeIP: not used.** The FakeIP branch runs only when a FakeIP DNS server exists and the destination is in its range ([`route/route.go:553-566`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L553-L566)). `scaffolds/client/dns.json` has no `fakeip` server.
- **DNS reverse mapping: enabled (`"reverse_mapping": true`).** If `metadata.Domain` is empty, the router looks the destination IP up in the reverse map ([`route/route.go:567-572`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L567-L572)). The map is filled from A/AAAA answers that pass through sing-box's DNS router, kept for the record's TTL, in an LRU of 1024 entries ([`dns/router.go:116-118`](https://github.com/SagerNet/sing-box/blob/v1.14.0/dns/router.go#L116-L118), [`:1109-1118`](https://github.com/SagerNet/sing-box/blob/v1.14.0/dns/router.go#L1109-L1118)). Because this runs before the sniff rule, a TLS connection whose sniff times out can still match `github` if the app looked up `github.com` through the TUN's hijacked port 53 (line 218-221).
- **Limits of reverse mapping.** The docs warn it "relies on the act of resolving domain names by an application before making a request" and "can be problematic in environments such as macOS, where DNS is proxied and cached by the system" ([`docs/configuration/dns/index.md:130-135`](https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/dns/index.md#L130-L135)). It also misses apps that use their own DoH. DoT on 853 is dropped by line 222-236, which pushes those apps back to plain DNS. That is a side effect of the rule, not something it states as its purpose (inferred).
- **`mixed` inbound: the domain is in the request.** An HTTP CONNECT or SOCKS5 request by name puts the name in `Destination.Fqdn`, which `DomainItem` falls back to. Sniffing is not needed for those connections.

## 4. When the first payload can be later than 300ms

### 4.1 What sing-box can sniff

The docs list: TCP `http` (Host), `tls` (SNI), `ssh` (client name), `rdp`, `bittorrent`, `dns`; UDP `quic` (SNI, client type), `stun`, `dtls`, `ntp`, `bittorrent`, `dns` ([`docs/configuration/route/sniff.md:12-25`](https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/route/sniff.md#L12-L25), rendered at [route/sniff](https://sing-box.sagernet.org/configuration/route/sniff/)). The default TCP set in code is TLS, HTTP, DNS, BitTorrent, SSH, RDP ([`route/route.go:716-728`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L716-L728)); the default UDP set is DNS, QUIC, STUN, uTP, UDP tracker, DTLS, NTP ([`route/route.go:32-40`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L32-L40)). **Only HTTP, TLS, and QUIC yield a domain.** Every one of these is a protocol in which the client speaks first.

### 4.2 Server-first protocols

- sing-box skips sniffing entirely, with no wait, on the SMTP (25, 465, 587), IMAP (143, 993), and POP3 (110, 995) ports ([`common/sniff/sniff.go:25-39`](https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/sniff.go#L25-L39), used at [`route/route.go:702-704`](https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go#L702-L704)).
- **SSH is not a problem.** RFC 4253 §4.2 has both sides send their identification string on connect, and sing-box's SSH sniffer reads the client's `SSH-2.0-` line ([`common/sniff/ssh.go:14-24`](https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/ssh.go#L14-L24)). OpenSSH clients send it at once, so SSH is sniffed quickly.
- **Other server-first protocols do stall.** For a protocol not on the skip list where the server speaks first, such as MySQL (3306), FTP control (21), or VNC (5900), the client sends nothing until it hears from the server. The server has not been dialed yet (§1.3), so the sniff always waits the **full timeout**, then routes unsniffed. Every new connection of that kind is delayed by exactly the timeout (inferred from §1.3 and §2; the protocol behaviour is general knowledge, not checked against each spec here). A larger timeout makes this delay larger.

### 4.3 Where the network *does* matter: sing-box as a gateway

- If sing-box runs on a router or another machine and routes traffic for other devices, the "local" TCP handshake from §1.4 happens over the LAN or Wi-Fi link. The deadline starts before the SYN-ACK is sent, so the budget has to cover one device-to-gateway round trip plus the arrival of the ClientHello. On a link with a 500ms round trip, a 300ms budget would run out and the domain would be missed (inferred from [`sniff.go:45-48`](https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/sniff.go#L45-L48) and [`stack_gvisor_lazy.go:133-139`](https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_lazy.go#L133-L139); not tested).
- This is not the setup in `scaffolds/client/`: its TUN (`inbounds.json`, `auto_route`, `strict_route`) runs on the same device as the apps.

### 4.4 Slow apps

- An app that opens a TCP connection and waits more than 300ms before writing (for example a connection pool that pre-opens sockets) is sniffed as nothing. With TLS and HTTP this is rare: clients write the ClientHello or request immediately after connect. No sing-box source or doc discusses this; it is inferred.

## 5. Recommendation

- **Keep the default for this client config.** High ping on the user's Wi-Fi or internet link does not reach the sniffer, because (a) the remote is dialed after sniffing and (b) the TUN handshake is local to the machine. A larger value brings no benefit and adds latency to every connection of a server-first protocol that is not on the skip list.
- **Raise it only for a gateway deployment.** If a profile is ever used on a machine that routes other devices' traffic over a slow link, set `"timeout": "1s"` on the sniff action. That covers a 500ms round trip plus the ClientHello with some margin. Going much higher only lengthens the stall for server-first protocols.
- **If server-first stalls ever matter,** put a rule for those ports *before* the sniff action (e.g. `{"port": [21, 3306, 5900], "outbound": "direct"}`), so they are routed without sniffing. This is a suggestion, not something the docs recommend.
- **To check whether sniffing is missing anything,** use debug logging as described in §2.

## Open questions / unknowns

- **Client sing-box version.** The user's macOS client runs a sing-box binary from `~/Downloads` whose version was not checked. This note reads v1.14.0. The `actionSniff`/`PeekStream` logic looks long-standing, but older versions were not compared.
- **gVisor handshake inside the deadline.** That the local SYN-ACK/ACK round trip counts against the budget follows from the order of calls in `PeekStream` and `gLazyConn`. It was not measured, and the effect on a gateway is not tested (§4.3).
- **`system` and `mixed` TUN stacks.** Only the `gvisor` stack used here was traced. The `system` stack terminates TCP in the host kernel, and was not checked.
- **`my-rules` contents.** Whether it contains IP rules (which match without a domain) was not checked.
- **Live test.** Not done. A quick one: run with `log.level: debug`, open a domain-routed site, and confirm a "sniffed protocol: tls, domain: ..." line. Then connect to a MySQL server and confirm a ~300ms gap between the connection line and `match[...]`.

## Sources

sing-box v1.14.0 (primary):
- `route/route.go` (`routeConnection`, `PreMatch`, `prepareMatchMetadata`, `matchRule`, `actionSniff`): https://github.com/SagerNet/sing-box/blob/v1.14.0/route/route.go
- `route/conn.go` (`ConnectionManager.NewConnection`, the remote dial): https://github.com/SagerNet/sing-box/blob/v1.14.0/route/conn.go
- `common/sniff/sniff.go` (`Skip`, `PeekStream`, `PeekPacket`): https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/sniff.go
- `common/sniff/ssh.go`: https://github.com/SagerNet/sing-box/blob/v1.14.0/common/sniff/ssh.go
- `constant/timeout.go`: https://github.com/SagerNet/sing-box/blob/v1.14.0/constant/timeout.go
- `route/rule/rule_item_domain.go`: https://github.com/SagerNet/sing-box/blob/v1.14.0/route/rule/rule_item_domain.go
- `dns/router.go` (reverse mapping): https://github.com/SagerNet/sing-box/blob/v1.14.0/dns/router.go
- Rule action `sniff` docs: https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/route/rule_action.md (rendered: https://sing-box.sagernet.org/configuration/route/rule_action/#sniff)
- Protocol sniff docs: https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/route/sniff.md (rendered: https://sing-box.sagernet.org/configuration/route/sniff/)
- DNS `reverse_mapping` docs: https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/dns/index.md (rendered: https://sing-box.sagernet.org/configuration/dns/#reverse_mapping)

SagerNet/sing-tun v0.9.0-beta.4 (primary):
- `stack_gvisor_tcp.go`: https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_tcp.go
- `stack_gvisor_lazy.go`: https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/stack_gvisor_lazy.go

SagerNet/sing v0.9.0-beta.4 (primary):
- `protocol/http/handshake.go`: https://github.com/SagerNet/sing/blob/v0.9.0-beta.4/protocol/http/handshake.go
- `protocol/socks/lazy.go`: https://github.com/SagerNet/sing/blob/v0.9.0-beta.4/protocol/socks/lazy.go

SagerNet/gvisor v0.0.0-20260727.0-sing-box-mod.1 (primary; fork of google/gvisor):
- `pkg/tcpip/transport/tcp/forwarder.go`: https://github.com/SagerNet/gvisor/blob/v0.0.0-20260727.0-sing-box-mod.1/pkg/tcpip/transport/tcp/forwarder.go

IETF:
- RFC 4253 §4.2, SSH protocol version exchange: https://www.rfc-editor.org/rfc/rfc4253#section-4.2

Repo files read: `scaffolds/client/{route,dns,inbounds,experimental,endpoints}.json`, `docs/research/magicdns-headscale.md` (for structure).
