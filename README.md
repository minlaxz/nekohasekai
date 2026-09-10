# nekohasekai

Self-hosted [sing-box](https://github.com/SagerNet/sing-box) server plus a small API that hands out per-user client profiles. Built to get around Myanmar internet restrictions. Transport is Shadowsocks over ShadowTLS v3.

The repository name comes from the author of sing-box. Please consider supporting the original project ❤️

## Layout

| Path | What it is | Image |
|---|---|---|
| `scaffolds/` | sing-box server: config templates, client templates, init entrypoint | `ghcr.io/minlaxz/nekohasekai:neko` |
| `api/` | FastAPI service: profile generation, user management, stats | `ghcr.io/minlaxz/nekohasekai:neko-api` |
| `rules/` | Routing rule generation from OONI data, published on the [`route-rules`](https://github.com/minlaxz/nekohasekai/tree/route-rules) branch | |
| `docker-compose.yaml` | Runs both, optionally behind Caddy | |
| `CONTEXT.md` | Glossary of domain terms | |

Images are built by GitHub Actions on push to `master`.

## How it works

- **Server** runs two inbounds: Shadowsocks (per-user PSK, managed by sing-box's ssm-api) and ShadowTLS v3 (one shared handshake password, detours into Shadowsocks). ShadowTLS is transport only. All user identity lives in Shadowsocks.
- **Client profile** (`/c`) is built from `scaffolds/client/*.json`. The API fills in log level, DNS, and the user's PSK. Everything else is served as-is. `/i` wraps that into a `sing-box://import-remote-profile` link.
- **First start** seeds the config volume from the image and writes ports, SNI, and the ShadowTLS password once. Every start re-detects the public IPv4 and writes it into the client template.
- **Users** live in `users.json`. The API seeds them into ssm-api at startup (add-only) and keeps the file in sync through `/ssm/create` and `/ssm/delete`.

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
| `SHADOWSOCKS_PORT` | yes | Shadowsocks inbound, published TCP and UDP |
| `SHADOWTLS_PORT` | yes | ShadowTLS inbound, published TCP |
| `SHADOWTLS_SNI` | yes | Domain the handshake imitates, e.g. `mozilla.org` |
| `SHADOWTLS_PASSWORD` | yes | Shared handshake password |
| `PUBLIC_IP` | no | Skips auto-detection |
| `APP_HOST` | yes | Public hostname of the API, used in import links and Caddy |
| `APP_DEFAULT_*` | no | Defaults for `/c` query parameters |

Then:

```sh
docker compose pull
docker compose up -d                       # sing-box + API
docker compose --profile with-caddy up -d  # also Caddy with automatic TLS
docker compose logs sing-box | grep entrypoint
```

Expect `configured ports ...` on first start and `public ip x.x.x.x` on every start.

Upgrade is the same two commands: `docker compose pull && docker compose up -d`. Every start copies the client template (`route.json`, `dns.json`, `inbounds.json`, ...) from the image into the volume, so rule and DNS changes land without touching it. `client/outbounds.json`, `server/`, and `cache/` persist.

Ports, SNI, and the ShadowTLS password are written once. To change them, remove the volume:

```sh
docker compose down && docker volume rm sing-box_sing-box-configs && docker compose up -d
```

## Users

`users.json`:

```json
{ "users": [ { "name": "alice", "password": "20-random-chars==", "admin": false } ] }
```

Optional `ts_auth_key` (Mesh key): a reusable headscale pre-auth key for that user. Mint it by hand:

```sh
headscale preauthkeys create --user alice --reusable --expiration 1y
```

A user with a Mesh key gets the `ts-ep` tailscale endpoint (hostname = username, `control_url` from `APP_TS_CONTROL_URL`) and `100.64.0.0/10` routed into it. A user without one gets no endpoint and no such rule.

- Import link: `https://<APP_HOST>/i?j=<name>&k=<password>`
- Raw profile: `https://<APP_HOST>/c?j=<name>&k=<password>`
- Create: form at `/ssm/form`, or `POST /ssm/create`
- Delete: `POST /ssm/delete` with form field `username`
- Stats: `/ssm/server/v1/users`

Changes take effect immediately. No restart needed.

`/c` query parameters (each falls back to its `APP_DEFAULT_*`): `ll` log level, `dh` DoH host or IP, `dn` DoH TLS server name (when `dh` is an IP), `dp` DoH path prefix (username is appended), `dr` resolver IP, `dd` resolver detour, `df` DNS final, `dv` 4 or 6, `mx` multiplex.

## Develop

No Docker needed for the fast loop:

```sh
# API
cd api && uv run --with 'fastapi[standard]' --with httpx --with apscheduler fastapi dev app/main.py

# Entrypoint, against a scratch dir with a stubbed sing-box
SING_BOX_ROOT=/path/to/scratch SHADOWSOCKS_PORT=1 SHADOWTLS_PORT=2 \
  SHADOWTLS_SNI=x SHADOWTLS_PASSWORD=y PUBLIC_IP=1.2.3.4 sh scaffolds/entrypoint.sh
```

Validate a config inside the image: `sing-box check -C /sing-box/server`.

## VPS tuning

Swap for low-memory hosts:

```sh
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
```

BBR congestion control:

```sh
echo net.core.default_qdisc=fq | sudo tee -a /etc/sysctl.conf
echo net.ipv4.tcp_congestion_control=bbr | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```
