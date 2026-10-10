# nekohasekai

Self-hosted [sing-box](https://github.com/SagerNet/sing-box) server plus a small API that hands out per-user client profiles. Built to get around Myanmar internet restrictions. Clients reach it through two Transports, ShadowTLS v3 (TCP) and Hysteria2 (UDP), each carrying Shadowsocks for both TCP and UDP. Shadowsocks itself is never exposed on the internet.

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

## Users

`users.json`:

```json
{ "users": [ { "name": "alice", "password": "20-random-chars==", "admin": false, "expires_at": "2026-10-08T12:00:00+00:00" } ] }
```

Passwords must be unique per user; a shared one makes sing-box treat the entries as one user, and the API logs `duplicate PSK shared by [...]` every minute until fixed. Optional `expires_at` (Expiry, ISO 8601 UTC): past it the user is removed from ssm-api within a minute and can no longer connect or fetch a profile; the entry, name and password stay. No `expires_at` means never. Created users get the months chosen at create plus a 3-day Trial period; `/ssm/renew` pushes it forward. Optional `disabled: true`: the user is kept out of ssm-api like an expired one, whatever the Expiry; `/ssm/enable` clears it.

Optional `ts_auth_key` (Mesh key): a reusable headscale pre-auth key for that user. Mint it by hand:

```sh
headscale preauthkeys create --user alice --reusable --expiration 1y
```

A user with a Mesh key gets the `ts-ep` tailscale endpoint (hostname = username, `control_url` from `APP_TS_CONTROL_URL`) and `100.64.0.0/10` routed into it. A user without one gets no endpoint and no such rule.

- Import link: `https://<APP_HOST>/i?j=<name>&k=<password>`
- Raw profile: `https://<APP_HOST>/c?j=<name>&k=<password>`
- Create: form at `/ssm/form`, or `POST /ssm/create` with form fields `username` and optional `months` 0 to 6 (409 if it exists)
- Renew: `POST /ssm/renew` with `username` and `months` 1 to 6 (404 if unknown)
- Set or clear Expiry: per-row form on the stats page, or `POST /ssm/expiry` with `username` and `expires_at` (ISO 8601 UTC, empty = never)
- Disable / enable: per-row button on the stats page, or `POST /ssm/disable` / `POST /ssm/enable` with `username` (404 if not in `users.json`)
- Delete: per-row button on the stats page, or `POST /ssm/delete` with form field `username` (404 if unknown). Admin entries cannot be disabled or deleted (403).
- Stats: `/ssm/server/v1/users`

Everything under `/ssm` needs HTTP Basic (`APP_ADMIN_USER` / `APP_ADMIN_PASSWORD`). Full reference for integrating a frontend: [docs/api.md](docs/api.md), or `/docs` on a running instance.

Changes made through `/ssm/create`, `/ssm/renew`, `/ssm/expiry`, `/ssm/disable`, `/ssm/enable` and `/ssm/delete` take effect immediately. No restart needed.

Editing `users.json` by hand is picked up at API startup and by the minute sweep, but only for a file edited in place: most editors replace the file, and the container keeps the old one (see below). The sweep adds live users and removes expired ones; it never deletes ssm-api users the file does not know and never changes a password. Don't use `down -v`: it wipes the volume (traffic stats, ssm cache).

| Hand edit | Apply with |
|---|---|
| Added user | `docker compose up -d --force-recreate sing-box-api` |
| Changed `expires_at` | prefer the stats page form or `/ssm/expiry`; by hand, the recreate above |
| Changed password | `docker compose exec sing-box wget -qO- --method=DELETE http://127.0.0.1:8888/server/v1/users/<name>`, then the recreate above |
| Removed user | `docker compose exec sing-box wget -qO- --method=DELETE http://127.0.0.1:8888/server/v1/users/<name>` |

`--force-recreate` (not `restart`) because editors replace the file, and a running container keeps the old single-file bind mount.

`/c` query parameters (each falls back to its `APP_DEFAULT_*`): `ll` log level, `dh` DoH host or IP, `dn` DoH TLS server name (when `dh` is an IP), `dp` DoH path prefix (username is appended), `dr` resolver IP, `dd` resolver detour, `df` DNS final, `dv` 4 or 6.

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
