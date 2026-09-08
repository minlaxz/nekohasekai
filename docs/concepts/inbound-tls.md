# Why every sing-box inbound has a `tls` block

Applies to: `ccm`, `ssm-api`, `trojan`, `naive`, `vmess`, `vless`, `hysteria2`, `tuic`, `anytls`, `http`, `mixed`, and any other listener.

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

- Need a domain and a certificate. ACME needs port 80/443 reachable, or use `certificate_path` / `key_path`.
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
This repo's Mesh (`ts_auth_key`) is this option: tailscale encrypts, so `tls` is redundant.

## Same concept, other inbounds

The wire threat is identical. What differs is *what* leaks and *what the protocol does if TLS is missing*.

| Inbound     | Auth material on wire       | Without `tls`                                      | Notes                                                        |
|-------------|-----------------------------|----------------------------------------------------|--------------------------------------------------------------|
| `ccm`       | bearer token, prompts       | token replay, prompt/code leak                     | HTTP service; TLS optional                                   |
| `ssm-api`   | API key                     | admin API hijack                                   | same shape as `ccm`                                          |
| `trojan`    | SHA224(password) in header  | password hash replay + all traffic cleartext        | protocol *designed* to look like HTTPS; `tls` effectively required, no `tls` = not trojan anymore |
| `naive`     | user:pass (HTTP basic)      | not runnable                                        | naive is HTTP/2 CONNECT over TLS; `tls` mandatory            |
| `vmess`     | none plain (AEAD encrypted) | payload still encrypted by vmess itself, but fingerprintable | `tls` optional, recommended                        |
| `vless`     | UUID in clear               | UUID replay + all traffic cleartext                | no built-in encryption; needs `tls` or `reality`             |
| `hysteria2` | password                    | not runnable                                        | QUIC = TLS 1.3 by design; `tls` mandatory                    |
| `tuic`      | uuid + password             | not runnable                                        | QUIC; `tls` mandatory                                        |
| `anytls`    | password                    | not runnable                                        | TLS is the protocol; `tls` mandatory                         |
| `shadowsocks` | none (AEAD cipher)        | fine                                                | encrypts itself; no `tls` field at all                       |
| `http` / `mixed` / `socks` | user:pass    | credentials + traffic cleartext                    | LAN / loopback only without `tls`                            |

Three buckets:

```
                 ┌───────────────────────────┐
  tls optional   │ ccm  ssm-api  vmess  http │  runs without it; unsafe outside private nets
                 ├───────────────────────────┤
  tls mandatory  │ trojan naive hysteria2    │  protocol *is* TLS; config rejected or broken without it
                 │ tuic anytls  (vless+tls)  │
                 ├───────────────────────────┤
  no tls field   │ shadowsocks  wireguard    │  brings own crypto; add TLS only for camouflage
                 └───────────────────────────┘
```

## Decision

```
Is the listener reachable from a network you don't own?
├─ no  (127.0.0.1, tailscale, wireguard)  → omit tls
└─ yes
   ├─ something in front terminates TLS (Caddy, nginx, CDN) → omit tls, bind 127.0.0.1
   └─ sing-box is the edge                                   → tls.enabled = true
        ├─ have domain, port 80/443 open → acme
        └─ otherwise                     → certificate_path + key_path
```

## References

- CCM service: https://sing-box.sagernet.org/configuration/service/ccm/
- Shared TLS fields: https://sing-box.sagernet.org/configuration/shared/tls/
- Listen fields: https://sing-box.sagernet.org/configuration/shared/listen/
