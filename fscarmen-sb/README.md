### Supported ENV VARS

- ARGO_DOMAIN=sv1.yourdomain.tld
- ARGO_AUTH=
- CDN=www.csgo.com
- SERVER_IP=1.2.3.4
- START_PORT=8800

```
docker run --rm ghcr.io/minlaxz/nekohasekai:fscarmen-sb generate uuid
```

- UUID=

```
docker run --rm ghcr.io/minlaxz/nekohasekai:fscarmen-sb generate reality-keypair
```

- CUSTOM_REALITY_PRIVATE=
- CUSTOM_REALITY_PUBLIC=

```
docker run --rm ghcr.io/minlaxz/nekohasekai:fscarmen-sb generate rand --base64 16
```

- CUSTOM_SHADOWTLS_PASSWORD=

---

### Proxies

- UDP

  - HYSTERIA2=true
  - TUIC=true

- TCP + Brutal (`TCP Brutal`, [installation](https://github.com/minlaxz/nekohasekai?tab=readme-ov-file#tcp-brutal-multiplexing-for-tcp-proxies)) _For containers which you have access to underlying host_

  - XTLS_REALITYX=true
  - H2_REALITYX=true
  - GRPC_REALITYX=true
  - VLESS_WSX=true
  - TROJANX=true
  - SHADOWTLSX=true
  - SHADOWSOCKSX=true

- TCP _For containers which you **don't** have access to underlying host, ECS Fargate launch type for example_
  - XTLS_REALITY=true
  - H2_REALITY=true
  - GRPC_REALITY=true
  - VLESS_WS=true
  - TROJAN=true
  - SHADOWTLS=true
  - SHADOWSOCKS=true

### Note for DNS Settings

To use DNS servers (for example, AdGuard Remote DNS) configured from the client side.

1. Server: Disable `sniff`, otherwise _no recent network activity will occur_.
2. Server: Disable `sniff_override_destination`, otherwise _DNS will not be used_.
3. Client: Remove `fakeip` to enable `direct` network.
4. Clinet: Use `dns-local`, but other dns servers should work!
5. Client: Enable `sniff` in `tun`, otherwise _no recent network activity will occur_.
6. Client: Enable `sniff_override_destination` in `tun`, otherwise _unexpected connection closed error will occur_.
