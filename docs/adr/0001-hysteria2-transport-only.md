# Hysteria2 is transport only; Shadowsocks runs inside it

The Hysteria2 transport (#22) has one shared password and carries Shadowsocks inside it. On the server, traffic from the Hysteria2 inbound may reach only the local Shadowsocks inbound; everything else is rejected. We chose this so that the PSK stays the gate and Managed users stay the only per-user identity: quota, user create and user delete keep working through ssm-api with no sing-box restart. This is the same pattern as ShadowTLS.

The cost is deliberate: traffic is encrypted twice, and each UDP packet loses about 55 bytes to the Shadowsocks header. Do not "simplify" the path by removing the inner Shadowsocks layer.

## Considered Options

- **Per-user Hysteria2 users (password = PSK).** Rejected: the Hysteria2 `users` list is static, so every user change needs a config write and a sing-box restart, and ssm-api does not count traffic on that inbound, so quota is lost.
- **Shared Hysteria2 password as a direct proxy.** Rejected: a removed user keeps access until the shared password is rotated, and there is no quota.

## Consequences

- The client needs two outbounds (outer `hysteria2`, inner Shadowsocks with `detour`) and the server needs two route rules that confine the Hysteria2 inbound.
- Multiplex stays off on the inner Shadowsocks outbound. With smux on, UDP travels inside the smux stream and no longer uses QUIC datagrams.
- In the server log, the client's real address is on the Hysteria2 inbound line and the user name is on the Shadowsocks inbound line.
