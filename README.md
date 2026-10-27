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

The user store starts empty. Add users with the create form at `/ssm/form`, or import a CSV on the stats page (see [User import](#user-import)). `example-users.csv` shows the format.

### Upgrade

```sh
docker compose pull && docker compose up -d
```

For deployments already using only ShadowTLS, that is the whole upgrade path. The image carries the configs: every start copies the client template (`route.json`, `dns.json`, `inbounds.json`, ...) from the image into the volume, so rule and DNS changes land without touching it. `client/outbounds.json`, `server/`, and `cache/` persist; outbounds the image adds (new tags) are appended to `outbounds.json` on start, existing entries stay as they are.

`git pull` on the server is only needed when `docker-compose.yaml` changes or `.env` gains a new variable.

**Moving from `users.json` to the user store ([ADR 0006](docs/adr/0006-sqlite-user-store-csv-import.md)):** the API no longer reads `users.json`. Convert it once, then import it:

```sh
git pull                                   # new docker-compose.yaml: mounts ./data, drops users.json
python3 scripts/users_json_to_csv.py users.json > users.csv
docker compose pull && docker compose up -d
```

Open the stats page `https://<APP_HOST>/ssm/server/v1/users`, choose `users.csv` under Import users and submit. If any row is bad, nothing is added and the response lists each `row N: reason`. Fix those rows in `users.csv` and import again. Until the import, existing users keep connecting (ssm-api still holds them), but `/c` serves them no Mesh, WARP or Full mode. After a good import, delete `users.json` and `users.csv`: both hold every PSK in plain text.

**Retiring Hysteria2 from an existing deployment:** use the updated Compose file and rebuild the config volume once after pulling images that include the retirement:

```sh
git pull
docker compose pull
docker compose down -v
docker compose up -d
```

This resets generated configs, cached users, and traffic counters. The host's `.env` and `./data/` survive; the API restores every user in its store, but users held only in the old cache are lost. Keep the same ShadowTLS and Shadowsocks values in `.env`. Remove the unused `HYSTERIA2_*` values and close the old UDP port in the VPS firewall. Clients pinned to Hysteria2 must switch to ShadowTLS or refresh their profile. Without the volume rebuild, persistent server and client configs retain the old transport entries.

Hysteria2 was retired because the operator observed delayed or failed connections when first opening the VPN and lower stability than ShadowTLS. The cause is still unknown; follow-up is tracked in [issue #65](https://github.com/minlaxz/nekohasekai/issues/65). All Hysteria2 docs and research are retained, including the [previous deployment instructions](docs/research/hysteria2-deployment-before-retirement.md), for a possible return later.

**Outbound naming cleanup ([issue #67](https://github.com/minlaxz/nekohasekai/issues/67)):** set `APP_DEFAULT_DNS_DETOUR=shadowsocks-uot` in the existing `.env`, and change any profile URL using `dd=Proxy` to `dd=shadowsocks-uot`. The `Proxy` group is removed and `All` is now `All Outbounds`. Rebuild the config volume with the procedure above, then refresh cached client profiles. If deploying both the Hysteria2 retirement and naming cleanup together, rebuild once using images containing both changes. Init only appends outbound tags to existing volumes; without the rebuild, the old groups and Remote DNS Detour options remain.

Ports, SNI, the Server PSK, and the ShadowTLS password are written once. To change them, remove the volume:

```sh
docker compose down && docker volume rm sing-box_sing-box-configs && docker compose up -d
```

## Users

Each user is a User record in the API's store: `name`, `password` (the PSK), `admin`, and optional Expiry, Disabled flag, Mesh key and WARP key. The store is `./data/users.db` on the host; back it up with `cp` or with User export.

Passwords must be unique per user; a shared one makes sing-box treat the entries as one user. Expiry (`expires_at`, ISO 8601, no zone = UTC): past it the user is removed from ssm-api within a minute and can no longer connect or fetch a profile; the record, name and password stay. No Expiry means never. Created users get the months chosen at create plus a 3-day Trial period; `/ssm/renew` pushes it forward. Disabled: the user is kept out of ssm-api like an expired one, whatever the Expiry; `/ssm/enable` clears it.

Mesh key (`ts_auth_key`): a reusable headscale pre-auth key for that user. Mint it by hand:

```sh
headscale preauthkeys create --user alice --reusable --expiration 1y
```

A user with a Mesh key gets the `ts-ep` tailscale endpoint (hostname = username, `control_url` from `APP_TS_CONTROL_URL`) and `100.64.0.0/10` routed into it. A user without one gets no endpoint and no such rule.

WARP key (`warp_key` and `warp_ipv6`): the `PrivateKey` and the IPv6 `Address` of a Cloudflare WARP account, e.g. from `wgcf register && wgcf generate`. A user with a WARP key who fetches with `dv=6` gets the `warp-ep` WireGuard endpoint (dialed through `shadowsocks-uot`, since WireGuard and Cloudflare are blocked locally). DNS stays `ipv4_only` except for the WARP domains listed in the rule set at `r6` (same format and hosts as `r`, e.g. `ip6only.me`, `test-ipv6.com`), which a DNS rule answers with `prefer_ipv4` (AAAA included); every IPv6 connection (`ip_version: 6`) and all traffic to those domains go to `warp-ep`. Without `dv=6` or without a key, no endpoint and none of these rules.

Mesh keys and WARP keys have no dashboard form yet. To set them, export, add them to the CSV row, delete the user, and import that row.

- Import link: `https://<APP_HOST>/i?j=<name>&k=<password>`
- Raw profile: `https://<APP_HOST>/c?j=<name>&k=<password>`
- Create: form at `/ssm/form`, or `POST /ssm/create` with form fields `username` and optional `months` 0 to 6 (409 if it exists)
- Renew: `POST /ssm/renew` with `username` and `months` 1 to 6 (404 if unknown)
- Set or clear Expiry: per-row form on the stats page, or `POST /ssm/expiry` with `username` and `expires_at` (ISO 8601, empty = never)
- Disable / enable: per-row button on the stats page, or `POST /ssm/disable` / `POST /ssm/enable` with `username` (404 if the user has no User record)
- Delete: per-row button on the stats page, or `POST /ssm/delete` with form field `username` (404 if unknown). Admin entries cannot be disabled or deleted (403).
- Export / import: see below
- Stats: `/ssm/server/v1/users`

Everything under `/ssm` needs HTTP Basic (`APP_ADMIN_USER` / `APP_ADMIN_PASSWORD`). Full reference for integrating a frontend: [docs/api.md](docs/api.md). End users: `/help?j=<name>&k=<psk>`.

Every change made through the dashboard or `/ssm/*` takes effect immediately. No restart needed.

### User export

"Export users (CSV)" on the stats page, or `GET /ssm/export`, downloads every User record as `users.csv`:

```csv
name,password,admin,expires_at,disabled,ts_auth_key,warp_key,warp_ipv6
alice,k3j9x0q2m8n1p5r7t4w6==,false,2026-10-08T12:00:00+00:00,false,,,
```

`admin` and `disabled` are `true` or `false`; an empty cell means not set. Last fetch is not exported. The file holds every PSK, Mesh key and WARP key in plain text: keep it like `.env`.

### User import

"Import users" on the stats page, or `POST /ssm/import` with the file as multipart field `file`, adds the users in a CSV of the export shape (`example-users.csv` is one). Import only adds; it never changes or deletes a user. It is all-or-nothing: every row is checked first. If any row is bad, nothing is added and every problem is reported as `row N: reason` (the header is row 1). A row is bad when:

- a column is unknown or missing, or the row has the wrong number of cells
- the name is not a valid username, or the PSK is not 20 base64 characters plus `==`
- `expires_at` is not ISO 8601, or `admin` / `disabled` is not `true`, `false` or empty
- the name or PSK repeats an earlier row, or already exists in the store

On success, live users are in ssm-api before the response returns; Expired and Disabled users stay out. To change an existing user through import, delete them first.

`/c` query parameters (each falls back to its `APP_DEFAULT_*`): `ll` log level, `dh` DoH host or IP, `dn` DoH TLS server name (when `dh` is an IP), `dp` DoH path prefix (username is appended), `dr` resolver IP, `dd` resolver detour, `df` DNS final, `dv` 4 or 6 (6 turns on WARP for users with a WARP key; DNS stays `ipv4_only` either way).

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
