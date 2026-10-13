# Network diagnostics

Command cookbook for diagnosing sing-box tunnels from the client host, split
by topic. Append new commands to the matching file whenever a diagnosis
session uses one; start a new `network-diag-<topic>.md` when none fits, and
list it here.

Each entry: what it tells you, the command, how to read the output.
Commands use BSD tools (`nc`, `ping`) unless noted; GNU flags differ.

| File | Covers |
|---|---|
| [network-diag-clash-api.md](network-diag-clash-api.md) | sing-box state over the Clash API: selected group members, active connections and their matched rule |
| [network-diag-reachability.md](network-diag-reachability.md) | RTT, TCP and UDP port checks under the tun, proxy env vars, utun interfaces |
| [network-diag-openvpn.md](network-diag-openvpn.md) | MTU / MSS blackhole, worked case: OpenVPN endpoint over shadowtls |
| [network-diag-ipv6.md](network-diag-ipv6.md) | Which path IPv6 takes: system DNS vs browser DoH, address sorting, WARP |
| [network-diag-vps.md](network-diag-vps.md) | "User X can (not) connect": which VPS the client uses, what sing-box accepted |
