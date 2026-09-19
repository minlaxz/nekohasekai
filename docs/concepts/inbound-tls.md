# Why every sing-box inbound has a `tls` block

Applies to: `ccm`, `ssm-api`, `trojan`, `naive`, `vmess`, `vless`, `hysteria2`, `tuic`, `anytls`, `http`, `mixed`. Not every listener has the field: `socks`, `shadowsocks` and `shadowtls` inbounds do not.

See also: [outbound-tls](outbound-tls.md), the client-side half of the same handshake.

## One idea

`tls` on an inbound/service = **encrypt the wire between the client and sing-box**.

It never touches the upstream side. sing-box's own connections to the internet
(Anthropic API for `ccm`, the destination site for a proxy) are governed by
`detour` / outbound config, not by the inbound `tls` block.

```
 client ──── inbound tls{} ────▶ sing-box ──── outbound / detour ────▶ destination
            (your knob)                       (separate config)
```

Rule: **`tls` is mandatory iff the listener is reachable from a network you do not own.**

## Example: `ccm` (Claude Code Multiplexer)

### Without `tls`

```
remote laptop                internet / LAN                 your box (sing-box)         Anthropic
┌──────────────┐   http://box:8080   ┌────────────┐   https://api.anthropic.com  ┌──────────┐
│ claude code  │ ══════════════════▶ │ ccm service│ ════════════════════════════▶│ API      │
│ AUTH_TOKEN=  │  plaintext:         │ users[]    │  OAuth token from            │          │
│ ak-ccm-alice │  - bearer token     │ check      │  ~/.claude/.credentials.json │          │
└──────────────┘  - prompts/code     └────────────┘  (always TLS, not your knob) └──────────┘
                  - responses
        ▲
        │ anyone on path (wifi, ISP, VPS neighbour) reads token → replays it → burns your subscription
```

```json
{
  "type": "ccm",
  "listen": "0.0.0.0",
  "listen_port": 8080,
  "users": [{ "name": "alice", "token": "ak-ccm-alice" }]
}
```

Client:

```sh
ANTHROPIC_BASE_URL=http://box:8080 ANTHROPIC_AUTH_TOKEN=ak-ccm-alice claude
```

Consequences:

- Bearer token, prompts, code, responses all cleartext on the wire.
- Captured token = full Claude usage on your account, no OAuth needed.
- Acceptable only when the wire is already private: localhost, tailscale/Mesh, WireGuard.

### With `tls`

```
remote laptop                internet                       your box (sing-box)         Anthropic
┌──────────────┐  https://box:8443   ┌────────────┐   https://api.anthropic.com  ┌──────────┐
│ claude code  │ ═══[encrypted]════▶ │ tls{} term │ ════════════════════════════▶│ API      │
│ AUTH_TOKEN   │                     │ ccm service│                              │          │
└──────────────┘                     └────────────┘                              └──────────┘
        ▲
        │ on-path sees: SNI "box.example.com" + byte sizes. no token, no prompts.
```

```json
{
  "type": "ccm",
  "listen": "0.0.0.0",
  "listen_port": 8443,
  "users": [{ "name": "alice", "token": "ak-ccm-alice" }],
  "tls": {
    "enabled": true,
    "server_name": "box.example.com",
    "acme": { "domain": "box.example.com", "email": "you@example.com" }
  }
}
```

Client:

```sh
ANTHROPIC_BASE_URL=https://box.example.com:8443 ANTHROPIC_AUTH_TOKEN=ak-ccm-alice claude
```

Consequences:

- Need a domain and a certificate. ACME needs port 80 (HTTP challenge) or 443 (TLS-ALPN challenge) reachable; a `dns01_challenge` needs neither. Or use `certificate_path` / `key_path`.
- Inline `acme` is deprecated in sing-box 1.14.0 and will be removed in 1.16.0; the replacement is `certificate_provider` (since 1.14.0).
- Self-signed cert: Claude Code (Node) rejects it unless `NODE_EXTRA_CA_CERTS` is set.
- Safe on the public internet. Same wire protection as Anthropic's own endpoint.

### Third option: terminate TLS elsewhere

```
remote laptop         internet          edge (Caddy / nginx / tailscale)   sing-box (127.0.0.1)
┌────────────┐  https / wireguard  ┌──────────────┐   plain http, loopback  ┌────────────┐
│ claude code│ ═══[encrypted]════▶ │ TLS ends here│ ───────────────────────▶│ ccm, no tls│
└────────────┘                     └──────────────┘                         └────────────┘
```

No `tls` in sing-box, bind `listen: "127.0.0.1"`. Encryption lives in the layer in front.
A tailscale / WireGuard mesh is this option: the mesh encrypts, so `tls` is redundant.

## Same concept, other inbounds

The wire threat is identical. What differs is *what* leaks and *what the protocol does if TLS is missing*.

| Inbound     | Auth material on wire       | Without `tls`                                      | Notes                                                        |
|-------------|-----------------------------|----------------------------------------------------|--------------------------------------------------------------|
| `ccm`       | bearer token, prompts       | token replay, prompt/code leak                     | HTTP service; TLS optional                                   |
| `ssm-api`   | API key                     | admin API hijack                                   | same shape as `ccm`                                          |
| `trojan`    | SHA224(password) in header  | password hash replay + all traffic cleartext        | protocol *designed* to look like HTTPS; `tls` effectively required, no `tls` = not trojan anymore |
| `naive`     | user:pass (HTTP basic)      | credentials cleartext; real naive clients cannot connect | naive is HTTP/2 CONNECT over TLS. sing-box only *rejects* a missing `tls` for the QUIC network; over TCP it starts, for use behind a TLS-terminating front |
| `vmess`     | none plain (UUID never sent; header AEAD only with `alter_id: 0`) | fingerprintable; payload is cleartext if the client chose `security: none` or `zero` | `tls` optional, recommended. vmess encrypts the payload only when the client's `security` says so |
| `vless`     | UUID in clear               | UUID replay + all traffic cleartext                | no built-in encryption; needs `tls` or `reality`             |
| `hysteria2` | password                    | not runnable                                        | QUIC = TLS 1.3 by design; `tls` mandatory                    |
| `tuic`      | uuid + password             | not runnable                                        | QUIC; `tls` mandatory                                        |
| `anytls`    | password                    | password + traffic cleartext                        | TLS is the protocol by design. The inbound docs do not mark `tls` Required (the *outbound* does), so sing-box starts without it; only sane behind a TLS-terminating front |
| `shadowsocks` | none (AEAD cipher)        | fine                                                | encrypts itself; no `tls` field at all                       |
| `http` / `mixed` | user:pass              | credentials + traffic cleartext                    | LAN / loopback only without `tls`. The `mixed` docs page omits the field, but the source accepts it (shared options struct with `http`) |
| `socks`     | user:pass                   | credentials + traffic cleartext                    | no `tls` field at all; LAN / loopback only                   |

Three buckets:

```
                 ┌───────────────────────────┐
  tls optional   │ ccm  ssm-api  vmess  http │  runs without it; unsafe outside private nets
                 │ mixed                     │
                 ├───────────────────────────┤
  tls required   │ hysteria  hysteria2  tuic │  docs mark ==Required==; QUIC cannot run without it
  by sing-box    │                           │
                 ├───────────────────────────┤
  tls required   │ trojan  naive  anytls     │  sing-box starts without it, but the protocol
  by the protocol│ (vless+tls)               │  assumes TLS: clients fail or everything leaks
                 ├───────────────────────────┤
  no tls field   │ shadowsocks  socks        │  own crypto (shadowsocks) or none (socks)
                 │ shadowtls    wireguard    │
                 └───────────────────────────┘
```

## Inbound fields at a glance

| Field | Since | Meaning |
|---|---|---|
| `enabled`, `server_name`, `alpn`, `min_version`, `max_version`, `cipher_suites` | - | same meaning as on the client side |
| `certificate`(`_path`), `key`(`_path`) | - | the cert and private key this server presents; `*_path` files are reloaded when modified |
| `curve_preferences` | 1.13.0 | allowed key exchanges |
| `client_authentication` | 1.13.0 | mutual TLS: `no` (default), `request`, `require-any`, `verify-if-given`, `require-and-verify` |
| `client_certificate`(`_path`), `client_certificate_public_key_sha256` | 1.13.0 | which client certs to accept; one is required for the two `verify` modes |
| `kernel_tx` / `kernel_rx` | 1.13.0 | kernel TLS, Linux 5.1+, TLS 1.3 only; docs advise against `kernel_rx` |
| `handshake_timeout` | 1.14.0 | default `15s` |
| `certificate_provider` | 1.14.0 | tag of a shared certificate provider, or an inline one; replaces `acme` |
| `acme` | deprecated 1.14.0 | removal planned for 1.16.0 |
| `ech` | - | server side holds `key` / `key_path` |
| `reality` | - | server side holds `handshake`, `private_key`, `short_id[]`, `max_time_difference` |

Client-only fields (`insecure`, `utls`, `disable_sni`, ...) are in [outbound-tls](outbound-tls.md).

## Decision

```
Is the listener reachable from a network you don't own?
├─ no  (127.0.0.1, tailscale, wireguard)  → omit tls
└─ yes
   ├─ something in front terminates TLS (Caddy, nginx, CDN) → omit tls, bind 127.0.0.1
   └─ sing-box is the edge                                   → tls.enabled = true
        ├─ have domain, port 80/443 open → certificate_provider (1.14.0+), acme before that
        └─ otherwise                     → certificate_path + key_path
```

## References

- CCM service: https://sing-box.sagernet.org/configuration/service/ccm/
- Shared TLS fields: https://sing-box.sagernet.org/configuration/shared/tls/
- Listen fields: https://sing-box.sagernet.org/configuration/shared/listen/
- Certificate provider (since 1.14.0): https://sing-box.sagernet.org/configuration/shared/certificate-provider/
- Inbound pages (per-protocol `tls` and Required markers): https://sing-box.sagernet.org/configuration/inbound/
- Source, which inbounds embed TLS options (`socks` does not, `mixed` does): https://github.com/SagerNet/sing-box/blob/testing/option/simple.go
- Trojan protocol (`hex(SHA224(password))`): https://trojan-gfw.github.io/trojan/protocol
