# API

Base URL: `https://<APP_HOST>`. Interactive schema: `/docs` (Swagger) and `/openapi.json`.

Two surfaces:

| Surface | Routes | Auth |
|---|---|---|
| Profile | `GET /c`, `GET /i` | per-user: `j` username + `k` PSK |
| Admin | `POST /ssm/create`, `POST /ssm/renew`, `POST /ssm/expiry`, `POST /ssm/delete`, `GET /ssm/server/v1/users` | HTTP Basic: `APP_ADMIN_USER` (default `admin`) / `APP_ADMIN_PASSWORD` |

Terms (`CONTEXT.md`): a **Managed user** is one Shadowsocks identity; the **PSK** is their password; the **Admin credential** gates every admin route. The PSK is what users hold and what `k` carries; ssm-api itself holds the derived **SSM key** (so the raw ssm-api proxy and stats show `uPSK` in that form, not `k`). **Expiry** is when access ends, enforced by the API within a minute (ADR 0003).

## Admin routes

All admin routes take form-encoded bodies (`application/x-www-form-urlencoded`) and answer in JSON when the request carries `Accept: application/json`. A browser form submit (`Accept: text/html`) gets an HTML page instead. Errors are JSON: `400` (missing or invalid field) is `{"message": "..."}`, everything else is `{"detail": "..."}`.

Without a valid Admin credential every admin route answers `401` with `WWW-Authenticate: Basic`. If `APP_ADMIN_PASSWORD` is unset on the server, the admin surface is closed, not open.

Browser-facing origins other than `https://<APP_HOST>` must be listed in `APP_CORS_ORIGINS` (comma-separated) or the browser blocks the call before it reaches auth.

### Create a Managed user

```
POST /ssm/create
username=<name>
months=<0..6>        # optional, default 0
```

`username`: 1 to 32 characters, letters, digits, `-`, `_`; must start with a letter or digit. The PSK is generated server-side. `months`: whole calendar months of access; the 3-day Trial period is added on top, so `0` is trial only. `expires_at` is ISO 8601, UTC.

```sh
curl -u admin:$APP_ADMIN_PASSWORD -H 'Accept: application/json' \
  -d 'username=alice' https://$APP_HOST/ssm/create
```

```json
{
  "username": "alice",
  "uPSK": "k3j9x0q2m8n1p5r7t4w6==",
  "expires_at": "2026-10-08T12:00:00+00:00",
  "import_url": "https://vpn.example/i?j=alice&k=k3j9x0q2m8n1p5r7t4w6==",
  "config_url": "https://vpn.example/c?j=alice&k=k3j9x0q2m8n1p5r7t4w6=="
}
```

| Status | Meaning |
|---|---|
| 200 | Created. Takes effect immediately, no sing-box restart. |
| 400 | Username fails the rule above, or `months` outside 0 to 6. |
| 409 | Username already exists. To rotate a PSK: delete, then create. |
| 502 | ssm-api unreachable. |

Hand `import_url` to the user. Opening it on a device with sing-box installed imports the profile.

### Renew a Managed user

```
POST /ssm/renew
username=<name>
months=<1..6>
```

```sh
curl -u admin:$APP_ADMIN_PASSWORD -H 'Accept: application/json' \
  -d 'username=alice' -d 'months=1' https://$APP_HOST/ssm/renew
```

`200 {"username": "alice", "expires_at": "..."}`. Expiry moves forward by `months` calendar months from the current Expiry, or from now if the user is already expired or has none. No Trial period. An Expired user is back in ssm-api before the response returns, with the same PSK, so devices reconnect without re-importing. `400` bad `months`, `404` if the name is not in `users.json`.

### Set a Managed user's Expiry

```
POST /ssm/expiry
username=<name>
expires_at=<ISO 8601 | empty>
```

```sh
curl -u admin:$APP_ADMIN_PASSWORD -H 'Accept: application/json' \
  -d 'username=alice' -d 'expires_at=2026-12-31T00:00' https://$APP_HOST/ssm/expiry
```

`200 {"username": "alice", "expires_at": "2026-12-31T00:00:00+00:00"}`. Sets the exact Expiry; no zone means UTC. Empty `expires_at` removes it (`"expires_at": null`, never expires). Applied before the response returns: a past instant removes the user from ssm-api, a future one or empty puts them back with the same PSK. A browser form submit (the stats page has one per row) is answered with `303` to `/ssm/server/v1/users`. `400` unparsable value, `404` if the name is not in `users.json`.

### Delete a Managed user

```
POST /ssm/delete
username=<name>
```

```sh
curl -u admin:$APP_ADMIN_PASSWORD -H 'Accept: application/json' \
  -d 'username=alice' https://$APP_HOST/ssm/delete
```

`200 {"deleted": "alice"}`, or `404` if the name is unknown.

### Traffic stats

```
GET /ssm/server/v1/users
```

`{"users": [...]}` sorted by download bytes, descending. Each entry is the ssm-api stats object for one user plus their `uPSK`, `expires_at` (`null` = never) and `expired`. The HTML table has a per-row form that posts to `/ssm/expiry`. Expired users are no longer in ssm-api, so they are appended from `users.json` with `expired: true` and no traffic fields.

## Profile routes

No admin credential. Identity is the `j`/`k` pair from the create response.

- `GET /c?j=<name>&k=<psk>`: full sing-box client config as JSON. `k` is verified against ssm-api; a wrong pair fails. Optional overrides: `ll` log level, `dh` DoH host or IP, `dn` DoH TLS server name, `dp` DoH path prefix, `dr` resolver IP, `dd` resolver detour, `df` DNS final, `dv` 4 or 6, `r` User rule set URL, `rd` outbound tag the remote rule sets are downloaded through (default `Proxy`; use `direct` when the proxy stream dies mid-download).
- `GET /i?j=<name>&k=<psk>`: HTML page with a `sing-box://import-remote-profile` link that points at `/c`. `p` and `v` are accepted for old links and ignored.

## Integration flow

1. Admin frontend calls `POST /ssm/create` with the Admin credential.
2. Show or send `import_url` to the end user.
3. The user's sing-box fetches `/c` through that link; nothing else to do.
4. Access ends at `expires_at` on its own; the user keeps the same link. To extend by months: `POST /ssm/renew`; to set an exact date or clear it: `POST /ssm/expiry`.
5. To revoke for good: `POST /ssm/delete`.

## Not public

`/ssm-transparent/*` raw-proxies the internal ssm-api. It is behind the same Admin credential, hidden from `/docs`, and may change without notice.
