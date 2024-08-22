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

- TCP
    - XTLS_REALITY=true
    - H2_REALITY=true
    - GRPC_REALITY=true
    - VLESS_WS=true
    - TROJAN=true
    - SHADOWTLS=true
    - SHADOWSOCKS=true

- TCP + Brutal (`TCP Brutal`, [installation](https://github.com/minlaxz/nekohasekai?tab=readme-ov-file#tcp-brutal-multiplexing-for-tcp-proxies))
    - XTLS_REALITYX=true
    - H2_REALITYX=true
    - GRPC_REALITYX=true
    - VLESS_WSX=true
    - TROJANX=true
    - SHADOWTLSX=true
    - SHADOWSOCKSX=true
