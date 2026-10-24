# Historical Hysteria2 deployment instructions

These instructions describe the deployment before Hysteria2 was retired from API-served VPN profiles. They are preserved for the investigation in [issue #65](https://github.com/minlaxz/nekohasekai/issues/65), not for deploying the current images. See [ADR 0005](../adr/0005-retire-hysteria2.md) and the [current deployment instructions](../../README.md).

The operator reported that Hysteria2 did not connect promptly when first opening the VPN and appeared less stable than Shadowsocks over ShadowTLS. The cause has not been diagnosed. Existing Hysteria2 concept notes, research, and ADR 0001 remain available; reintroduction is a future investigation.

## How it works

- **Server** runs three inbounds: Shadowsocks (loopback only; per-user PSK, managed by sing-box's ssm-api), ShadowTLS v3 (one shared handshake password, detours into Shadowsocks), and Hysteria2 (QUIC with Salamander obfuscation, one shared password, routed to the Shadowsocks inbound and nowhere else). ShadowTLS and Hysteria2 are transport only. All user identity lives in Shadowsocks.
- **Client profile** (`/c`) is built from `scaffolds/client/*.json`. The API fills in log level, DNS, and the user's PSK. Everything else is served as-is. `/i` wraps that into a `sing-box://import-remote-profile` link.
- **First start** seeds the config volume from the image and writes ports, SNI, and the ShadowTLS password once. It also writes the Hysteria2 passwords once and generates a self-signed certificate once; the client template carries that certificate as its trust anchor. Every start re-detects the public IPv4 and writes it into the client template.
- **Users** live in `users.json`. The API mirrors them into ssm-api at startup and every minute (expired and disabled users out, live users in) and keeps the file in sync through `/ssm/create`, `/ssm/renew`, `/ssm/disable`, `/ssm/enable` and `/ssm/delete`.

## Deploy

Prerequisites: Docker with the Compose plugin. Swap is strongly recommended on a 512 MB VPS (see below).

```sh
git clone https://github.com/minlaxz/nekohasekai.git && cd nekohasekai
cp .env.sample .env
cp example-users.json users.json
docker network create caddy-net
```

Edit `.env`:

| Variable | Required | Meaning |
|---|---|---|
| `SHADOWSOCKS_PORT` | yes | Shadowsocks inbound, loopback only, not published |
| `SHADOWSOCKS_PASSWORD` | yes | SS-2022 server PSK, exactly 16 bytes: `openssl rand -base64 16` |
| `SHADOWTLS_PORT` | yes | ShadowTLS inbound, published TCP |
| `HYSTERIA2_PORT` | yes | Hysteria2 inbound, published UDP only |
| `HYSTERIA2_PASSWORD` | yes | Shared Hysteria2 password |
| `HYSTERIA2_OBFS_PASSWORD` | yes | Shared Salamander obfuscation password |
| `SHADOWTLS_SNI` | yes | Domain the handshake imitates, e.g. `mozilla.org` |
| `SHADOWTLS_PASSWORD` | yes | Shared handshake password |
| `PUBLIC_IP` | no | Skips auto-detection |
| `APP_HOST` | yes | Public hostname of the API, used in import links and Caddy |
| `APP_ADMIN_PASSWORD` | yes | HTTP Basic password for `/ssm/*`. Unset = every admin request refused |
| `APP_ADMIN_USER` | no | HTTP Basic username, default `admin` |
| `APP_CORS_ORIGINS` | no | Extra browser origins allowed to call the API, comma-separated |
| `APP_DEFAULT_*` | no | Defaults for `/c` query parameters |

The four `*_PASSWORD` values are shared by every client (per-user auth is the Shadowsocks PSK). Generate `SHADOWSOCKS_PASSWORD` with `openssl rand -base64 16` and the other three with:

```sh
openssl rand -base64 32
```

`docker compose up` refuses to start sing-box while any of the seven required values is empty.

Then:

```sh
docker compose pull
docker compose up -d                       # sing-box + API; TLS ingress is the separate caddy-ingress deployment
docker compose logs sing-box | grep entrypoint
```

Expect `configured ports ...` and `configured hysteria2 ...` on first start and `public ip x.x.x.x` on every start.

### Upgrade

```sh
docker compose pull && docker compose up -d
```

That is the whole upgrade path. The image carries the configs: every start copies the client template (`route.json`, `dns.json`, `inbounds.json`, ...) from the image into the volume, so rule and DNS changes land without touching it. `client/outbounds.json`, `server/`, and `cache/` persist; outbounds the image adds (new tags) are appended to `outbounds.json` on start, existing entries stay as they are.

`git pull` on the server is only needed when `docker-compose.yaml` changes or `.env` gains a new variable.

**Upgrading a server deployed before Hysteria2:** add `HYSTERIA2_PORT`, `HYSTERIA2_PASSWORD` and `HYSTERIA2_OBFS_PASSWORD` to `.env`, open that UDP port in the VPS firewall, then `git pull && docker compose pull && docker compose up -d`. The next start adds the Hysteria2 inbound, its route rules, and the client outbounds to the existing volume and logs `configured hysteria2 ...`. Existing ports, SNI, and passwords stay as they are. Users get the new outbound when their client refreshes its profile.

Ports, SNI, the ShadowTLS and Hysteria2 passwords, and the Hysteria2 certificate are written once. To change them, remove the volume:

```sh
docker compose down && docker volume rm sing-box_sing-box-configs && docker compose up -d
```

## Develop

No Docker needed for the fast loop:

```sh
# API
cd api && uv run --with 'fastapi[standard]' --with httpx --with apscheduler fastapi dev app/main.py

# Entrypoint, against a scratch dir with a stubbed sing-box
SING_BOX_ROOT=/path/to/scratch SHADOWSOCKS_PORT=1 SHADOWSOCKS_PASSWORD=$(openssl rand -base64 16) SHADOWTLS_PORT=2 HYSTERIA2_PORT=3 \
  SHADOWTLS_SNI=x SHADOWTLS_PASSWORD=y HYSTERIA2_PASSWORD=h HYSTERIA2_OBFS_PASSWORD=o \
  PUBLIC_IP=1.2.3.4 sh scaffolds/entrypoint.sh

# Tests. SING_BOX is optional; it adds `sing-box check` on the generated Server config.
SING_BOX=/path/to/sing-box sh scaffolds/entrypoint.test.sh
cd api && uv run --with 'fastapi[standard]' --with httpx --with apscheduler --with pytest pytest -q tests
```

Validate a config inside the image: `sing-box check -C /sing-box/server`.
