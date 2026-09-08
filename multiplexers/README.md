# multiplexers

Standalone deployment. **Not** the sing-box VPS this repo sets up, and not wired into
the API, scaffolds, or `users.json`. Only thing borrowed is the sing-box config shape.
Runs on its own VPS. (Not a sidecar: a sidecar shares a host/pod with the main service.
This shares nothing.)

What it runs, one `sing-box` container:

- `ccm` on `:4200` — Claude Code multiplexer. Many users, one Claude subscription.
- `ocm` on `:4201` — Codex multiplexer. Same idea, OpenAI.
- `tailscale` endpoint — joins the Mesh (headscale) so users reach `:4200`/`:4201`
  over the tailnet without TLS. Ports are also bound to `127.0.0.1` for ssh tunnels.

## Files

| File | Role |
|---|---|
| `config.json` | sing-box config template. `${MUX_*}` placeholders. |
| `entrypoint.sh` | Fills placeholders from env, `sing-box check`, `sing-box run`. |
| `docker-compose.yaml` | One service, `ghcr.io/sagernet/sing-box:v1.14.0`. |
| `.env.sample` | Copy to `.env`. |
| `data/` | Created on first run. Tailscale state, usage stats. Back this up. |

## Setup (on the mux VPS)

1. Log in once so the credential files exist. Headless: both print a URL + code.
   ```sh
   claude auth login
   codex login
   ```
   Result: `~/.claude/.credentials.json`, `~/.codex/auth.json`. Mounted read-write;
   ccm/ocm refresh tokens in place.
2. Mint a headscale pre-auth key for the mux node.
   ```sh
   headscale preauthkeys create --user <user> --expiration 1h
   ```
3. Env.
   ```sh
   cp .env.sample .env
   ```
   Fill `MUX_TS_*`. One `MUX_USER_<NAME>_TOKEN=` per user; `openssl rand -hex 24`
   for tokens. Any number of users; entrypoint collects every `MUX_USER_*_TOKEN`.
4. Run.
   ```sh
   docker compose up -d && docker compose logs -f
   ```
   Log shows tailscale IP (`100.x.x.x`). After first join, `MUX_TS_AUTH_KEY` may be
   blanked; state lives in `data/tailscale`.

## Add or remove a user

Edit `.env`, then `docker compose up -d --force-recreate`. Restart drops in-flight
requests; nothing else.

## Client

Over the tailnet (device already in the Mesh):

```sh
ANTHROPIC_BASE_URL=http://100.x.x.x:4200 ANTHROPIC_AUTH_TOKEN=<token> claude
```

Over ssh, no Mesh:

```sh
ssh -L 4200:127.0.0.1:4200 -L 4201:127.0.0.1:4201 mux-vps
ANTHROPIC_BASE_URL=http://127.0.0.1:4200 ANTHROPIC_AUTH_TOKEN=<token> claude
```

Codex, in `~/.codex/config.toml`:

```toml
[model_providers.ocm]
name = "OCM Proxy"
base_url = "http://100.x.x.x:4201/v1"
supports_websockets = true
experimental_bearer_token = "<token>"

[profiles.ocm]
model_provider = "ocm"
```

Then `codex --profile ocm`.

## Usage stats

`data/claude-usages.json`, `data/codex-usages.json`. Per model and per user, saved
every minute.

## Notes

- No `tls` on ccm/ocm on purpose: tailnet or loopback only. Never expose `:4200`/`:4201`
  on a public interface without `tls`. See `../docs/concepts/inbound-tls.md`.
- Env values must not contain `|`, `&`, or `"`; entrypoint uses `sed`.
- Route rule `ts-ep -> direct-out, override_address 127.0.0.1` is what makes the
  tailscale IP reach the listeners. sing-box's tailscale is userspace, no TUN.
