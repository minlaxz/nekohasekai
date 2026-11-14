# Users

Each user is a User record in the API's store: `name`, `password` (the PSK), `admin`, and optional Expiry, Disabled flag, Mesh key and WARP key. The store is `./data/users.db` on the host; back it up with `cp` or with User export.

Every admin route (create, renew, Expiry, Mesh key, WARP key, disable, enable, delete, User export, User import, stats) is in [api.md](api.md). Everything under `/ssm` needs HTTP Basic (`APP_ADMIN_USER` / `APP_ADMIN_PASSWORD`). Every change made through the dashboard or `/ssm/*` takes effect immediately. No restart needed.

- Import link: `https://<APP_HOST>/i?j=<name>&k=<password>`
- Raw profile: `https://<APP_HOST>/c?j=<name>&k=<password>`
- Help page for end users: `https://<APP_HOST>/help?j=<name>&k=<password>`

## Password, Expiry, Disabled

Passwords must be unique per user; a shared one makes sing-box treat the entries as one user.

Expiry (`expires_at`, ISO 8601, no zone = UTC): past it the user is removed from ssm-api within a minute and can no longer connect or fetch a profile; the record, name and password stay. No Expiry means never. Created users get the months chosen at create plus a 3-day Trial period; `/ssm/renew` pushes it forward.

Disabled: the user is kept out of ssm-api like an expired one, whatever the Expiry; `/ssm/enable` clears it.

## Mesh key

`ts_auth_key`: a reusable headscale pre-auth key for that user. Mint it by hand:

```sh
headscale preauthkeys create --user alice --reusable --expiration 1y
```

A user with a Mesh key gets the `ts-ep` tailscale endpoint (hostname = username, `control_url` from `APP_TS_CONTROL_URL`) and `100.64.0.0/10` routed into it. A user without one gets no endpoint and no such rule. Set, change or clear it in the Keys column of the stats page (Show details), or with `POST /ssm/mesh`. The user's next `/c` fetch joins the Mesh, or leaves it.

## WARP key

`warp_key` and `warp_ipv6`: the `PrivateKey` and the IPv6 `Address` of a Cloudflare WARP account, e.g. from `wgcf register && wgcf generate`.

A user with a WARP key who fetches with a WARP rule set (`r6`) gets the `warp-ep` WireGuard endpoint (dialed through `shadowsocks-uot`, since WireGuard and Cloudflare are blocked locally). DNS answers AAAA queries empty except for the WARP domains listed in that rule set (same format and hosts as `r4`, e.g. `ip6only.me`, `test-ipv6.com`), whose DNS rule sits before the AAAA block (AAAA included); every IPv6 connection (`ip_version: 6`) and all traffic to those domains go to `warp-ep`. Without `r6` or without a key, no endpoint and none of these rules.

Set, change or clear it in the Keys column of the stats page (Show details), or with `POST /ssm/warp`; both or neither. The user's next `/c` fetch uses it.

## Profile DNS

`/c` query parameters are listed in [api.md](api.md#profile-routes); each falls back to its `APP_DEFAULT_*`. DNS answers no AAAA (a `query_type: AAAA` rule returns empty `NOERROR`; sing-box 1.14 deprecates the DNS rule `strategy`), except WARP domains (see WARP key). Proxy server names resolve `ipv4_only` through `route.default_domain_resolver`.
