- [v1](./v1/)
  - using multiple proxies
  - using supervisor to manage multiple services in single container
  - credits https://github.com/fscarmen/sing-box
- [v2](./v2/)
  - using only shadowsocks
  - using docker compose to manage multiple containers
  - dynamic config generation
  - tailscale endpoint as exit node
  - rerouting tailscale outbound to Cloudflare warp

### Note for DNS Settings

Sing-box supports to resolve DNS queires from server side, client side or both.
It's more flexiable to configure DNS server settings from the client side rather than the server side using some public remote DNS.

### Notes for common issues

1. Server: Disable `sniff`, otherwise _no recent network activity will occur_.
2. Server: Disable `sniff_override_destination`, otherwise _DNS will not be used_.
3. Client: Remove `fakeip` to enable `direct` network.
4. Clinet: Use `dns-local`, but other dns servers should work!
5. Client: Enable `sniff` in `tun`, otherwise _no recent network activity will occur_.
6. Client: Enable `sniff_override_destination` in `tun`, otherwise _unexpected connection closed error will occur_.
