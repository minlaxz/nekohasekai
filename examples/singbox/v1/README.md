## Supported Environment Variables

- START_PORT=8800
- ARGO_DOMAIN=<sv1.yourdomain.tld>
- ARGO_AUTH=<your-argo-tunnel-auth-token>
- CDN=www.csgo.com

```
docker run --rm ghcr.io/sagernet/sing-box generate uuid
```

- CUSTOM_UUID=

```
docker run --rm ghcr.io/sagernet/sing-box generate reality-keypair
```

- CUSTOM_REALITY_PRIVATE=
- CUSTOM_REALITY_PUBLIC=

```
docker run --rm ghcr.io/sagernet/sing-box generate rand --base64 16
```

- CUSTOM_SHADOWTLS_PASSWORD=

---

## Proxies (Default all disabled, enable by setting ENV VAR to true)

#### UDP Proxies:
  - HYSTERIA2=true
  - TUIC=true

### TCP Proxies:
- TCP + Brutal (`TCP Brutal`, [installation](https://github.com/minlaxz/nekohasekai?tab=readme-ov-file#tcp-brutal-multiplexing-for-tcp-proxies)) _If you have access to the underlying host_

  - XTLS_REALITYX=true
  - H2_REALITYX=true
  - GRPC_REALITYX=true
  - VLESS_WSX=true
  - TROJANX=true
  - SHADOWTLSX=true
  - SHADOWSOCKSX=true

- TCP _If you **don't** have access to `/dev/net/tun` of the underlying host_
  - XTLS_REALITY=true
  - H2_REALITY=true
  - GRPC_REALITY=true
  - VLESS_WS=true
  - TROJAN=true
  - SHADOWTLS=true
  - SHADOWSOCKS=true

### Note for `X`
> `X` means `with XTLS` (for XTLS Realitiy proxies) or `with Brutal` (for Brutal Multiplexing proxies)
