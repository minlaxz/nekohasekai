# sing-box TUN inbound: the packet path from app to destination and back

Research note, 2026-09-09. Verified against sing-box **v1.14.0** source (tag `v1.14.0`) and the docs bundled in that tag, plus the libraries it pins in `go.mod`: **sing-tun v0.9.0-beta.4** (commit `f4c1f3ae`, 2026-08-10) and **sing v0.9.0-beta.4**. Citations are `path:line` at those revisions. Prefixes: `https://github.com/SagerNet/sing-box/blob/v1.14.0/`, `https://github.com/SagerNet/sing-tun/blob/v0.9.0-beta.4/`, `https://github.com/SagerNet/sing/blob/v0.9.0-beta.4/`. Files without a prefix are sing-box; files marked `tun:` are sing-tun; `sing:` is the sing library. Companion note: [sing-box-route-matching.md](./sing-box-route-matching.md) covers the rule loop; this note stops at the router entry point and picks up again at the outbound dial.

## TL;DR

- **The TUN is a Layer-3 pipe; sing-tun turns raw IP packets into Go `net.Conn`s before sing-box ever sees them.** The kernel routes app packets to the virtual device (auto_route); sing-tun reads them from the fd, runs a user-space TCP/IP stack (`system`, `gvisor`, or `mixed`), and hands sing-box a TCP conn or a UDP "packet conn" with only `Source`/`Destination` IP:port metadata. [`tun:stack.go:37-65`, `tun:tun.go:22-27`, `protocol/tun/inbound.go:546-584`]
- **Loop avoidance is a socket option on sing-box's own outbound sockets, not a firewall rule.** `route.auto_detect_interface` binds every outbound socket to the real default NIC (`SO_BINDTOIFINDEX`/`SO_BINDTODEVICE` on Linux, `IP_BOUND_IF` on macOS, `IP_UNICAST_IF` on Windows). On macOS the trick works because auto_route installs two `/1` routes (and finer sub-ranges) instead of replacing `0.0.0.0/0`, so the kernel's true default route survives and the interface monitor can still find it. [`common/dialer/default.go:105-130`, `route/network.go:379-392`, `sing:common/control/bind_darwin.go:22-27`, `tun:tun_rules.go:107,123-133`, `tun:monitor_darwin.go:128-163`]
- **The `system` stack is a NAT trick, not a TCP implementation.** It listens on a real kernel TCP socket bound to the TUN address, rewrites every inbound SYN so the kernel connects to that listener, records the original 4-tuple in a port table, and reverses the rewrite on the way back. The kernel does TCP; sing-tun does address rewriting. UDP and ICMP are handled in user space. [`tun:stack_system.go:164-178,478-516`, `tun:stack_system_nat.go:125-154`]
- **gVisor stack is lazy on TCP: the app's SYN is not answered until the outbound connect succeeds.** `gLazyConn` defers `CreateEndpoint` to the first write or explicit handshake-success signal, so a failed proxy dial surfaces to the app as a RST, not as a connected-then-closed socket. [`tun:stack_gvisor_lazy.go:31-83`, `tun:stack_gvisor_tcp.go:77-96`]
- **There is a pre-match "flow" fast path in front of both stacks (new in 1.13/1.14).** Every first packet (TCP SYN, first UDP datagram) goes through `JudgeFlow` → `Router.PreMatch`, which walks `route.rules` on IP-only metadata. If the selected outbound is a `FlowOutbound` (Tailscale/WireGuard endpoint, `direct` for ICMP), packets are NAT-rewritten and forwarded at Layer 3, bypassing the user-space stack entirely. For everything else the verdict is "accept" and the normal path continues. [`tun:flow_dispatch.go:195-332`, `adapter/router.go:52-102`, `route/route.go:316-418,440-532`, `protocol/direct/outbound.go:177-182`]
- **DNS to the TUN's own derived address (`address[0] + 1`) is hijacked before any rule runs, and for UDP it never becomes a connection at all.** The dispatcher answers it as a synthesized packet through `Router.HijackDNSPacket`. TCP to that address is marked `Protocol=dns` and short-circuited at the top of `routeConnection`. `dns_mode`/`dns_address` (1.14) make this explicit and, when `dns_address` is set, turn the auto-hijack off. [`protocol/tun/inbound.go:334-338,523-544,553-555`, `tun:flow_dispatch.go:321-327`, `tun:flow_dns.go:14-89`, `route/route.go:101-104,240-242`, `docs/configuration/inbound/tun.md:278-292`]
- **Applied to this repo** (`scaffolds/client`): `stack: gvisor`, `auto_route` + `strict_route`, no fake-ip, `reverse_mapping: true`, `auto_detect_interface: true`, no `routing_mark`, default DNS hijack of `10.10.10.1`, plus an explicit `port: 53 → hijack-dns` rule. Loop avoidance is correct. Footguns: the TUN address is a `/24` network address (`10.10.10.0`), MTU 1420 is far below the 65535/4064 defaults, macOS CLI never installs `10.10.10.1` as system DNS so the port-53 rule and hijack only fire inside the graphical client or when an app talks to a non-LAN resolver, and `strict_route` on Windows also blocks all port-53 traffic that is not through the TUN. See §9.

---

## 1. Device creation and routes

### 1.1 Common option handling

`NewInbound` splits `address`/`route_address`/`route_exclude_address` into v4/v6 lists [`protocol/tun/inbound.go:80-102`], rejects the removed `inet4_*` legacy fields and `gso` [`:66-74`], and sets defaults:

| option | default | source |
|---|---|---|
| `mtu` | 65535; 9000 on Android; 4064 under Apple NetworkExtension | `protocol/tun/inbound.go:108-119` |
| `udp_timeout` | `C.UDPTimeout` = 5m | `:124-129`, `constant/timeout.go:12` |
| `iproute2_table_index` / `iproute2_rule_index` / fallback rule | 2022 / 9000 / 32768 | `:146-157`, `tun:tun.go:57-61` |
| `auto_redirect_{input,output,reset}_mark`, `auto_redirect_nfqueue` | 0x2023 / 0x2024 / 0x2025 / 100 | `:158-173`, `docs/configuration/inbound/tun.md:366-396` |
| `dns_mode` | `hijack` | `tun:tun.go:127-132` |
| `dns_address` | `address[0].Addr().Next()` per family | `tun:tun.go:146-176` |
| `stack` | `mixed` if built with gVisor and GSO off, else `system`; `gvisor` forced when `includeAllNetworks` | `tun:stack.go:41-49` |
| `interface_name` | `utunN` on Apple, `tunN` elsewhere (first free index) | `tun:tun.go:230-253`, `protocol/tun/inbound.go:368-370` |

Everything is copied into a `tun.Options` [`protocol/tun/inbound.go:198-235`]. `route_address_set` / `route_exclude_address_set` are resolved to rule-sets at construction [`:244-257`] and their IP CIDRs are appended to the route lists at start when `auto_redirect` is off [`:407-426`]. Note `ForwarderBindInterface: C.IsDarwin` [`:463`], which matters for the system stack on macOS (§3.1).

Start is three-staged [`:331-498`]: `Initialize` derives the DNS hijack addresses [`:334-338`]; `Start` opens the device (`platformInterface.OpenInterface` for graphical clients, otherwise `tun.New`) [`:427-432`] and builds the stack [`:452-466`]; `PostStart` starts the stack, then the interface (which installs routes/rules), then `auto_redirect` [`:475-493`].

### 1.2 Route ranges (all platforms)

`BuildAutoRouteRanges` [`tun:tun_rules.go:109-212`] decides what gets routed to the TUN:

- `route_address` set → those prefixes (on macOS the TUN subnet itself is appended so the interface is reachable) [`:113-121`].
- otherwise `auto_route: true` → on **macOS outside NetworkExtension**, eight sub-ranges `1/8, 2/7, 4/6, 8/5, 16/4, 32/3, 64/2, 128/1` (and the v6 equivalents); on every other platform a single `0.0.0.0/0` / `::/0` [`:107,122-136,172-186`].
- `route_exclude_address` is subtracted with an `IPSetBuilder`, so exclusions become "holes" expressed as more-specific prefixes rather than separate exclusion routes [`:144-159`].

The macOS sub-range choice is deliberate: `0.0.0.0/0` already exists (the real default route) and the sub-ranges are more specific, so they win without deleting it. §2 explains why that is the loop-avoidance mechanism.

### 1.3 Linux: netlink + policy routing

`tun.New` opens `/dev/net/tun`, then `configure` sets MTU and adds the addresses with netlink [`tun:tun_linux.go:53-75,132-158`]. `Start` brings the link up, writes `rp_filter=2`, and calls `setRoute` and `setRules` [`:317-358`]. Routes are written into a **dedicated table** (`iproute2_table_index`, default 2022), one per range, with the TUN as link and `address[0]+1` as gateway [`:647-668`, gateway from `tun:tun.go:185-188`]. Routing into that table is controlled by **policy rules** starting at priority `iproute2_rule_index` (9000), built in `rules()` [`:686-1090`]. Without `auto_redirect`, the sequence for IPv4 is (priorities increase in this order):

| rule | effect | source |
|---|---|---|
| `uidrange X-Y goto nop` (per exclude range, incl. `include_uid` inversion) | excluded users bypass | `:790-808` |
| `iif <include_if> goto match` … `goto nop`; or `iif <exclude_if> goto nop` | `include_interface` / `exclude_interface` | `:817-897` |
| Android only: `fwmark 0x20000/0x20000 goto nop` | VpnService-protected sockets bypass (`override_android_vpn` flips it) | `:899-927` |
| `strict_route`: `unreachable` for the family that has no TUN address | "let unsupported network unreachable" | `:929-946` |
| `to <tun subnet> lookup 2022` | reach the TUN's own subnet | `:950-957` |
| `lookup 2022 suppress_prefixlength 0` | consult the sing-box table but ignore its default route | `:960-966` |
| `not dport 53 lookup main suppress_prefixlength 0` | non-DNS traffic keeps main-table specific routes (LAN); DNS to a directly attached subnet is forced through the TUN | `:977-996`, doc `docs/configuration/inbound/tun.md:268-271` |
| `iif tunN goto nop` | packets arriving from the TUN never re-enter | `:998-1005` |
| `not iif lo lookup 2022` ; `iif lo from 0.0.0.0/32 lookup 2022` ; `iif lo from <tun subnet> lookup 2022` | locally generated traffic (and forwarded traffic) falls to the TUN default route | `:1007-1031` |
| `nop` (empty rule at `ruleStart+10`) | goto target | `:1077-1088` |

Key consequence: there is **no fwmark rule in this path**. Sing-box's own sockets escape by interface binding (§2), not by `SO_MARK`. `default_mark`/`routing_mark` are optional extras the user must pair with their own `ip rule` and are refused when `auto_redirect` is on [`common/dialer/default.go:251-265`].

With `auto_redirect` the rule set collapses to a mark-based one: `fwmark 0x2024 goto +2` (sing-box's output mark, skip), `fwmark 0x2023 lookup 2022` (packets the nftables chain marked as input), an empty rule, and a fallback `lookup 2022` at priority 32768 that only fires if main/default have no route [`:722-788`, doc `:398-407`]. The marks are applied by nftables rules from `redirect_nftables_rules.go`; `NewAutoRedirect` is created at `protocol/tun/inbound.go:263-274` and registers the output mark with the network manager so every dialer sets it [`:278-286`, `route/network.go:411-430`, `common/dialer/default.go:137-141`]. `autoRedirect.Start` picks nftables unless `DISABLE_NFTABLES`, starts a local redirect TCP server, optionally an nfqueue pre-match handler, then installs the tables and (mark mode) redirect routes [`tun:redirect_linux.go:97-222`]. With `dns_mode: hijack` it also adds a DNAT of `dport 53` to the derived DNS address [`tun:redirect_nftables_rules.go:678-692,1040-1160`]. Details of the nft chains are out of scope here.

`dns_mode != disabled` also registers the TUN with systemd-resolved via `resolvectl domain ~. / default-route true / dns <derived>` when `resolvectl` exists [`tun:tun_linux.go:360-365,1209-1224`].

### 1.4 macOS / Darwin: utun control socket + route socket

`tun.New` requires the name to be `utun%d`, opens an `AF_SYSTEM` datagram socket, and `create` connects it to the `com.apple.net.utun_control` kernel control with `Unit = index+1` [`tun:tun_darwin.go:94-118,234-248`]. MTU via `SIOCSIFMTU` [`:250-258`], addresses via `SIOCAIFADDR` / `SIOCAIFADDR_IN6` with dst = own address (point-to-point) [`:262-340`]. `Start` registers the interface with the monitor (so the monitor ignores it) and calls `setRoutes` [`:152-158`]. `setRoutes` iterates `BuildAutoRouteRanges` and writes each as an `RTM_ADD` message on an `AF_ROUTE` socket with flags `RTF_STATIC|RTF_GATEWAY|RTF_UP`, gateway = the TUN's **own** address [`:457-501,536-570`, gateway from `tun:tun.go:189-190`]. An `EEXIST` route is deleted and re-added [`:482-490`]. It then runs `dscacheutil -flushcache` [`:496,572-574`].

Nothing here touches system DNS settings. The only DNS-related act on macOS CLI is the cache flush. The graphical client gets the derived addresses via libbox `GetDNSServerAddress` and applies them through NetworkExtension [`experimental/libbox/tun.go:22,102-107`].

### 1.5 Windows: wintun + metric-0 routes + WFP

`tun.New` creates (or opens) a wintun adapter and starts a ring session [`tun:tun_windows.go:39-70`]. `configure` sets addresses, sets **per-interface DNS** to the derived servers when `auto_route` and `dns_mode != disabled`, disables DNS registration, enables forwarding, sets NL MTU, and with `auto_route` forces the interface metric to 0 [`:73-163`]. `Start` adds the auto-route prefixes with route metric 0 and flushes the resolver cache [`:169-187,600-629`]. With `strict_route` it opens a dynamic WFP session and adds, in a max-weight sublayer: permit for sing-box's own process App ID (weight 13), block IPv6 if the TUN has no v6 address (12), permit on the TUN interface index (11), and with `dns_mode: hijack` **block remote port 53 everywhere else** (10) [`:188-364`, doc `:275-276,445-451`].

### 1.6 Android / iOS (graphical clients)

When a `PlatformInterface` is present, `OpenInterface` asks the app for the fd (`VpnService`/`NEPacketTunnelProvider`), passing the computed route ranges and options; sing-tun then wraps the fd (`FileDescriptor != 0`) and installs nothing itself [`experimental/libbox/service.go:59-84`, `tun:tun_linux.go:76-89`, `tun:tun_darwin.go:119-125`]. On Android CLI (root) the normal netlink path runs and `include_package`/`exclude_package` are translated to UID ranges (`uid = appId + user*100000`) before the rules are built [`protocol/tun/inbound.go:365-367`, `tun:tun_rules.go:22-90`].

## 2. Loop avoidance: how sing-box's own sockets escape the TUN

The TUN default route would swallow sing-box's outbound sockets too. The escape hatch is applied at socket creation via `dialer.Control`/`listener.Control` in `NewDefault` [`common/dialer/default.go:56-249`], in this order:

1. `bind_interface` on the outbound → `control.BindToInterface` [`:77-84`].
2. `routing_mark` → `SO_MARK` (Linux only), refused together with `auto_redirect` [`:85-91,251-265`].
3. `route.default_interface` → same bind, unless the outbound already binds [`:100-104`].
4. `route.auto_detect_interface` → `networkManager.AutoDetectInterfaceFunc()` (CLI) or the platform `protect()` control (graphical clients) [`:105-130`].
5. `route.default_mark` → `SO_MARK` [`:132-135`].
6. `auto_redirect` output mark, always appended when registered [`:137-141`].

`AutoDetectInterfaceFunc` resolves per connection: if the destination is an address owned by a local interface, bind to that; otherwise bind to `interfaceMonitor.DefaultInterface()` [`route/network.go:379-392`]. Virtual destinations are skipped [`sing:common/control/bind.go:37-39`]. The actual syscalls:

| OS | mechanism | source |
|---|---|---|
| Linux | `SO_BINDTOIFINDEX`, falling back to `SO_BINDTODEVICE` | `sing:common/control/bind_linux.go:15-42` |
| macOS | `IP_BOUND_IF` / `IPV6_BOUND_IF` | `sing:common/control/bind_darwin.go:10-29` |
| Windows | `IP_UNICAST_IF` / `IPV6_UNICAST_IF` | `sing:common/control/bind_windows.go:12-61` |
| Linux mark | `SO_MARK` | `sing:common/control/mark_linux.go:7-13` |

How the monitor finds the "default" interface after auto_route: on macOS it walks the routing table for an IPv4 `0.0.0.0/0` entry with `RTF_UP|RTF_GATEWAY` and takes its interface [`tun:monitor_darwin.go:120-163`]. Because auto_route installs `/1` sub-ranges and never a `/0`, the real default route still exists and still points at `en0`. Under NetworkExtension the `/0` is gone (the app installs it), so the monitor instead does a UDP-connect trick to `10.255.255.255:80` and reads the chosen source address [`:114-118,180-224`]. The docs state the requirement plainly: "To avoid traffic loopback, set `route.auto_detect_interface` or `route.default_interface` or `outbound.bind_interface`" [`docs/configuration/inbound/tun.md:312-314`; `docs/configuration/route/index.md:82-108`].

Inbound side, Linux only: the rule `iif tunN goto nop` [`tun:tun_linux.go:998-1005`] stops packets that arrived from the TUN from being routed back into it, and `rp_filter=2` [`:332`] keeps reverse-path filtering from dropping them.

## 3. Packet → connection: the user-space stack

The `Handler` interface every stack drives is `JudgeFlow`, `NewDNSPacket`, `NewConnectionEx` (TCP), `NewPacketConnectionEx` (UDP) [`tun:tun.go:22-27`]; the TUN inbound implements all four [`protocol/tun/inbound.go:523-584`].

### 3.0 Pre-match flow dispatcher (in front of every stack)

Both stacks put a `ForwardDispatcher` between the fd and the transport parser (`system`: `dispatchIPv4` [`tun:stack_system.go:391-409,435`]; `gvisor`: `LinkEndpointFilter.DeliverNetworkPacket` [`tun:stack_gvisor_filter.go:52-82`]). `Dispatch` parses the packet, drops fragments and flow-less packets, looks the 5-tuple up in a 16384-entry flow table, and for a *new* TCP SYN or first UDP datagram calls `handler.JudgeFlow` with the UDP payload as `firstPacket` [`tun:flow_dispatch.go:195-226,279-284`]. The verdict installs one of: `ActionFlow` (packets rewritten and forwarded to a `tun.Port`, i.e. a `FlowOutbound`), `Accept` (fall through to the stack), `Reject` (RST/ICMP unreachable), `Drop`, `HijackDNS` (UDP: answered inline; TCP: accept) [`:291-331`, `tun:flow.go:8-25`].

On the sing-box side `adapter.JudgeFlow` builds a minimal `InboundContext` and calls `Router.PreMatch` [`adapter/router.go:52-102`], which runs `prepareMatchMetadata` and walks `route.rules` with `PreMatch=true`: `sniff` may run *packet* sniffers on the first UDP datagram, `route`/`bypass` resolve the outbound (following selector/urltest groups up to 8 deep), `reject`/`hijack-dns` map directly, and anything else returns "continue" [`route/route.go:316-418`]. `preMatchFlow` only returns `PreMatchFlow` if the chosen outbound is a `FlowOutbound` [`:466-473`]: Tailscale and WireGuard endpoints always are [`protocol/tailscale/port.go:21-23`, `protocol/wireguard/endpoint.go:177-179`]; `direct` only for ICMP [`protocol/direct/outbound.go:177-182`]. A fake-ip destination requires a prior `resolve` action or the flow is rejected [`route/route.go:488-506`]. Flow forwarding does its own NAT (port selector per `Port` address), MSS clamping on SYN, TCP re-segmentation / IPv4 fragmentation / ICMP "too big" against the port's MTU [`tun:flow_dispatch.go:375-459,495-547`, `tun:flow_mtu.go:14,77,109,138`].

For a plain proxy outbound the verdict is `Accept`, and the packet continues into the stack below. The same `JudgeFlow` is called a second time by the stack's TCP/UDP forwarder [`tun:stack_gvisor_tcp.go:80`, `tun:stack_gvisor_udp.go:80`], so a `reject` rule matched on IP metadata takes effect before a connection object exists.

### 3.1 `system` stack: kernel TCP + address rewriting

`NewSystem` requires `address[0]` to have a next address (`10.10.10.0/24` → `10.10.10.1`) [`tun:stack_system.go:97-113`]. `start`:

- listens a **real kernel TCP socket** on `<tunAddr>:0` (random port `tcpPort`) per family, bound to the TUN interface on macOS (`ForwarderBindInterface`) [`:150-195`];
- creates a `TCPNat` (port table starting at 10000) and a `UDPNat` [`:177,196-203`, `tun:stack_system_nat.go:31-40`];
- creates the dispatcher with a writeback that batch-writes to the fd [`:209,897-958`].

`tunLoop` reads packets (batched on Linux/Darwin), calls `processPacket`, and if it returns true **writes the same, rewritten buffer straight back to the TUN** [`:214-252`]. For an outbound TCP packet from the app (`src=app:port → dst=1.2.3.4:443`), `processIPv4TCP` allocates a NAT port `p` for the 4-tuple and rewrites it to `src=<tunAddr+1>:p → dst=<tunAddr>:tcpPort` [`:505-513`, `tun:stack_system_nat.go:125-154`]. The kernel now sees a packet addressed to its own listener and completes the handshake in-kernel; `acceptLoop` accepts it, looks the remote port `p` up in the NAT table to recover the original source/destination, and calls `handler.NewConnectionEx(conn, source, destination)` [`:375-389`]. Packets flowing the other way (`src=<tunAddr>:tcpPort → dst=<tunAddr+1>:p`) are rewritten back to `src=1.2.3.4:443 → dst=app:port` [`:486-493`]; checksums are updated incrementally or offloaded [`:558-594`]. Reply packets from the listener are exempted from the dispatcher [`:397-401`]. The TCP NAT idle timeout is, surprisingly, the **UDP** timeout (`NewNat(ctx, s.udpTimeout)`) [`:177`].

UDP never touches the kernel: `processIPv4UDP` drops fragments and feeds the payload into `UDPNat.NewPacket` with the IP header as user data [`:634-648`]; `preparePacketConnection` builds a writer that keeps a copy of the IP+UDP header and synthesises replies [`:660-688`]. ICMP echo to anything is answered locally by swapping addresses (the system stack fakes ping) [`:690-717`].

### 3.2 `gvisor` stack: full netstack in user space

`NewGVisor` needs a `GVisorTun` (Linux, Darwin, Windows all implement it) [`tun:stack_gvisor.go:56-96`]. `Start` creates an fd-based link endpoint reading the TUN fd directly (`fdbased.New` with `RecvMMsg` on Darwin) [`:99`, `tun:tun_darwin_gvisor.go:44-60`], wraps it in the pre-match filter [`:106-115`], and registers three transport handlers [`:120-131`]:

- **TCP**: `tcp.NewForwarder(stack, 0, 1024, Forward)` [`tun:stack_gvisor_tcp.go:41`]. `Forward` runs on each SYN, calls `JudgeFlow`, then wraps the pending request in a `gLazyConn` and calls `NewConnectionEx` **without completing the handshake** [`:77-96`]. `CreateEndpoint` (which sends the SYN-ACK) happens in `HandshakeContext`, triggered by the first `Write` or by `HandshakeSuccess` after the outbound dial; `HandshakeFailure` completes the request with a RST [`tun:stack_gvisor_lazy.go:31-83,109-115`]. sing-box calls `ReportConnHandshakeSuccess` right after the outbound dial succeeds [`route/conn.go:122`].
- **UDP**: `HandlePacket` extracts the payload and calls `UDPNat.NewPacket` [`tun:stack_gvisor_udp.go:52-59`]; `PreparePacketConnection` runs `JudgeFlow` on the first payload, handles `HijackDNS` inline, and otherwise returns a `UDPBackWriter` that builds replies with `stack.FindRoute` + `route.WritePacket` [`:64-103,136-197`].
- **ICMP**: a forwarder that hands echo requests to the handler (ping through the proxy), not covered further here [`tun:stack_gvisor.go:128-131`].

Replies leave gVisor through the link endpoint's `WritePacket`, which `writev`s onto the TUN fd with the 4-byte AF header prepended on Darwin [`tun:tun_darwin_gvisor.go:17-42`] or a virtio header on Linux GSO [`tun:tun_linux_gvisor.go:21-53`].

### 3.3 `mixed` stack

`Mixed` embeds `System` [`tun:stack_mixed.go:20-39`]. TCP takes the system NAT path; UDP is injected into a gVisor `channel` endpoint whose only transport handler is the UDP forwarder, and a `packetLoop` copies gVisor's output back to the TUN [`:41-63,248-273,301-310`]. It is the default when gVisor is compiled in (release builds are: `with_gvisor` is in `release/DEFAULT_BUILD_TAGS_OTHERS`) [`tun:stack.go:42-49`, `docs/configuration/inbound/tun.md:575`].

### 3.4 What sing-box receives

`Inbound.NewConnectionEx` / `NewPacketConnectionEx` fill `metadata.Inbound`, `InboundType = tun`, `Source`, `Destination` (always IP:port here) and set `Protocol = dns` if the destination IP is a derived DNS address; `Network` is set later by the router (`tcp` at `route/route.go:90`, `udp` at `:234`) [`protocol/tun/inbound.go:546-584`]. `udp_timeout` is not in metadata; it is the NAT table lifetime (§6). Then `router.RouteConnectionEx` / `RoutePacketConnectionEx` [`:562,:583`].

## 4. DNS on TUN

### 4.1 The derived address and the pre-rule hijack

At `Initialize`, if `dns_mode != disabled` and `dns_address` is unset, `dnsHijackAddress = [address[0]+1, address6[0]+1]` [`protocol/tun/inbound.go:334-338`, `tun:tun.go:146-176`]. Three hooks use it:

1. `JudgeFlow`: UDP to that address → `ActionHijackDNS`; TCP → `Accept` [`protocol/tun/inbound.go:523-531`]. The dispatcher then calls `hijackDNSPacket`, which hands the UDP payload to `NewDNSPacket` with a `dnsResponseWriter` [`tun:flow_dispatch.go:321-327`, `tun:flow_dns.go:14-20`]. `NewDNSPacket` builds metadata with `Protocol=dns` and calls `Router.HijackDNSPacket`, which unpacks the message, clears `Destination`, runs `dns.ExchangeAsync`, and writes the (possibly truncated) answer back [`protocol/tun/inbound.go:533-544`, `route/dns.go:46-72`]. The writer synthesises a complete IP+UDP reply with swapped addresses and writes it to the TUN [`tun:flow_dns.go:29-89`]. **No UDP NAT entry, no packet connection, no route rule runs.**
2. `NewConnectionEx` (TCP) and `NewPacketConnectionEx` set `Protocol = dns` [`protocol/tun/inbound.go:553-555,572-576`].
3. `routeConnection` / `routePacketConnection` short-circuit `InboundType == tun && Protocol == dns` to `hijackDNSStream` / `hijackDNSPacket` *before* `matchRule` [`route/route.go:101-104,240-242`, `route/dns.go:20-44`]. The stream handler loops `HandleStreamDNSRequest` with a 10s read deadline [`route/dns.go:23-33`, `constant/timeout.go:11`].

Docs confirm the intent and the 1.14 escape hatch: setting `dns_address` disables the auto-hijack and you must add a `hijack-dns` rule yourself [`docs/configuration/inbound/tun.md:284-292`].

### 4.2 Model A: `hijack-dns` action for any other resolver

A `port: 53` (or `protocol: dns` after sniff) rule with `action: hijack-dns` is *final*; `routeConnection` wraps peeked buffers and calls the same `hijackDNSStream`/`hijackDNSPacket` [`route/route.go:146-151,282-283`]. In pre-match, `hijack-dns` returns `PreMatchHijackDNS` only for UDP [`:402-406`], so UDP DNS matched by a rule is *also* answered inline by the dispatcher without a NAT entry. From there the DNS module walks `dns.rules` first-final-match and falls back to `dns.final` (see route-matching note §4). Every non-fake-ip answer that passes through the module is written to the reverse-mapping cache when `dns.reverse_mapping` is on [`dns/router.go:116-117,1109-1117`, doc `docs/configuration/dns/index.md:130-135`], and that cache is what gives later TCP/UDP connections a `metadata.Domain` before sniff [`route/route.go:567-572`].

### 4.3 Model B: fake-ip

The 1.12+ form is a DNS *server* of `type: fakeip` with `inet4_range`/`inet6_range` [`docs/configuration/dns/server/fakeip.md:11-25`]; the legacy `dns.fakeip` block is removed in 1.14 [`docs/configuration/dns/fakeip.md:5-7`]. The transport answers only A/AAAA, allocating from the store [`dns/transport/fakeip/fakeip.go:62-75`]. The store hands out sequential addresses starting at `range + 2`, wraps at the broadcast address, persists to `cache_file` when `store_fakeip` is enabled, else memory [`dns/transport/fakeip/store.go:76-83,107-153`]. On the connection side `prepareMatchMetadata` checks `Store().Contains(dst)`; if so it rewrites `Destination` to `{Fqdn: domain, Port}`, keeps the fake IP in `OriginDestination`, and sets `FakeIP=true`; a missing record is a hard error ("try enable `experimental.cache_file`") [`route/route.go:553-566`]. For UDP the packet conn is wrapped in `fakeIPNATPacketConn` so replies are rewritten back to the fake IP the app expects [`:305-307`, `route/fakeip_conn.go:23-31`]. `prepareMatchMetadata` runs in both `PreMatch` and `matchRule`, so pre-match sees the domain too [`:321,534`].

### 4.4 Where `dns.strategy` / `domain_resolver` apply to a TUN connection

A TUN connection's destination is an IP; the only resolution that happens for it is (a) a `resolve` route action, or (b) inside the outbound dialer when the destination became a domain via fake-ip or `sniff` with override. Outbound dialers are built by `dialer.NewWithOptions`: when `RemoteIsDomain`, it wraps the dialer in a `resolveDialer` using the outbound's `domain_resolver` (server + strategy), else `route.default_domain_resolver`, else the only DNS server [`common/dialer/dialer.go:65-146`]. `dns.strategy` is the DNS module's default answer strategy; the dialer's strategy comes from `domain_resolver.strategy` [`:86-95`]. Docs: for `direct`, `domain_resolver` affects "Domain in request"; for other outbounds only the server address [`docs/configuration/shared/dial.md:184-193`].

## 5. Routing and outbound, then the way back

After metadata is filled, `routeConnection` runs `matchRule` (sniff / resolve / final action, see the route-matching note), resolves the outbound, re-attaches peeked buffers, applies trackers, and calls either the outbound's own `NewConnection` or `ConnectionManager.NewConnection` [`route/route.go:108-178`].

`ConnectionManager.NewConnection` dials with the outbound as `N.Dialer` (`DialSerialNetwork` when resolved addresses exist, else `DialContext`) [`route/conn.go:101-105`], reports handshake success to the inbound conn (this is what releases gVisor's lazy SYN-ACK) [`:122`], optionally wraps TLS fragment/spoof [`:130-143`], and starts two `connectionCopy` goroutines [`:152-153`]. The copy loop is `bufio.CopyWithIncreateBuffer(destination, source, …)`; on EOF it half-closes the peer, on error closes both [`:273-308`].

For `direct`, `DialContext` refuses loopback into the TUN range, logs, and calls the `DefaultDialer` built in §2 [`protocol/direct/outbound.go:145-160`, `common/dialer/default.go:267-293`]. For a proxy outbound (shadowsocks/shadowtls here) the same `DefaultDialer` dials the server address; the bind/mark controls are identical.

Reply path per stack:

- **gvisor**: `remoteConn.Read` → `gTCPConn.Write` → gVisor TCP endpoint segments it → `LinkEndpoint.WritePackets` → `NativeTun.WritePacket` `writev` to the fd [`tun:tun_darwin_gvisor.go:17-42`] → kernel delivers to the app's socket.
- **system**: `remoteConn.Read` → write to the accepted kernel conn → kernel emits `src=<tunAddr>:tcpPort → dst=<tunAddr+1>:p` on the TUN → `tunLoop` reads it, `processIPv4TCP` rewrites to `src=1.2.3.4:443 → dst=app:port`, writes it back to the TUN [`tun:stack_system.go:244-249,486-493`] → kernel delivers to the app.

## 6. UDP specifics

- **NAT table.** `UDPNat` is an LRU (`freelru`) keyed by source `addr:port`; with the default `udp_mapping: endpoint_independent` the key also carries an egress-interface class so the same source can have one mapping per egress; `address_dependent`/`address_and_port_dependent` add destination fields [`tun:udp_nat.go:339-355`]. Capacity is `udp_nat_max`, defaulting to 4096 on iOS or `clamp(totalMem/16384, 4096, 16384)` [`:112-125`, doc `docs/configuration/shared/udp-nat.md:58-67`]. Lifetime is `udp_timeout` (5m) and is refreshed on every packet (`GetAndRefreshOrAdd`); eviction closes the conn [`:147-158,360,412`].
- **Association.** The first packet creates the conn and spawns `NewPacketConnectionEx` in a goroutine; each packet is queued into a 64-slot channel and **silently dropped when the channel is full** [`:416,422-443`]. The router reads the first packet(s) from that channel for sniffing and re-attaches them as cached packets [`route/route.go:243,294-297`].
- **Timeouts on the sing-box side.** `route-options`/`route` `udp_timeout` sets `metadata.UDPTimeout`; if absent, a sniffed or port-implied protocol picks `ProtocolTimeouts` (DNS/NTP/STUN 10s, QUIC/DTLS 30s); the resulting timeout wraps the conn in a `canceler` [`route/route.go:435-437`, `route/conn.go:252-266`, `constant/timeout.go:23-35`]. Docs: a value larger than the inbound's `udp_timeout` has no effect [`docs/configuration/route/rule_action.md:201-205`], which matches the NAT lifetime being the hard ceiling.
- **Copy loop.** `bufio.CopyPacket` in both directions; the return direction writes through the stack-specific writer (§3.1/§3.2) [`route/conn.go:269-270,368-393`].
- **MTU/fragmentation.** Both stacks drop IP fragments at the dispatcher and the system stack drops fragmented UDP explicitly [`tun:flow_dispatch.go:200`, `tun:stack_system.go:635-640`]; the TUN MTU therefore bounds UDP datagram size. Outbound sockets disable UDP fragmentation unless `udp_fragment` is set [`common/dialer/default.go:185-194`]. On the flow fast path, MTU is handled per port (§3.0).

## 7. Platform notes

- **macOS**: no fwmark; loop avoidance = `IP_BOUND_IF` to the interface the RIB monitor found via the surviving `0.0.0.0/0` (§2). `strict_route` has no macOS-specific code in sing-tun (the docs list only Linux and Windows effects [`docs/configuration/inbound/tun.md:433-451`]); its only effect on macOS is inferred to be nil. The `system` stack's forwarder listener is bound to the utun interface [`tun:stack_system.go:153-161`, `protocol/tun/inbound.go:463`]. `EXP_MultiPendingPackets` batching is turned on for small MTUs and whenever a TCP-capable `FlowOutbound` exists [`protocol/tun/inbound.go:191,340-364`]. System DNS is not configured by sing-tun on macOS (§1.4). TunnelVision: only the graphical client with `includeAllNetworks` is protected, which forces `gvisor` [`docs/manual/misc/tunnelvision.md:18-24`, `tun:stack.go:43-44`].
- **Windows**: wintun; routes with metric 0 on a metric-0 interface; per-interface DNS pushed from `dns_address`; `strict_route` = WFP permit-self/permit-TUN/block-rest plus block-port-53 (§1.5).
- **Linux**: policy rules, table 2022, `not dport 53 → main suppress_prefixlength 0`, systemd-resolved registration (§1.3); `auto_redirect` moves the whole thing to nftables + marks and is "always recommended" [`docs/configuration/inbound/tun.md:320-322`].
- **Android**: VpnService fd; loop avoidance is the app's `protect()` exposed as `AutoDetectInterfaceControl` [`route/network.go:369-374,396-405`, `experimental/libbox/service.go:47-53`]; `include_package` → UID ranges (§1.6); root CLI adds the `0x20000` VPN mark rule [`tun:tun_linux.go:899-927`].
- **iOS**: NetworkExtension fd, MTU capped to 4064, `includeAllNetworks` forces gVisor, default interface found by the connect trick [`protocol/tun/inbound.go:110-112`, `tun:monitor_darwin.go:180-224`].

## 8. Hop lists (for the teaching diagram)

Assumes the repo's config: `stack: gvisor`, `auto_route`, `auto_detect_interface`, macOS CLI, destination `1.2.3.4`, TUN `10.10.10.0/24`, physical NIC `en0`.

### TCP

1. App `connect(1.2.3.4:443)`; kernel routes `1.2.3.4` → matches `0.0.0.0/1` on `utunN` (gateway `10.10.10.0`) [`tun:tun_rules.go:124-133`, `tun:tun_darwin.go:457-501`]; kernel emits SYN on utun.
2. sing-tun gVisor `fdbased` endpoint reads the packet from the utun fd [`tun:tun_darwin_gvisor.go:44-53`].
3. `LinkEndpointFilter` → `ForwardDispatcher.Dispatch` → `JudgeFlow` → `Router.PreMatch` walks rules on IP metadata → not a `FlowOutbound` → `Accept` [`tun:stack_gvisor_filter.go:72-81`, `tun:flow_dispatch.go:279-313`, `route/route.go:316-418`].
4. gVisor netstack parses IP/TCP; TCP forwarder `Forward` on SYN → `JudgeFlow` again → `gLazyConn` → `Inbound.NewConnectionEx` [`tun:stack_gvisor_tcp.go:77-96`].
5. `NewConnectionEx` fills `Source/Destination/Inbound`, → `Router.RouteConnectionEx` [`protocol/tun/inbound.go:546-563`].
6. `routeConnection`: DNS check, `matchRule` (reverse-map/fake-ip, sniff, rules) → outbound `X` [`route/route.go:101-177`].
7. `ConnectionManager.NewConnection` → `X.DialContext` → `DefaultDialer` with `IP_BOUND_IF(en0)` → kernel → `en0` → server (or proxy server) [`route/conn.go:101-105`, `common/dialer/default.go:127-129,267-293`, `sing:common/control/bind_darwin.go:22-27`].
8. Dial succeeds → `ReportConnHandshakeSuccess` → `gLazyConn.HandshakeContext` → gVisor `CreateEndpoint` → SYN-ACK written to utun → app's `connect()` returns [`route/conn.go:122`, `tun:stack_gvisor_lazy.go:56-69`].
9. App `write()` → utun → gVisor TCP endpoint → `gTCPConn.Read` → `connectionCopy` → `remoteConn.Write` → kernel → `en0` → destination [`route/conn.go:152,274`].
10. Destination reply → `en0` → kernel → `remoteConn.Read` → `connectionCopy` → `gTCPConn.Write` → gVisor segments → `NativeTun.WritePacket` → utun fd → kernel → app `read()` [`route/conn.go:153`, `tun:tun_darwin_gvisor.go:17-42`].
11. Close: EOF on either side → `CloseWrite` on the peer; both closed on error; gVisor sends FIN/RST to the app [`route/conn.go:275-290`].

### UDP

1. App `sendto(1.2.3.4:5000)` → kernel → utun (same route as TCP).
2. gVisor endpoint reads it; dispatcher: first datagram → `JudgeFlow(firstPacket=payload)` → `PreMatch` (packet sniffers may run) → `Accept` [`tun:flow_dispatch.go:281-284`, `route/route.go:337-357`]. *If the destination is `10.10.10.1:53`: `ActionHijackDNS` → answered inline via `Router.HijackDNSPacket`, reply synthesised and written to utun; stop here* [`protocol/tun/inbound.go:523-544`, `tun:flow_dns.go:14-89`].
3. gVisor UDP forwarder → `UDPNat.NewPacket` → new entry keyed by source → `PreparePacketConnection` (`JudgeFlow` again, `UDPBackWriter`) → goroutine `Inbound.NewPacketConnectionEx`; datagram queued in the conn's channel [`tun:stack_gvisor_udp.go:52-103`, `tun:udp_nat.go:339-420`].
4. `NewPacketConnectionEx` → `Router.RoutePacketConnectionEx` → `routePacketConnection`: DNS check, `matchRule` (reads first packet(s) for sniff), outbound `X`, cached packets re-attached [`protocol/tun/inbound.go:565-584`, `route/route.go:240-313`].
5. `ConnectionManager.NewPacketConnection` → `X.ListenPacket` (bound to `en0`) → timeout wrapper → two `packetConnectionCopy` loops [`route/conn.go:203-209,252-270`].
6. Upload: channel → `CopyPacket` → `remotePacketConn.WriteTo(1.2.3.4:5000)` → kernel → `en0`.
7. Reply: `en0` → kernel → `ReadFrom` → `CopyPacket` → `udpNatConn.WritePacket` → `UDPBackWriter.WritePacket` → gVisor `route.WritePacket` → utun → app `recvfrom()` [`tun:stack_gvisor_udp.go:136-197`].
8. Idle `udp_timeout` (5m) with no packets → LRU eviction → conn closed → both copy loops end [`tun:udp_nat.go:147-158`].

(System stack differences: steps 2-4 for TCP become "SYN rewritten to the kernel listener, kernel completes handshake immediately, `acceptLoop` → `NewConnectionEx`"; the app's `connect()` returns *before* the outbound dial, and a failed dial is a later RST. UDP is identical except the reply is written by `systemUDPPacketWriter4` with a copied header [`tun:stack_system.go:660-688`].)

## 9. Applied to this repo

Files read: `scaffolds/client/{inbounds,dns,route,outbounds,endpoints,experimental}.json`, `rules/my-rules.jsonc`, `CONTEXT.md`.

What the client config uses:

| mechanism | this repo | effect |
|---|---|---|
| `stack` | `gvisor` [`scaffolds/client/inbounds.json:12`] | §3.2 path; lazy SYN-ACK; no kernel NAT listener |
| `address` | `10.10.10.0/24` [`:6-8`] | TUN IP is `10.10.10.0`; derived DNS/gateway address is `10.10.10.1` |
| `mtu` | 1420 [`:9`] | UDP datagrams above ~1392 payload cannot enter the TUN (§6) |
| `auto_route` / `strict_route` | both `true` [`:10-11`] | macOS: `/1` sub-ranges; Linux: policy rules + `unreachable` for IPv6 (no v6 address); Windows: WFP incl. port-53 block |
| `auto_redirect` | absent | Linux users get the iproute2 path, not nftables |
| `dns_mode` / `dns_address` | absent → `hijack`, derived `10.10.10.1` | UDP DNS to `10.10.10.1` is answered before rules (§4.1) |
| `udp_timeout` | absent → 5m | NAT lifetime |
| fake-ip | none (`dns.json` has no `fakeip` server) | destinations stay IPs; domain rules rely on sniff or reverse mapping |
| `dns.reverse_mapping` | `true` [`scaffolds/client/dns.json:31`] | hijacked answers seed `metadata.Domain` pre-sniff |
| `port: 53 → hijack-dns` | rule 2 [`scaffolds/client/route.json:210-213`] | catches DNS to any other resolver that reaches the TUN |
| `auto_detect_interface` | `true` [`:348`] | loop avoidance via `IP_BOUND_IF`/`SO_BINDTOIFINDEX` (§2) |
| `default_interface` / `default_mark` / `routing_mark` / `bind_interface` | none | fine; nothing conflicts |
| `default_domain_resolver` | `dns-resolver` (UDP 1.1.1.1 via outbound `UDP`) [`:349`, `dns.json:14-19`] | used only when a destination is a domain (proxy server names, sniff override) |
| `ts-ep` Tailscale endpoint + `ip_cidr 100.64.0.0/10 → ts-ep` | rule 1 [`route.json:206-209`, `endpoints.json:3-19`] | **pre-match flow path**: Tailscale is a `FlowOutbound`, so mesh traffic is forwarded at L3 by the dispatcher and never becomes a gVisor conn (§3.0); on macOS this also enables `EXP_MultiPendingPackets` [`protocol/tun/inbound.go:340-364`] |

Footguns and observations:

1. **Network address as host address.** `10.10.10.0/24` makes the interface address the subnet's `.0`. It works on utun (point-to-point) and modern Linux accepts it, but the docs' examples use `x.x.x.1/30` [`docs/configuration/inbound/tun.md:77-80`], and with the `system` stack the kernel listener would bind `10.10.10.0` [`tun:stack_system.go:166`]. Inferred: harmless with gVisor; switch to `10.10.10.1/24` (DNS becomes `.2`) if anyone flips `stack`.
2. **DNS hijack rarely fires on macOS CLI.** sing-tun does not set system DNS on macOS (§1.4). With the router's LAN resolver (`192.168.x.1`) the kernel's directly-connected `/24` route beats the TUN's `/1` routes, so system DNS **bypasses the TUN entirely** and neither the derived hijack nor the `port: 53` rule sees it. The graphical Apple client fixes this by installing `10.10.10.1` as the tunnel's DNS via NetworkExtension [`experimental/libbox/tun.go:102-107`]. Inferred: for CLI use on macOS, users must set `10.10.10.1` as DNS manually or add `route_address`/exclusions deliberately.
3. **`strict_route` on Windows blocks all non-TUN port 53** [`tun:tun_windows.go:332-364`], including a LAN resolver a user may rely on while sing-box is up. Combined with per-interface DNS = `10.10.10.1` this is intended; just be aware it is a firewall rule, not a route.
4. **`strict_route` on Linux without an IPv6 address** installs an `unreachable` rule for IPv6 [`tun:tun_linux.go:929-946`]: IPv6-only destinations fail fast rather than leaking. Intended, but it is a visible behaviour change for dual-stack LANs.
5. **MTU 1420** is below the 65535 CLI default. Sing-tun does not fragment; UDP payloads above the MTU are dropped at the dispatcher [`tun:flow_dispatch.go:200`, `tun:stack_system.go:635-640`]. With gVisor and a Shadowsocks/ShadowTLS transport there is no inner tunnel header that would justify 1420 (that number is a WireGuard convention). Inferred: raising it, or leaving it unset, removes a class of large-datagram failures (QUIC works either way because it caps at 1200-1350).
6. **Port-53 rule position** (already flagged in the route-matching note): it sits *after* the `100.64.0.0/10 → ts-ep` rule, so MagicDNS at `100.100.100.100:53` goes to Tailscale (correct for this repo, since the mesh resolver lives there) — but note that with the flow fast path that packet is forwarded at L3 and is never sniffed.
7. **No `udp_timeout` override for the tailscale endpoint's flows**: flow UDP timeout comes from `route-options`/sniffed protocol via `preMatchFlow` [`route/route.go:475-487`], otherwise the dispatcher default of 5m [`tun:flow_dispatch.go:21`]. Fine as-is.
8. **`reverse_mapping` on macOS** is documented as unreliable because the system resolver caches [`docs/configuration/dns/index.md:134-135`]; combined with footgun 2, domain rules for TCP in this config effectively depend on `sniff` (which the config has, rule 7).

## 10. Config keys touched

| key | struct field | file:line |
|---|---|---|
| `interface_name` | `TunInboundOptions.InterfaceName` | `option/tun.go:15` |
| `netns` | `.NetNs` | `:16` |
| `mtu` | `.MTU` | `:17` |
| `address` | `.Address` | `:18` |
| `dns_mode` | `.DNSMode` | `:19` |
| `dns_address` | `.DNSAddress` | `:20` |
| `auto_route` | `.AutoRoute` | `:21` |
| `iproute2_table_index` / `iproute2_rule_index` | `.IPRoute2TableIndex` / `.IPRoute2RuleIndex` | `:22-23` |
| `auto_redirect` (+ `_input_mark`, `_output_mark`, `_reset_mark`, `_nfqueue`, `_iproute2_fallback_rule_index`) | `.AutoRedirect*` | `:24-29` |
| `exclude_mptcp` | `.ExcludeMPTCP` | `:30` |
| `loopback_address` | `.LoopbackAddress` | `:31` |
| `strict_route` | `.StrictRoute` | `:32` |
| `route_address` / `route_address_set` / `route_exclude_address` / `route_exclude_address_set` | `.RouteAddress*` | `:33-36` |
| `include_interface` / `exclude_interface` | `.IncludeInterface` / `.ExcludeInterface` | `:37-38` |
| `include_uid` / `include_uid_range` / `exclude_uid` / `exclude_uid_range` | `.IncludeUID*` / `.ExcludeUID*` | `:39-42` |
| `include_android_user` / `include_package` / `exclude_package` | `.IncludeAndroidUser` / `.IncludePackage` / `.ExcludePackage` | `:43-45` |
| `include_mac_address` / `exclude_mac_address` | `.IncludeMACAddress` / `.ExcludeMACAddress` | `:46-47` |
| `udp_timeout` / `udp_mapping` / `udp_filtering` / `udp_nat_max` | `.UDPTimeout` / `.UDPMapping` / `.UDPFiltering` / `.UDPNATMax` | `:48-51` |
| `stack` | `.Stack` | `:52` |
| `platform` | `.Platform` | `:53` |
| `route.auto_detect_interface` / `default_interface` / `default_mark` / `default_domain_resolver` | `RouteOptions.AutoDetectInterface` / `.DefaultInterface` / `.DefaultMark` / `.DefaultDomainResolver` | `option/route.go:14,16,17,18` |
| `route.override_android_vpn` | `RouteOptions.OverrideAndroidVPN` | `option/route.go:15` |
| outbound `bind_interface` / `routing_mark` / `domain_resolver` | `DialerOptions.BindInterface` / `.RoutingMark` / `.DomainResolver` | used at `common/dialer/default.go:77,85`, `common/dialer/dialer.go:77` |
| `dns.reverse_mapping` | `DNSOptions.ReverseMapping` | used at `dns/router.go:116` |
| `dns.servers[].type: fakeip` (`inet4_range`, `inet6_range`) | `FakeIPDNSServerOptions.Inet4Range` / `.Inet6Range` | used at `dns/transport/fakeip/fakeip.go:33-34` |

## Open questions / unverified

- The nftables chain layout for `auto_redirect` (`redirect_nftables_rules.go`, 1202 lines) was only sampled for the DNS DNAT; the exact input-mark/output-mark chain ordering and the nfqueue pre-match are not verified here.
- `strict_route` on macOS: no Darwin-specific code was found in sing-tun for it, and the docs describe only Linux and Windows. Treating it as a no-op on macOS is inferred, not proven (the graphical client may act on the flag via NetworkExtension).
- Whether macOS's kernel prefers the directly-connected LAN route over the TUN's `/1` routes for the LAN resolver (footgun 2) is standard longest-prefix behaviour, not something sing-tun code demonstrates; it is inferred.
- Linux gateway on auto_route: `routes()` carries a comment "Do not create gateway on linux by default" [`tun:tun_linux.go:652`] but still passes `address[0]+1` as gateway when it exists [`:653-660`, `tun:tun.go:185-188`]. The practical effect (on-link route vs gateway route) was not tested.
- The ICMP forwarder in the gVisor stack and `direct`'s ICMP `FlowOutbound` port were not traced end to end.
- `EXP_MultiPendingPackets` / Darwin batch `sendmsg_x` behaviour is marked experimental in sing-tun and was not evaluated for correctness.
- Which sing-box build the repo's end users run (CLI vs SFM/SFI graphical client) is not recorded in the repo; the macOS DNS conclusion in §9 depends on it.
