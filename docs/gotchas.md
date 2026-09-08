### SHADOWTLS SNI must be matched
- see at server.inbounds[1].handshake.server and client.outbounds[3].tls.server_name

### Others
[tunnelvision](https://sing-box.sagernet.org/manual/misc/tunnelvision/)
- enable includeAllNetworks under Settings - Packet Tunnel
- change TUN stack to `gvisor` see client.inbounds[0].stack

### Full mode is admin-only
- `clash_mode: Full` rules in client route.json are stripped by the API for users without `admin: true` (see `apply_full_mode`). Mesh (`ts-ep`) rules are stripped the same way for users without `ts_auth_key`.

### DNS: when NextDNS gets blocked
- Today DoH to NextDNS goes direct (no `detour` on `dns-remote`): NextDNS dashboard shows each user's IP, CDNs resolve near the user.
- If a network blocks `dns.nextdns.io` / `45.90.28.0`, add `"detour": "TCP"` to `dns-remote` in `scaffolds/client/dns.json`. Trade-off: NextDNS and CDNs see the VPS IP; dashboard still shows per-user device names (from the DoH path). Bootstrap `dns-resolver` already detours via `APP_DEFAULT_DNS_DETOUR` (`UDP` group).
