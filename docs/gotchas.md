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
- `dns-remote` detours via the `DNS` selector group (`direct` default, or `TCP`). If a network blocks `dns.nextdns.io` / `45.90.28.0`, switch the `DNS` group to `TCP` in the app (same place as Clash mode / proxy groups), no config edit. `interrupt_exist_connections` drops the open DoH transport so the switch takes effect at once. Trade-off when on `TCP`: NextDNS and CDNs see the VPS IP; dashboard still shows per-user device names (from the DoH path). Bootstrap `dns-resolver` already detours via `APP_DEFAULT_DNS_DETOUR` (`UDP` group).
- Symptom (2026-09-15, cellular and wifi at once): every site dead, Slack/Telegram stuck connecting, yet urltest and direct outbounds healthy. Log is silent, no error line:
  ```
  inbound/tun[tun-in]: inbound DNS packet from 10.10.10.1:63715
  dns: exchange example.com. IN A
  <no "dns: exchanged ..." reply, client retries every 2-4 s>
  ```
  `ping 1.1.1.1` pongs, `ping example.com` says bad address. Quick check from a Mac on the same network, below the TUN:
  `curl --interface en0 --resolve dns.nextdns.io:443:45.90.28.243 https://dns.nextdns.io/dns-query?name=example.com -H 'accept: application/dns-json'`

### TUN on macOS CLI: LAN resolver bypasses the tunnel
- sing-tun never installs the TUN DNS address (`10.10.10.2`, address+1) as system resolver on macOS CLI. If the system resolver is a LAN address (`192.168.x.1` from DHCP), the directly-connected `/24` beats the TUN's `/1` routes and DNS leaves via en0: neither the auto hijack nor the `port: 53` rule sees it.
- A public resolver (`1.1.1.1`, `8.8.8.8`) is fine: it matches the TUN routes and the `port: 53` rule hijacks it. Check: `scutil --dns | grep nameserver` and `route -n get <resolver>` must say `utun`.
- Fix if it says `en0`: `networksetup -setdnsservers Wi-Fi 10.10.10.2` (or any public IP). Graphical clients (SFM/SFI/SFA) and Windows/Linux install DNS themselves. Detail: `docs/research/sing-box-tun-inbound.md` §9.
