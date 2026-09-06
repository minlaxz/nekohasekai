# Context: nekohasekai

Single bounded context. Glossary of domain terms as used in this repo.

## Terms

- **Server config** — the sing-box config directory the VPS runs (`server/`). Seeded from the image on first start, then persistent.
- **Client template** — the sing-box outbounds config handed to end users (`client/`). Has server address, ports, and SNI filled in; per-user passwords are filled by the API, not by init.
- **Init** — the one-time step on first container start that seeds Server config and Client template into the persistent volume and fills in deploy-specific values. Seeding runs once (`.initialized`); ports, SNI, and the ShadowTLS password are written once (`.configured`); Public IP is refreshed on every start.
- **Deploy values** — values that differ per VPS: Shadowsocks port, ShadowTLS port, SNI, ShadowTLS password, Public IP. All but Public IP come from `.env`; Public IP is auto-detected, `PUBLIC_IP` overrides.
- **Public IP** — the VPS's internet-facing IPv4 address. Auto-detected on every start (`PUBLIC_IP` overrides), written into the Client template.
- **SNI** — the TLS server name the ShadowTLS handshake imitates. Same value on server (`handshake.server`) and client (`tls.server_name`).
- **Users file** — `users.json` on the host, mounted into the API. Entries are `{name, password, admin}`. `example-users.json` is its template. Seeded into ssm-api on API startup (add-only); kept in sync by `/ssm/create` and `/ssm/delete`.
- **Managed users** — Shadowsocks users held by the ssm-api service. The only per-user identity; adding or removing one needs no sing-box restart.
- **ShadowTLS password** — one shared handshake secret for all clients. ShadowTLS is transport only; it carries no per-user identity.
- **Profile config** — the full sing-box client config returned by `/c` for one user. Built from the Client template: log, dns, and outbounds are injected per request (query params override `APP_DEFAULT_*`); inbounds, experimental, endpoints, services, and route are served verbatim.
- **Profile import** — the `/i` page that wraps a Profile config URL in a `sing-box://import-remote-profile` link.
- **PSK** — the user's Shadowsocks password (`k`). Verified against ssm-api before a Profile config is issued; the same value is the ShadowTLS password.
