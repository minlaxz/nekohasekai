# Context: nekohasekai

Single bounded context. Glossary of domain terms as used in this repo.

## Terms

- **Server config** — the sing-box config directory the VPS runs (`server/`). Seeded from the image on first start, then persistent.
- **Client template** — the sing-box outbounds config handed to end users (`client/`). Has server address, ports, and SNI filled in; per-user passwords are filled by the API, not by init.
- **Init** — the container entrypoint. It seeds Server config and Client template into the persistent volume and fills in Deploy values. Each step has its own gate: seeding runs once (`.initialized`); the Shadowsocks port, ShadowTLS port, SNI, and ShadowTLS password are written once (`.configured`); the Hysteria2 transport is set up once (`.hysteria2`), which also upgrades a volume configured before that step existed; Public IP is refreshed on every start.
- **Template refresh** — the every-start step that copies every Client template file except `outbounds.json` from the image (`/defaults`) into the volume. Makes `pull` + `up -d` the whole upgrade path; `outbounds.json` is skipped because it holds Deploy values and the Hysteria2 secrets.
- **Deploy values** — values that differ per VPS: Shadowsocks port, ShadowTLS port, Hysteria2 port, SNI, ShadowTLS password, Hysteria2 password, Salamander password, Public IP. All but Public IP come from `.env`; Public IP is auto-detected, `PUBLIC_IP` overrides. The Hysteria2 certificate also differs per VPS, but it is generated, not a Deploy value.
- **Public IP** — the VPS's internet-facing IPv4 address. Auto-detected on every start (`PUBLIC_IP` overrides), written into the Client template.
- **SNI** — the TLS server name the ShadowTLS handshake imitates. Same value on server (`handshake.server`) and client (`tls.server_name`).
- **Users file** — `users.json` on the host, mounted into the API. Entries are `{name, password, admin}` plus an optional Mesh key. `example-users.json` is its template. Seeded into ssm-api on API startup (add-only); kept in sync by `/ssm/create` and `/ssm/delete`.
- **Managed users** — Shadowsocks users held by the ssm-api service. The only per-user identity; adding or removing one needs no sing-box restart. Also called SSM users in the admin UI. A username is 1–32 characters: letters, digits, `-`, `_`; it must start with a letter or digit. Creating an existing username is a conflict, not a password rotation; rotate by deleting and creating.
- **Admin credential** — the single username/password pair that gates every Managed user operation (create, delete, stats, raw ssm-api proxy). Set per VPS. Without it the admin surface is closed, not open.
- **ShadowTLS password** — one shared handshake secret for all clients. ShadowTLS is transport only; it carries no per-user identity.
- **Hysteria2 transport** — the UDP (QUIC) path to the VPS, obfuscated with Salamander. Transport only, like ShadowTLS: it carries Shadowsocks inside and can reach nothing on the server except the Shadowsocks inbound. The PSK stays the gate, and Managed users stay the only per-user identity. Present on every VPS.
- **Hysteria2 password** and **Salamander password** — two shared secrets for all clients, set in `.env` like the ShadowTLS password and written once by Init. Transport only; they carry no per-user identity.
- **Hysteria2 certificate** — the self-signed certificate for the Hysteria2 transport. Generated once by Init, kept in the volume, never regenerated. The Client template carries it inline as the trust anchor.
- **Profile config** — the full sing-box client config returned by `/c` for one user. Built from the Client template: log, dns, and outbounds are injected per request (query params override `APP_DEFAULT_*`); inbounds, experimental, endpoints, services, and route are served verbatim, except for the User rule set merge into route.
- **User rule set** — a sing-box rule-set source file the user hosts and passes by URL when fetching their Profile config. Only `domain_suffix`, `domain_keyword`, and `domain_regex` are accepted. Fetched and checked on every request; its matchers join the Profile config's proxied-in-Partial-mode list, alongside the admin-curated rule sets (`my-rules`, geosite). Optional, one per request. A bad or unreachable file fails the request rather than being dropped silently.
- **Profile import** — the `/i` page that wraps a Profile config URL in a `sing-box://import-remote-profile` link.
- **PSK** — the user's Shadowsocks password (`k`). Verified against ssm-api before a Profile config is issued. Per-user; the ShadowTLS password is separate and shared.
- **Mesh** — the headscale tailnet that users' devices join. Separate deployment from the VPS; the VPS is not in the mesh path. Mesh addresses are the whole `100.64.0.0/10` range; a device reaches a peer only if that peer is registered.
- **Mesh key** — a per-user, reusable headscale pre-auth key (`ts_auth_key` in the Users file), minted by the admin by hand. Optional: a user with a Mesh key gets a Profile config that joins the Mesh under their username and resolves MagicDNS names (`*.minlaxz.internal`); a user without one gets no Mesh sections at all.
