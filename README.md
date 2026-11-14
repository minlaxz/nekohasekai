# nekohasekai

Self-hosted [sing-box](https://github.com/SagerNet/sing-box) server plus a small API that hands out per-user client profiles. Built to get around Myanmar internet restrictions. Clients reach it through ShadowTLS v3 (TCP), carrying Shadowsocks for both TCP and UDP. Shadowsocks itself is never exposed on the internet.

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

- **Server** runs two inbounds: Shadowsocks (loopback only; per-user PSK, managed by sing-box's ssm-api) and ShadowTLS v3 (one shared handshake password, detours into Shadowsocks). ShadowTLS is transport only. All user identity lives in Shadowsocks.
- **Client profile** (`/c`) is built from `scaffolds/client/*.json`. The API fills in log level, DNS, and the user's PSK. Everything else is served as-is. `/i` wraps that into a `sing-box://import-remote-profile` link.
- **First start** seeds the config volume from the image and writes ports, SNI, and the ShadowTLS password once. Every start re-detects the public IPv4 and writes it into the client template.
- **Users** live in the API's SQLite store (`./data/users.db` on the host). The API mirrors them into ssm-api at startup and every minute (expired and disabled users out, live users in). The admin changes them only through the dashboard and `/ssm/*`; User import and User export move them in and out as CSV.

Client profiles keep the `shadowsocks-uot` outbound for Shadowsocks over ShadowTLS with UDP-over-TCP. They expose two groups: `All Outbounds`, a URL test over `direct` and `shadowsocks-uot`, and `Remote DNS Detour`, a selector over the same two options that defaults to `direct`. Proxied routes, rule-set downloads, Mesh, and WARP use `shadowsocks-uot` directly, so they cannot select the direct path through `All Outbounds`.

## Deploy

Prerequisites: Docker with the Compose plugin. Swap is strongly recommended on a 512 MB VPS (see below).

```sh
git clone https://github.com/minlaxz/nekohasekai.git && cd nekohasekai
cp .env.sample .env
docker network create caddy-net
```

Edit `.env`:

| Variable | Required | Meaning |
|---|---|---|
| `SHADOWSOCKS_PORT` | yes | Shadowsocks inbound, loopback only, not published |
| `SHADOWSOCKS_PASSWORD` | yes | SS-2022 server PSK, exactly 16 bytes: `openssl rand -base64 16` |
| `SHADOWTLS_PORT` | yes | ShadowTLS inbound, published TCP |
| `SHADOWTLS_SNI` | yes | Domain the handshake imitates, e.g. `mozilla.org` |
| `SHADOWTLS_PASSWORD` | yes | Shared handshake password |
| `PUBLIC_IP` | no | Skips auto-detection |
| `APP_HOST` | yes | Public hostname of the API, used in import links and Caddy |
| `APP_ADMIN_PASSWORD` | yes | HTTP Basic password for `/ssm/*`. Unset = every admin request refused |
| `APP_ADMIN_USER` | no | HTTP Basic username, default `admin` |
| `APP_CORS_ORIGINS` | no | Extra browser origins allowed to call the API, comma-separated |
| `APP_DEFAULT_*` | no | Defaults for `/c` query parameters |

The server and ShadowTLS passwords are shared by every client (per-user auth is the Shadowsocks PSK). Generate `SHADOWSOCKS_PASSWORD` with `openssl rand -base64 16` and `SHADOWTLS_PASSWORD` with:

```sh
openssl rand -base64 32
```

`docker compose up` refuses to start sing-box while any of the five required transport values is empty.

Then:

```sh
docker compose pull
docker compose up -d                       # sing-box + API; TLS ingress is the separate caddy-ingress deployment
docker compose logs sing-box | grep entrypoint
```

Expect `configured ports ...` on first start and `public ip x.x.x.x` on every start.

The user store starts empty. Add users with the create form at `/ssm/form`, or import a CSV on the stats page (see [User import](docs/api.md#user-import)). `example-users.csv` shows the format.

To upgrade, run `docker compose pull && docker compose up -d`. One-time migrations and config volume rebuilds: [docs/upgrade.md](docs/upgrade.md).

## Users

User records, Expiry, Mesh key and WARP key: [docs/users.md](docs/users.md). Admin routes, User import and User export: [docs/api.md](docs/api.md).

## Develop

No Docker needed for the fast loop:

```sh
# API
cd api && APP_INTERNAL_DB_PATH=/tmp/users.db uv run --with 'fastapi[standard]' --with httpx --with apscheduler --with sqlmodel --with alembic \
  sh -c 'alembic upgrade head && fastapi dev app/main.py'

# Entrypoint, against a scratch dir with a stubbed sing-box
SING_BOX_ROOT=/path/to/scratch SHADOWSOCKS_PORT=1 SHADOWSOCKS_PASSWORD=$(openssl rand -base64 16) SHADOWTLS_PORT=2 \
  SHADOWTLS_SNI=x SHADOWTLS_PASSWORD=y \
  PUBLIC_IP=1.2.3.4 sh scaffolds/entrypoint.sh

# Tests. SING_BOX is optional; it adds `sing-box check` on the generated Server config.
SING_BOX=/path/to/sing-box sh scaffolds/entrypoint.test.sh
cd api && uv run --with 'fastapi[standard]' --with httpx --with apscheduler --with sqlmodel --with alembic --with pytest pytest -q tests
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
