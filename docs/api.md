# API

Base URL: `https://<APP_HOST>`. Interactive schema: `/docs` (Swagger) and `/openapi.json`.

Two surfaces:

| Surface | Routes | Auth |
|---|---|---|
| Profile | `GET /c`, `GET /i` | per-user: `j` username + `k` PSK |
| Admin | `POST /ssm/create`, `POST /ssm/delete`, `GET /ssm/server/v1/users` | HTTP Basic: `APP_ADMIN_USER` (default `admin`) / `APP_ADMIN_PASSWORD` |

Terms (`CONTEXT.md`): a **Managed user** is one Shadowsocks identity; the **PSK** is their password; the **Admin credential** gates every admin route.

## Admin routes

All admin routes take form-encoded bodies (`application/x-www-form-urlencoded`) and answer in JSON when the request carries `Accept: application/json`. A browser form submit (`Accept: text/html`) gets an HTML page instead. Errors are JSON: `400` (missing or invalid field) is `{"message": "..."}`, everything else is `{"detail": "..."}`.

Without a valid Admin credential every admin route answers `401` with `WWW-Authenticate: Basic`. If `APP_ADMIN_PASSWORD` is unset on the server, the admin surface is closed, not open.

Browser-facing origins other than `https://<APP_HOST>` must be listed in `APP_CORS_ORIGINS` (comma-separated) or the browser blocks the call before it reaches auth.

### Create a Managed user

```
POST /ssm/create
username=<name>
```

`username`: 1 to 32 characters, letters, digits, `-`, `_`; must start with a letter or digit. The PSK is generated server-side.

```sh
curl -u admin:$APP_ADMIN_PASSWORD -H 'Accept: application/json' \
  -d 'username=alice' https://$APP_HOST/ssm/create
```

```json
{
  "username": "alice",
  "uPSK": "k3j9x0q2m8n1p5r7t4w6==",
  "import_url": "https://vpn.example/i?j=alice&k=k3j9x0q2m8n1p5r7t4w6==",
  "config_url": "https://vpn.example/c?j=alice&k=k3j9x0q2m8n1p5r7t4w6=="
}
```

| Status | Meaning |
|---|---|
| 200 | Created. Takes effect immediately, no sing-box restart. |
| 400 | Username fails the rule above. |
| 409 | Username already exists. To rotate a PSK: delete, then create. |
| 502 | ssm-api unreachable. |

Hand `import_url` to the user. Opening it on a device with sing-box installed imports the profile.

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

`{"users": [...]}` sorted by download bytes, descending. Each entry is the ssm-api stats object for one user plus their `uPSK`.

## Profile routes

No admin credential. Identity is the `j`/`k` pair from the create response.

- `GET /c?j=<name>&k=<psk>`: full sing-box client config as JSON. `k` is verified against ssm-api; a wrong pair fails. Optional overrides: `ll` log level, `dh` DoH host or IP, `dn` DoH TLS server name, `dp` DoH path prefix, `dr` resolver IP, `dd` resolver detour, `df` DNS final, `dv` 4 or 6, `mx` multiplex, `r` User rule set URL.
- `GET /i?j=<name>&k=<psk>`: HTML page with a `sing-box://import-remote-profile` link that points at `/c`. `p` and `v` are accepted for old links and ignored.

## Integration flow

1. Admin frontend calls `POST /ssm/create` with the Admin credential.
2. Show or send `import_url` to the end user.
3. The user's sing-box fetches `/c` through that link; nothing else to do.
4. To revoke: `POST /ssm/delete`.

## Not public

`/ssm-transparent/*` raw-proxies the internal ssm-api. It is behind the same Admin credential, hidden from `/docs`, and may change without notice.
