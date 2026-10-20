# Concepts

Teaching notes, one term per file, no repo specifics. Written for someone
who has never met the term. Read in order; each file assumes the ones above it.

Built over time. Add a line when a new file lands.

1. [inbound-tls](inbound-tls.md) — why every sing-box inbound has a `tls` block; what leaks without it.
2. [tun-inbound](tun-inbound.md) — how a TUN turns any app's traffic into a sing-box connection; stacks, loop avoidance, DNS, hop lists.
3. [magicdns](magicdns.md) — how tailnet devices get DNS names from a local resolver; ephemeral name collisions, what headscale changes.
4. [outbound-tls](outbound-tls.md) — the client half: how a sing-box outbound verifies the server and shapes its ClientHello; `insecure`, SNI, `utls`, `reality`.
5. [hysteria2](hysteria2.md) — a QUIC proxy dressed as an HTTP/3 site; every inbound field, Brutal vs BBR, obfs vs masquerade.
6. [fake-handshake-stall](fake-handshake-stall.md) — why a TUN IPv6 address with no IPv6 path makes sites hang instead of falling back to IPv4; Happy Eyeballs, DNS blocking limits.
