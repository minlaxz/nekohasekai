- [v1](/v1/) 
    + old version
    + using multiple proxies
    + complicated setup
    + using supervisor to manage multiple services in single container
- [v2](/v2/)
    + new version
    + using only shadowsocks
    + simple setup
    + using docker compose to manage multiple containers

### Note for DNS Settings
With sing-box, it's possible to handle answering DNS queries both from server side or client side. But it's more flexiable to configure DNS server settings from the client side rather than the server side.

### Notes for common issues
1. Server: Disable `sniff`, otherwise _no recent network activity will occur_.
2. Server: Disable `sniff_override_destination`, otherwise _DNS will not be used_.
3. Client: Remove `fakeip` to enable `direct` network.
4. Clinet: Use `dns-local`, but other dns servers should work!
5. Client: Enable `sniff` in `tun`, otherwise _no recent network activity will occur_.
6. Client: Enable `sniff_override_destination` in `tun`, otherwise _unexpected connection closed error will occur_.
