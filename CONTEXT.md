# Context: nekohasekai

Single bounded context. Glossary of domain terms as used in this repo. Mechanics live in `docs/` and `docs/adr/`.

## Deployment

- **Server config** — the sing-box config directory the VPS runs (`server/`). Seeded from the image on first start, then persistent.
- **Client template** — the sing-box client config directory (`client/`) that every Profile config is built from. Init fills in Deploy values; per-user values are filled by the API.
- **Init** — the container entrypoint. Seeds Server config and Client template into the volume and writes Deploy values once; Public IP is refreshed on every start.
- **Template refresh** — the every-start step of Init that copies every Client template file except `outbounds.json` from the image into the volume, so routine upgrades need only `pull` + `up -d` (`docs/upgrade.md`).
- **Deploy values** — values that differ per VPS: Shadowsocks port, Server PSK, ShadowTLS port, SNI, ShadowTLS password, Public IP. All but Public IP come from `.env`.
- **Public IP** — the VPS's internet-facing IPv4 address. Auto-detected on every start; `PUBLIC_IP` overrides.

## Transport

- **Transport** — the way a client reaches the VPS: ShadowTLS over TCP, carrying Shadowsocks for both TCP and UDP. Holds only shared secrets, never a per-user identity. Shadowsocks is never exposed on the internet by itself.
- **SNI** — the TLS server name the ShadowTLS handshake imitates. Same value on server (`handshake.server`) and client (`tls.server_name`).
- **ShadowTLS password** — the one handshake secret shared by all clients.
- **Server PSK** — the SS-2022 identity PSK of the Shadowsocks inbound (`SHADOWSOCKS_PASSWORD`, 16 bytes). Shared by all clients; not the user's PSK.
- **Shadowsocks UOT** — the `shadowsocks-uot` outbound: Shadowsocks over ShadowTLS with UDP-over-TCP.
- **All Outbounds** — the client URL-test group over `direct` and `shadowsocks-uot`. Either may win, so it does not guarantee traffic goes through the proxy.
- **Remote DNS Detour** — the client selector for reaching the remote DNS service, over `direct` and `shadowsocks-uot`. Defaults to `direct`.
- **Hysteria2 transport** — retired UDP (QUIC) Transport, with its own shared passwords and a self-signed certificate. Kept in docs for a possible return (ADR 0001, ADR 0005, issue #65).

## Users

- **Managed user** — one Shadowsocks identity held by ssm-api; the only per-user identity. Called SSM user in the admin UI. Added or removed with no sing-box restart.
- **User record** — one Managed user's entry in the API's store: name, PSK, admin flag, and optional Mesh key, WARP key, Expiry, Disabled flag, Last fetch. The store is the source of truth; the API mirrors it into ssm-api (ADR 0003, ADR 0006).
- **Users file** — retired. `users.json`, the store of User records before ADR 0006.
- **User import** — the admin adding User records from CSV. Add-only and all-or-nothing (`docs/api.md`).
- **User export** — the admin downloading every User record as CSV in the User import shape. Holds every secret in plain text; treat it like `.env`.
- **Admin credential** — the single username/password pair that gates every admin route. Unset means the admin surface is closed, not open.
- **PSK** — the user's Shadowsocks password (`k`): 20 base64 characters plus `==`. Must be unique: SS-2022 identifies a user by key, so two Managed users with one PSK are one user to sing-box (last name wins, stats merge, Expiry on one does nothing).
- **SSM key** — the SS-2022 user key ssm-api holds, derived from the PSK by the API, never stored (ADR 0002).
- **Client key** — the 16-byte key a Profile config carries, derived from the SSM key; written as `<Server PSK>:<Client key>` (ADR 0002).
- **Expiry** — the UTC instant after which a Managed user may no longer connect. None means never.
- **Trial period** — the 3 days added on top of the months chosen at create. 0 months means Trial period only.
- **Renewal** — pushing Expiry forward by whole months, with no Trial period. Does not enable a Disabled user.
- **Expired user** — a Managed user past Expiry: out of ssm-api, cannot connect, `/c` refuses them. User record and PSK are kept, so Renewal brings them back with no re-import. Expiry gates Shadowsocks only: a Mesh key stays valid.
- **Disabled user** — a Managed user switched off by the admin. Same effect as Expired, independent of Expiry: back only when neither holds.
- **Deleted user** — a Managed user removed from ssm-api and from the store. Permanent: a re-create issues a new PSK that devices must re-import.
- **Last fetch** — the last time `/c` delivered a user's Profile config. Not a measure of activity: clients re-fetch only on their own update interval.

## Profile

- **Profile config** — the full sing-box client config `/c` returns for one user, built from the Client template plus per-user values.
- **Profile import** — the `/i` page that wraps a Profile config URL in a `sing-box://import-remote-profile` link.
- **Help page** — the `/help` page listing every Profile config query param and its default. Visible only with a valid `j`/`k`.
- **User rule set** — a rule-set file the user hosts and passes by URL (`r4`); its domains are proxied in Partial mode.
- **User IP list** — single IPv4 addresses the user passes (`rr.ip_cidr`), proxied in Partial mode. Earlier route rules still win: an address in Myanmar stays direct.
- **Mesh** — the headscale tailnet users' devices join. A separate deployment; the VPS is not in the Mesh path.
- **Mesh key** — a per-user headscale pre-auth key. Optional: with one, the Profile config joins the Mesh; without one, no Mesh sections (`docs/users.md`).
- **WARP key** — a per-user Cloudflare WARP private key plus its IPv6 address, both or neither. Optional (`docs/users.md`).
- **WARP rule set** — a rule-set file passed by URL (`r6`) listing WARP domains. Turns WARP on only for a user with a WARP key; otherwise ignored.
