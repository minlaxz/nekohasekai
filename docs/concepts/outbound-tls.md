# What the `tls` block on a sing-box outbound does

Applies to: `trojan`, `vless`, `vmess`, `http`, `naive`, `anytls`, `shadowtls`, `hysteria`, `hysteria2`, `tuic` outbounds, and the `tls` / `https` / `quic` / `h3` DNS servers.

Versions: checked against sing-box 1.14 docs and source. Fields newer than 1.10 carry a "since" marker below.

See also: [inbound-tls](inbound-tls.md), the server-side half of the same handshake.

## One idea

`tls` on an outbound = **sing-box is the TLS client**. It does two jobs:

1. **Verify the server**: is the box on the other end really who I meant to reach?
2. **Shape the ClientHello**: what does my first packet look like to someone watching the wire?

An inbound `tls` block is the opposite role: sing-box is the TLS *server* and presents a certificate.

```
            outbound tls{}                          inbound tls{}
            (TLS client)                            (TLS server)
 ┌────────────┐   ClientHello: SNI, ALPN, ...    ┌────────────┐
 │ sing-box   │ ────────────────────────────────▶│ sing-box   │
 │ (your side)│ ◀──────────────────────────────── │ (far side) │
 └────────────┘   certificate + proof of key     └────────────┘
   checks cert,                                    holds cert + key,
   picks SNI / ALPN / fingerprint                  answers the hello
```

Rule: **the client decides how much to trust; the server decides what to present.** That is why `insecure` and `utls` exist only on outbounds, and `key` / `acme` only on inbounds.

## Verification: `insecure` vs proper checking

### Without verification (`insecure: true`)

```
 you (outbound)            attacker on path              real server
┌────────────┐  ClientHello  ┌──────────────┐  ClientHello  ┌──────────┐
│ sing-box   │ ────────────▶ │ fake cert    │ ────────────▶ │ real cert│
│ insecure   │ ◀──────────── │ (self-made)  │ ◀──────────── │          │
└────────────┘  "any cert ok"└──────────────┘               └──────────┘
        ▲
        │ two TLS sessions, attacker in the middle reads and edits everything:
        │ proxy password / UUID, every site you visit through the proxy
```

```json
{ "tls": { "enabled": true, "server_name": "proxy.example.com", "insecure": true } }
```

Consequences:

- The docs define it in one line: "Accepts any server certificate."
- The wire is still encrypted, but to *whoever answered*. Encryption without authentication stops passive sniffing only.
- A man-in-the-middle gets the inner proxy credentials, then can impersonate you to the real server.

### With verification (default)

```
 you (outbound)            attacker on path              real server
┌────────────┐  ClientHello  ┌──────────────┐
│ sing-box   │ ────────────▶ │ fake cert    │
│            │ ◀──────────── │              │
└────────────┘               └──────────────┘
   cert not signed by a trusted CA, or name ≠ server_name
   → handshake aborted, nothing sent
```

```json
{ "tls": { "enabled": true, "server_name": "proxy.example.com" } }
```

Three ways to verify, strictest last:

| Method | Config | Use when |
|---|---|---|
| System CA store | nothing extra | server has a real (ACME) certificate |
| Your own CA / self-signed cert | `certificate` or `certificate_path` | private CA or self-signed server cert |
| Public-key pin | `certificate_public_key_sha256` (since 1.13.0) | trust exactly one key, no CA at all |

Self-signed server? Pin it instead of reaching for `insecure`:

```json
{ "tls": { "enabled": true, "server_name": "proxy.example.com",
           "certificate_public_key_sha256": ["<base64 sha256 of server public key>"] } }
```

## `server_name` / SNI: what the wire shows

`server_name` does double duty (docs): it is the name checked against the certificate, **and** it is sent in the ClientHello "to support virtual hosting unless it is an IP address". That second part is SNI (RFC 6066 §3), and in normal TLS it travels in cleartext.

### With SNI (default)

```
 you ── ClientHello { SNI = "proxy.example.com", ALPN = h2 } ──▶ server
              ▲
              │ on-path sees: destination IP + the name "proxy.example.com"
              │ cannot see: anything after the handshake
              │ can do: block or throttle by that name
```

### Without SNI (`disable_sni: true`)

```
 you ── ClientHello { no SNI } ──▶ server
              ▲
              │ on-path sees: destination IP only
              │ but: a hello with no SNI is itself unusual, and a server hosting
              │ many names cannot tell which certificate to present
```

Related knobs, all client-only:

| Field | Since | What it does to the name on the wire |
|---|---|---|
| `disable_sni` | - | sends no name at all |
| `ech` | - | encrypts the real ClientHello (and its SNI) to a key the server published; config from `config` / `config_path`, otherwise loaded from DNS. `query_server_name` (1.13.0) overrides the name used for that DNS query |
| `fragment` | 1.12.0 | splits the handshake across TCP segments to dodge plaintext packet matching. Docs: slow, "should not be used to circumvent real censorship"; try `record_fragment` first |
| `record_fragment` | 1.12.0 | splits the handshake across several TLS records instead |
| `fragment_fallback_delay` | 1.12.0 | fixed wait used when `fragment` cannot auto-detect timing; default `500ms` |
| `spoof` | 1.14.0 | injects a forged ClientHello carrying an allowed name first; the real server discards it. Needs raw sockets (root / `CAP_NET_RAW` + `CAP_NET_ADMIN` on Linux, Administrator on Windows) |
| `spoof_method` | 1.14.0 | how the forged segment is made unacceptable to the server: `wrong-sequence` (default), `wrong-checksum`, `wrong-ack`, `wrong-md5`, `wrong-timestamp` |

## `utls`: what your ClientHello looks like

Every TLS library builds its ClientHello differently (cipher order, extension list). That pattern is a fingerprint, and it is visible before any encryption starts.

### Without `utls`

```
 you ── ClientHello built by Go crypto/tls ──▶
              ▲
              │ observer: "this is a Go program, not a browser"
              │ the uTLS project's own README: Go's hello "has a very unique fingerprint"
```

### With `utls`

```
 you ── ClientHello copied from Chrome's layout ──▶
              ▲
              │ observer: "looks like Chrome" ... at the ClientHello level
```

```json
{ "tls": { "enabled": true, "server_name": "proxy.example.com",
           "utls": { "enabled": true, "fingerprint": "chrome" } } }
```

Fingerprint values: `chrome` (used if empty), `firefox`, `edge`, `safari`, `360`, `qq`, `ios`, `android`, `random`, `randomized`. Removed in 1.10.0 (now fall back to `chrome`): `chrome_psk`, `chrome_psk_shuffle`, `chrome_padding_psk_shuffle`, `chrome_pq`, `chrome_pq_psk`.

Consequences:

- The sing-box docs mark `utls` **"Not Recommended"**: it copies the hello's *format*, but browsers run different TLS stacks (BoringSSL, NSS) whose *behaviour* cannot be copied, so detection remains possible. Their suggested alternative for fingerprint resistance is NaiveProxy.
- It needs a binary built with the `with_utls` tag.
- It is not supported over QUIC. Docs: "Only ECH is supported in QUIC", so `utls` and `reality` do nothing for `hysteria2` / `tuic`.

## `reality`: client side vs normal TLS

### Normal TLS

```
 you ── SNI "proxy.example.com" ──▶ your server, presents ITS OWN cert
              ▲
              │ you need a domain and a certificate; a prober who connects
              │ sees your server and your cert
```

### Reality

```
 you ── SNI "www.bigsite.com" + secret proof hidden in the hello ──▶ your server
                                                        │
                       proof valid (public_key + short_id match)?
                       ├─ yes → proxy session, no domain or CA cert needed
                       └─ no  → connection forwarded to the real www.bigsite.com
              ▲
              │ observer and prober both see a genuine handshake with www.bigsite.com
```

```json
{ "tls": { "enabled": true, "server_name": "www.bigsite.com",
           "utls": { "enabled": true, "fingerprint": "chrome" },
           "reality": { "enabled": true,
                        "public_key": "<from sing-box generate reality-keypair>",
                        "short_id": "0123456789abcdef" } } }
```

Consequences:

- `public_key` is required. The client gets the **public** half; the inbound holds the `private_key`. Generate the pair with `sing-box generate reality-keypair`.
- `utls.enabled` is **mandatory** with reality. The source rejects the config otherwise: "uTLS is required by reality client". `spoof` is rejected with reality too.
- `server_name` must be the borrowed site's name (the inbound's `handshake.server`), not your own domain.
- `short_id`: the docs text says "a hexadecimal string with zero to eight digits", while the docs' own example and the source (an 8-byte array) use up to 16 hex characters. Treat 16 hex characters as the ceiling; this wording conflict is unresolved in the docs.

## All outbound fields

| Field | Since | Meaning |
|---|---|---|
| `enabled` | - | turn TLS on |
| `engine` | 1.14.0 | TLS implementation: `go` (default), `apple`, `windows` (Schannel). The non-Go engines support only `server_name`, `insecure`, `alpn`, `min_version`, `max_version`, `certificate`(`_path`), `certificate_public_key_sha256`, `handshake_timeout`; no `utls`, `reality`, `ech`, fragmenting, kTLS or client certs |
| `disable_sni` | - | do not send the server name |
| `server_name` | - | name to verify on the cert; also sent as SNI unless it is an IP |
| `insecure` | - | accept any server certificate |
| `alpn` | - | application protocols offered, in preference order (RFC 7301). Handshake fails if both sides use ALPN and share none |
| `min_version` / `max_version` | - | `1.0` to `1.3`; defaults are 1.2 and 1.3 |
| `cipher_suites` | - | TLS 1.0 to 1.2 suites only; TLS 1.3 suites are not configurable |
| `curve_preferences` | 1.13.0 | key exchanges: `P256`, `P384`, `P521`, `X25519`, `X25519MLKEM768` (all on by default) |
| `certificate` / `certificate_path` | - | PEM of the server cert or CA to trust, instead of the system store |
| `certificate_public_key_sha256` | 1.13.0 | pin the server's public key (base64 SHA-256) |
| `client_certificate`(`_path`), `client_key`(`_path`) | 1.13.0 | your own cert + key, for servers that demand mutual TLS (inbound `client_authentication`) |
| `fragment`, `fragment_fallback_delay`, `record_fragment` | 1.12.0 | see SNI section |
| `spoof`, `spoof_method` | 1.14.0 | see SNI section |
| `kernel_tx` / `kernel_rx` | 1.13.0 | kernel TLS; Linux 5.1+, TLS 1.3 only. Docs: TX helps only when `splice(2)` applies, otherwise it degrades performance; RX "will definitely degrade performance" |
| `handshake_timeout` | 1.14.0 | default `15s` |
| `ech` | - | `enabled`, `config`, `config_path`, `query_server_name` (1.13.0). `pq_signature_schemes_enabled` and `dynamic_record_sizing_disabled` were deprecated in 1.12.0 and removed in 1.13.0 |
| `utls` | - | `enabled`, `fingerprint`; legacy chrome values removed in 1.10.0 |
| `reality` | - | `enabled`, `public_key`, `short_id` |

## Which outbounds take `tls`

| Outbound | `tls` | Notes |
|---|---|---|
| `hysteria`, `hysteria2`, `tuic` | **required** | QUIC carries TLS 1.3 inside it; only `ech` of the custom features works |
| `anytls` | **required** | TLS is the protocol |
| `naive` | **required** | only `server_name`, `certificate`, `certificate_path`, `ech` are supported. Docs warn self-signed certs change traffic behaviour and defeat its purpose |
| `shadowtls` | **required** | it performs a real TLS handshake with a decoy site |
| `trojan`, `vless`, `vmess`, `http` | optional | sing-box accepts them without it; whether that is safe depends on the protocol (see [inbound-tls](inbound-tls.md)) |
| `tls`, `https`, `quic`, `h3` DNS servers | optional field | same outbound structure; this is where `server_name` for an IP-addressed resolver goes |
| `socks`, `shadowsocks`, `wireguard`, `ssh`, `tor`, `direct` | no field | bring their own crypto or none |

```
                 ┌──────────────────────────────────────┐
  tls required   │ hysteria hysteria2 tuic              │  docs mark ==Required==
                 │ anytls   naive     shadowtls         │
                 ├──────────────────────────────────────┤
  tls optional   │ trojan  vless  vmess  http           │  runs without; must match the inbound
                 │ DNS: tls https quic h3               │
                 ├──────────────────────────────────────┤
  no tls field   │ socks shadowsocks wireguard ssh tor  │  own crypto, or none
                 └──────────────────────────────────────┘
```

## Inbound vs outbound fields

| Both sides | Inbound only (server) | Outbound only (client) |
|---|---|---|
| `enabled` | `key`, `key_path` | `engine` |
| `server_name` | `client_authentication` | `disable_sni` |
| `alpn` | `client_certificate_public_key_sha256` | `insecure` |
| `min_version`, `max_version` | `certificate_provider` | `certificate_public_key_sha256` |
| `cipher_suites` | `acme` (deprecated 1.14.0) | `client_key`, `client_key_path` |
| `curve_preferences` | `ech.key`, `ech.key_path` | `fragment`, `fragment_fallback_delay`, `record_fragment` |
| `certificate`, `certificate_path` | `reality.handshake` | `spoof`, `spoof_method` |
| `client_certificate`, `client_certificate_path` | `reality.private_key` | `ech.config`, `ech.config_path`, `ech.query_server_name` |
| `kernel_tx`, `kernel_rx` | `reality.max_time_difference` | `utls` |
| `handshake_timeout` | | `reality.public_key` |
| `ech.enabled`, `reality.enabled`, `reality.short_id` | | |

Same name, different meaning:

- `certificate`: inbound = the cert I **present**. Outbound = the cert or CA I **trust**.
- `client_certificate`: inbound = client certs I **accept**. Outbound = the cert I **send**.
- `reality.short_id`: inbound = a **list** of accepted ids. Outbound = **one** of them.

## The pairing rule

The outbound must ask for what the inbound serves.

```
 outbound (client)                          inbound (server)
 server_name            ═══ must match ═══  a name on its certificate
                                            (reality: its handshake.server)
 alpn                   ═══ must overlap ══  alpn
 reality.public_key     ═══ pair of ═══════  reality.private_key
 reality.short_id       ═══ one of ════════  reality.short_id[]
 ech.config             ═══ pair of ═══════  ech.key
 client_certificate+key ═══ trusted by ════  client_authentication + client_certificate*
 min/max_version        ═══ must overlap ══  min/max_version
```

A mismatch is a handshake failure, not a slow connection.

## Decision

```
Does the outbound protocol require tls? (hysteria*, tuic, anytls, naive, shadowtls)
├─ yes → tls.enabled = true
└─ no  → does the inbound on the other end serve TLS?
         ├─ no  → omit tls (only sane on a private wire)
         └─ yes → tls.enabled = true

What certificate does the server have?
├─ real CA cert (ACME)   → set server_name, nothing else
├─ self-signed / own CA  → certificate_path, or certificate_public_key_sha256 (1.13.0+)
├─ reality               → reality{public_key, short_id} + utls.enabled (mandatory)
│                          server_name = the borrowed site
└─ never                 → insecure: true on a network you do not own

Need to hide the name on the wire?
├─ server publishes an ECH config → ech
├─ simple plaintext SNI filter    → record_fragment, then fragment
└─ otherwise                      → a name is going to be visible; pick which one (reality)
```

## References

- Shared TLS fields (Inbound / Outbound structures, "since" markers): https://sing-box.sagernet.org/configuration/shared/tls/
- Outbound pages (per-protocol `tls` and Required markers): https://sing-box.sagernet.org/configuration/outbound/
- Naive outbound (supported TLS field subset): https://sing-box.sagernet.org/configuration/outbound/naive/
- DNS servers with a `tls` block: https://sing-box.sagernet.org/configuration/dns/server/tls/ , `/https/` , `/quic/` , `/http3/`
- Source, option struct: https://github.com/SagerNet/sing-box/blob/testing/option/tls.go
- Source, reality client (uTLS requirement, 8-byte short id): https://github.com/SagerNet/sing-box/blob/testing/common/tls/reality_client.go
- TLS 1.3: RFC 8446, https://www.rfc-editor.org/rfc/rfc8446
- SNI: RFC 6066 §3, https://www.rfc-editor.org/rfc/rfc6066#section-3
- ALPN: RFC 7301, https://www.rfc-editor.org/rfc/rfc7301
- ECH: RFC 9849, https://www.rfc-editor.org/rfc/rfc9849
- uTLS: https://github.com/refraction-networking/utls
- REALITY: https://github.com/XTLS/REALITY
