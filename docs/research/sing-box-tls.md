# sing-box TLS: the inbound (server) and outbound (client) `tls` blocks

Research note, 2026-09-20. Checked against these pinned versions:

- **sing-box v1.14.1** (latest stable on 2026-09-20; the repo's compose files still pin `v1.14.0`), commit `1ac1a339`. Prefix: `https://github.com/SagerNet/sing-box/blob/v1.14.1/`. The docs bundled in that tag are the citation target for documentation claims; the live site `https://sing-box.sagernet.org/configuration/shared/tls/` was fetched 2026-09-20 and carries the same 1.14 fields.
- **sing-vmess v0.2.8**, pinned in sing-box `go.mod:60`, commit `31ec11e8`. Prefix: `https://github.com/SagerNet/sing-vmess/blob/v0.2.8/`. This is the VMess and VLESS wire implementation sing-box actually runs.
- **metacubex/utls v1.8.7**, pinned in sing-box `go.mod:30`. Note this is a fork, not `refraction-networking/utls`.
- **trojan-gfw/trojan** `master` at commit `3e7bb9ae` (protocol spec). **XTLS/REALITY** `main` at commit `5dabb073` (README). Neither repo tags its docs, so these are commit-pinned.
- RFCs 8446, 6066, 7301, 9849, fetched 2026-09-20.

Source links point at a tag (or commit) plus a line anchor. Anything not read directly in source or official docs is marked **inferred** or **unverified**.

Scope: this note is the research deliverable. The concept docs `docs/concepts/inbound-tls.md` and `docs/concepts/outbound-tls.md` (commit `2975743`) are derived from it.

Method note: the first pass read the moving `testing` branch (1.15 alpha). Everything below was re-read at `v1.14.1`. The only documentation difference found between the two is the `min_version` default (§2).

## Questions

1. What is the difference between the inbound and the outbound `tls` block, and which fields exist on which side?
2. Which fields are new, deprecated or removed, and in which version?
3. Which inbounds have a `tls` field, which require it, and what does sing-box do when it is missing?
4. Which outbounds (and DNS servers) have a `tls` field, and which require it?
5. What auth material does each protocol put on the wire if TLS is absent? (trojan, vless, vmess)
6. How does certificate provisioning work on the inbound side (ACME, challenge ports, `certificate_provider`)?
7. How does the client verify the server, and what does `insecure` give up?
8. What do the ClientHello-shaping features do: SNI, `disable_sni`, `ech`, `fragment`, `record_fragment`, `spoof`, `utls`?
9. How does `reality` work on each side, and what is the valid `short_id` length?
10. What are kernel TLS and client authentication (mutual TLS)?
11. What must match between an outbound and the inbound it talks to?

## Short answer / recommendation

- **Inbound `tls` = sing-box is the TLS server; outbound `tls` = sing-box is the TLS client.** One Go struct per side: `InboundTLSOptions` and `OutboundTLSOptions`. Trust decisions (`insecure`, pinning, `utls`) exist only on the client; key material (`key`, `acme`, `certificate_provider`) only on the server.
- **Only QUIC inbounds truly require `tls`.** `hysteria`, `hysteria2` and `tuic` are marked Required and the code rejects a config without it. `trojan`, `naive` (over TCP) and `anytls` inbounds start without `tls`. That is a supported "TLS terminated in front" mode, not a safe default.
- **`socks` inbound has no `tls` field. `mixed` has one, but its docs page does not list it.**
- **Without TLS: vless sends the raw UUID, trojan sends a replayable password hash, and vmess protection depends on client settings.** vmess hides the UUID always, but the header is AEAD only with `alter_id: 0` and the payload is unencrypted when the client picks `security: none` or `zero`. The concept doc's vmess row overstated this and was corrected.
- **Inline `acme` is deprecated in 1.14.0 and scheduled for removal in 1.16.0.** New configs should use `certificate_provider`. This repo does not use inline `acme` (its servers do not terminate public TLS in sing-box), so no migration is needed here.
- **`utls` is marked "Not Recommended" by sing-box itself, and this repo uses it.** `scaffolds/client/outbounds.json:54-61` sets `utls.fingerprint: "chrome"` on the `shadowtls` outbound. It still works; whether to keep it is an open question below.
- **`reality` client needs `utls.enabled`.** The source rejects the config otherwise. The `short_id` docs text ("zero to eight digits") disagrees with the source (8 bytes = 16 hex characters).
- **Prefer `certificate_public_key_sha256` (1.13.0) over `insecure: true`** for self-signed servers.

---

## 1. Two roles, two structs

- The shared docs page has separate `### Inbound` and `### Outbound` structures ([`docs/configuration/shared/tls.md:40-158`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L40-L158)). Fields that belong to one side are tagged `==Client only==` or `==Server only==`.
- In source these are `InboundTLSOptions` ([`option/tls.go:13-40`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/tls.go#L13-L40)) and `OutboundTLSOptions` ([`option/tls.go:107-136`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/tls.go#L107-L136)). A protocol gets the field by embedding `InboundTLSOptionsContainer` ([`option/tls.go:90-92`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/tls.go#L90-L92)) or `OutboundTLSOptionsContainer` ([`option/tls.go:138-140`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/tls.go#L138-L140)). **Whether a protocol embeds the container is the authoritative test for "does it have a `tls` field"**; §3 and §4 use it.

Field placement, from the two docs structures:

| Both sides | Inbound only | Outbound only |
|---|---|---|
| `enabled`, `server_name`, `alpn`, `min_version`, `max_version`, `cipher_suites`, `curve_preferences` | `key`, `key_path` | `engine`, `disable_sni`, `insecure` |
| `certificate`, `certificate_path` | `client_authentication`, `client_certificate_public_key_sha256` | `certificate_public_key_sha256` |
| `client_certificate`, `client_certificate_path` | `certificate_provider`, `acme` | `client_key`, `client_key_path` |
| `kernel_tx`, `kernel_rx`, `handshake_timeout` | `ech.key`, `ech.key_path` | `fragment`, `fragment_fallback_delay`, `record_fragment`, `spoof`, `spoof_method` |
| `ech.enabled`, `reality.enabled`, `reality.short_id` | `reality.handshake`, `reality.private_key`, `reality.max_time_difference` | `ech.config`, `ech.config_path`, `ech.query_server_name`, `utls`, `reality.public_key` |

Same name, opposite meaning:

- `certificate`: inbound presents it; outbound trusts it. The docs describe both as "Server certificates chain" ([`tls.md:329-340`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L329-L340)). On the client it is the trust anchor. **Inferred** from the client structure typing it as a string PEM rather than a presented chain; not stated in so many words.
- `client_certificate`: client-only section = the cert the client sends ([`tls.md:360-390`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L360-L390)); server-only section = client certs the server accepts ([`tls.md:427-445`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L427-L445)).
- `reality.short_id`: a list on the inbound (`"short_id": [...]`, `tls.md:101-103`), a single string on the outbound (`tls.md:155`).

## 2. Versions: added, deprecated, removed

All from the changelog block at the top of the page ([`tls.md:5-38`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L5-L38)) and the per-field markers.

| Version | Change |
|---|---|
| 1.10.0 | `utls`: legacy chrome fingerprints removed, fall back to `chrome` (`chrome_psk`, `chrome_psk_shuffle`, `chrome_padding_psk_shuffle`, `chrome_pq`, `chrome_pq_psk`) ([`tls.md:548-556`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L548-L556)) |
| 1.12.0 | added `fragment`, `fragment_fallback_delay`, `record_fragment`. Deprecated `ech.pq_signature_schemes_enabled`, `ech.dynamic_record_sizing_disabled` |
| 1.13.0 | added `kernel_tx`, `kernel_rx`, `curve_preferences`, `certificate_public_key_sha256`, `client_certificate`(`_path`), `client_key`(`_path`), `client_authentication`, `client_certificate_public_key_sha256`, `ech.query_server_name`. **Removed** the two ECH fields deprecated in 1.12.0 ([`tls.md:580-590`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L580-L590)) |
| 1.14.0 | added `certificate_provider`, `handshake_timeout`, `spoof`, `spoof_method`, `engine`. **Deprecated inline `acme`**, "will be removed in sing-box 1.16.0" ([`tls.md:719-721`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L719-L721)) |

Defaults worth knowing:

- `min_version`: at v1.14.1 the docs say "TLS 1.2 is currently used as the minimum when acting as a client, and TLS 1.0 when acting as a server" ([`tls.md:294-299`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L294-L299)). On `testing` (1.15 alpha) this sentence is replaced by "TLS 1.2 is used by default". sing-box only sets `MinVersion` when the option is non-empty ([`common/tls/std_server.go:371-376`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/std_server.go#L371-L376), [`std_client.go:149-154`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/std_client.go#L149-L154)), so the real default is whatever Go's `crypto/tls` does for the Go version the binary was built with. **Inferred**: the 1.14.1 sentence is likely stale wording copied from older Go docs. **Unverified**: the actual server minimum of a 1.14.1 release binary. Set `min_version` explicitly if it matters.
- `max_version`: TLS 1.3. `handshake_timeout`: `15s` ([`tls.md:501-507`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L501-L507)).
- `cipher_suites` covers TLS 1.0 to 1.2 only; "TLS 1.3 cipher suites are not configurable" ([`tls.md:307-312`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L307-L312)).
- `engine` (1.14.0, client only): `go` (default), `apple`, `windows`. The non-Go engines support only `server_name`, `insecure`, `alpn`, `min_version`, `max_version`, `certificate`(`_path`), `certificate_public_key_sha256`, `handshake_timeout`, and explicitly not `disable_sni`, `cipher_suites`, `curve_preferences`, client certs, fragmenting, kTLS, `ech`, `utls`, `reality` ([`tls.md:197-265`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L197-L265)).

## 3. Inbounds: who has `tls`, who requires it

Three separate questions: does the struct embed the container, do the docs mark it Required, and does the constructor reject a config without it.

| Inbound | Embeds container | Docs `==Required==` | Code without `tls` |
|---|---|---|---|
| `hysteria2` | yes ([`option/hysteria2.go:22`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/hysteria2.go#L22)) | yes ([`inbound/hysteria2.md:127-129`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/hysteria2.md?plain=1#L127-L129)) | **rejected** ([`protocol/hysteria2/inbound.go:49`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/hysteria2/inbound.go#L49)) |
| `tuic` | yes ([`option/tuic.go:12`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/tuic.go#L12)) | yes ([`inbound/tuic.md:76-78`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/tuic.md?plain=1#L76-L78)) | **rejected** ([`protocol/tuic/inbound.go:43`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/tuic/inbound.go#L43)) |
| `hysteria` | yes | yes ([`inbound/hysteria.md:84-86`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/hysteria.md?plain=1#L84-L86)) | constructor not read; **unverified** |
| `trojan` | yes ([`option/trojan.go:6`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/trojan.go#L6)) | no ([`inbound/trojan.md:44`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/trojan.md?plain=1#L44)) | accepted: `if options.TLS != nil` ([`protocol/trojan/inbound.go:52`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/trojan/inbound.go#L52)). Only ALPN fallback needs TLS ([`:75`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/trojan/inbound.go#L75)) |
| `naive` | yes ([`option/naive.go:14`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/naive.go#L14)) | no ([`inbound/naive.md:58`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/naive.md?plain=1#L58)) | accepted over TCP ([`protocol/naive/inbound.go:80`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/naive/inbound.go#L80)); **rejected for QUIC**: "TLS is required for QUIC server" ([`:73-74`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/naive/inbound.go#L73-L74)) |
| `anytls` | yes ([`option/anytls.go:7`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/anytls.go#L7)) | no ([`inbound/anytls.md:59`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/anytls.md?plain=1#L59)) | accepted: `if options.TLS != nil && options.TLS.Enabled` ([`protocol/anytls/inbound.go:47`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/anytls/inbound.go#L47)) |
| `vless` | yes ([`option/vless.go:6`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/vless.go#L6)) | no | optional |
| `vmess` | yes ([`option/vmess.go:6`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/vmess.go#L6)) | no | optional |
| `http` | yes, shared struct ([`option/simple.go:14-19`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/simple.go#L14-L19)) | no ([`inbound/http.md:27`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/http.md?plain=1#L27)) | optional |
| `mixed` | **yes**, same `HTTPMixedInboundOptions`; handshake at [`protocol/mixed/inbound.go:58-62,116`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/mixed/inbound.go#L58-L62) | **field absent from [`inbound/mixed.md`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/mixed.md?plain=1)** | optional. Undocumented, so it could change without notice |
| `socks` | **no**: `SocksInboundOptions` has no container ([`option/simple.go:8-12`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/simple.go#L8-L12)); `protocol/socks/inbound.go` contains zero references to TLS | not in docs | no field |
| `shadowtls` | no ([`option/shadowtls.go:11`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/shadowtls.go#L11)) | not in docs | no field; it relays a handshake to a decoy server instead |
| `shadowsocks` | no | not in docs | no field |
| `ccm`, `ssm-api` services | docs list it ([`service/ccm.md:93`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/service/ccm.md?plain=1#L93), [`service/ssm-api.md:56`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/service/ssm-api.md?plain=1#L56)) | no | optional; option structs not read |

Reading: the missing Required marker on `trojan` / `naive` / `anytls` inbounds is deliberate, not a docs gap, because the code agrees with it. It supports terminating TLS in front of sing-box (nginx, a CDN). **Inferred**: that is the intended use; the docs do not say why.

## 4. Outbounds and DNS servers

| Outbound | Docs | Evidence |
|---|---|---|
| `hysteria`, `hysteria2`, `tuic` | `==Required==` | [`outbound/hysteria.md:120-122`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/hysteria.md?plain=1#L120-L122), [`hysteria2.md:161-163`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/hysteria2.md?plain=1#L161-L163), [`tuic.md:90-92`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/tuic.md?plain=1#L90-L92) |
| `anytls` | `==Required==` | [`outbound/anytls.md:65-67`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/anytls.md?plain=1#L65-L67); enforced at [`protocol/anytls/outbound.go:52`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/anytls/outbound.go#L52). Note the asymmetry with the anytls *inbound* |
| `naive` | `==Required==`, and "Only `server_name`, `certificate`, `certificate_path` and `ech` are supported"; self-signed certs "should not be used in production" | [`outbound/naive.md:124-132`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/naive.md?plain=1#L124-L132) |
| `shadowtls` | `==Required==` | [`outbound/shadowtls.md:48-50`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/shadowtls.md?plain=1#L48-L50) |
| `trojan`, `vless`, `vmess`, `http` | optional | [`trojan.md:48`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/trojan.md?plain=1#L48), [`vless.md:58`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/vless.md?plain=1#L58), [`vmess.md:83`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/vmess.md?plain=1#L83), [`http.md:52`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/http.md?plain=1#L52) |
| `socks`, `shadowsocks` | no field | `SOCKSOutboundOptions` has no container ([`option/simple.go:22-30`](https://github.com/SagerNet/sing-box/blob/v1.14.1/option/simple.go#L22-L30)); docs pages list none |
| `direct`, `ssh`, `tor`, `wireguard` | no field | docs pages list none (checked on `testing` only, **not re-read at the tag**) |
| DNS `tls`, `https`, `quic`, `h3` | optional, outbound structure | [`dns/server/tls.md:52`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/dns/server/tls.md?plain=1#L52), [`https.md:65`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/dns/server/https.md?plain=1#L65), [`quic.md:52`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/dns/server/quic.md?plain=1#L52), [`http3.md:65`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/dns/server/http3.md?plain=1#L65) |

Repo use of the DNS case: `api/app/utils.py:236-242` injects `{"enabled": true, "server_name": <dns_sni>}` into the `dns-remote` server when the host is a pinned IP. That is exactly what `server_name` is for: the docs say it is "used to verify the hostname on the returned certificates" and is sent in the handshake "unless it is an IP address" ([`tls.md:273-277`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L273-L277)). Without it, an IP-addressed DoH server fails name verification.

## 5. What is on the wire without TLS

### 5.1 trojan: confirmed

The request starts with `hex(SHA224(password))`, then CRLF, the request, CRLF, payload ([trojan `docs/protocol.md:11`](https://github.com/trojan-gfw/trojan/blob/3e7bb9ae/docs/protocol.md?plain=1#L11)). The hash is static per password, so a captured one replays. The protocol has no encryption of its own; it assumes TLS.

### 5.2 vless: "UUID in clear" confirmed

- The request header is: version byte (`0`), then the **raw 16-byte UUID**, then addons length, command, address ([`vless/protocol.go:145-156`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/vless/protocol.go#L145-L156); length accounting at [`:126-127`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/vless/protocol.go#L126-L127)). The server reads it back with a plain `io.ReadFull` into `request.UUID` ([`:41`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/vless/protocol.go#L41)).
- A search of `vless/protocol.go`, `vless/client.go` and `vless/service.go` for `aes`, `cipher`, `aead`, `chacha` returns nothing. The vless package contains no encryption. Payload follows the header as-is ([`:166`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/vless/protocol.go#L166)).
- Result: the concept doc row ("UUID in clear", "no built-in encryption; needs `tls` or `reality`") is correct. No change.

### 5.3 vmess: row was overstated, corrected

The old row said "none plain (AEAD encrypted)" and "payload still encrypted by vmess itself". Two conditions were missing:

- **Header.** AEAD applies only when `alter_id` is 0. The client branches on `c.alterId > 0`: legacy mode authenticates with HMAC-MD5 over a timestamp ([`client.go:195-214`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/client.go#L195-L214)); AEAD mode builds an `AuthID` and seals the header length and header with AES-GCM ([`client.go:257-272`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/client.go#L257-L272)). sing-box docs agree: `alter_id` 0 = "Use AEAD protocol", 1 = "Use legacy protocol" ([`outbound/vmess.md:59-65`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/vmess.md?plain=1#L59-L65)). The inbound still accepts legacy users ([`service.go:78-110`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/service.go#L78-L110)) and the docs warn it is "for compatibility purposes only" ([`inbound/vmess.md:42`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/inbound/vmess.md?plain=1#L42)).
- **Payload.** Encryption is the *client's* choice of `security`: `auto`, `none`, `zero`, `aes-128-gcm`, `chacha20-poly1305`, plus legacy `aes-128-ctr` ([`outbound/vmess.md:45-57`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/outbound/vmess.md?plain=1#L45-L57)). The library has distinct `SecurityTypeNone` and `SecurityTypeZero` ([`protocol.go:35-40`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/protocol.go#L35-L40)) with their own reader/writer branches ([`protocol.go:155,171,272`](https://github.com/SagerNet/sing-vmess/blob/v0.2.8/protocol.go#L155)). With either, the payload is not encrypted by vmess. The exact difference between `none` and `zero` was not traced: **unverified**.
- What does hold in every mode: the UUID itself is never sent; the wire carries a value derived from it.
- Not checked against v2fly's own spec pages; sing-vmess is the implementation sing-box runs, so it is the owning source for sing-box behaviour. **Unverified** against v2fly docs.

## 6. Certificates on the inbound: ACME and `certificate_provider`

- Inline `acme` fields: `domain` (ACME "disabled if empty"), `data_directory`, `default_server_name`, `email`, `provider` (`letsencrypt` default, `zerossl`, or a custom URL), `external_account`, `dns01_challenge` ([`tls.md:717-794`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L717-L794)).
- Challenge ports, from the field docs:
  - HTTP challenge listens on port 80; `alternative_http_port` "will be used instead of 80 to spin up a listener" ([`tls.md:761-764`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L761-L764)).
  - TLS-ALPN challenge needs 443: with `alternative_tls_port`, "the system must forward 443 to this port for challenge to succeed" ([`tls.md:766-769`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L766-L769)).
  - `dns01_challenge`: "If configured, other challenge methods will be disabled" ([`tls.md:790-794`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L790-L794)), so it needs neither port.
  - **Inferred**: the 80-as-seen-by-the-CA requirement for HTTP-01 also holds when `alternative_http_port` is set (the docs state the forwarding rule only for the TLS port; the ACME spec, RFC 8555, is the owner and was not read).
- `certificate_provider` (1.14.0, server only): "A string or an object": the tag of a shared provider, or an inline one ([`tls.md:509-519`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L509-L519)). Migration: "Most `tls.acme` fields can be moved into the ACME certificate provider unchanged" ([`docs/migration.md:30-34`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/migration.md?plain=1#L30-L34)).
- `certificate_path`, `key_path`, server `client_certificate_path` and `ech.key_path` are "automatically reloaded if file modified" ([`tls.md:333-338`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L333-L338)).

## 7. Client-side verification

- `server_name` is the name checked on the certificate "unless insecure is given" ([`tls.md:273-277`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L273-L277)).
- `insecure`: "Accepts any server certificate" ([`tls.md:279-283`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L279-L283)). The handshake still encrypts, but to an unauthenticated peer, so an active on-path attacker can terminate it. That consequence is standard TLS reasoning (RFC 8446 treats server authentication as what defeats an active attacker); it is **inferred**, not a sing-box docs statement.
- Alternatives to `insecure` for a self-signed server: a custom trust anchor via `certificate` / `certificate_path`, or a key pin via `certificate_public_key_sha256` (1.13.0), a base64 SHA-256 of the server's public key, with the `openssl` recipe in the docs ([`tls.md:342-358`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L342-L358)).

## 8. Shaping the ClientHello

- **SNI.** `server_name` is sent "to support virtual hosting unless it is an IP address"; `disable_sni` sends none ([`tls.md:267-277`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L267-L277)). SNI is defined in [RFC 6066 §3](https://www.rfc-editor.org/rfc/rfc6066#section-3) and is cleartext in an ordinary ClientHello.
- **ALPN.** Ordered preference list; "the connection will fail if there is no mutually supported protocol" when both peers use it ([`tls.md:285-292`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L285-L292)); [RFC 7301](https://www.rfc-editor.org/rfc/rfc7301).
- **ECH** ([RFC 9849](https://www.rfc-editor.org/rfc/rfc9849)). Server holds `key` / `key_path`; client holds `config` / `config_path`, and "If empty, load from DNS will be attempted"; `query_server_name` (1.13.0) overrides the name used for that HTTPS-record query. Keys come from `sing-box generate ech-keypair` ([`tls.md:571-637`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L571-L637)). ECH is the only custom TLS feature that works over QUIC: "Only ECH is supported in QUIC" ([`tls.md:525`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L525)).
- **`fragment`** (1.12.0): splits the handshake to beat "plaintext packet matching"; "should not be used to circumvent real censorship"; "Due to poor performance, try `record_fragment` first". Wait time is auto-detected on Linux, Apple platforms and (as Administrator) Windows, else `fragment_fallback_delay` (default `500ms`), which is also used when the measured wait is under 20ms ([`tls.md:639-667`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L639-L667)).
- **`record_fragment`** (1.12.0): splits into multiple TLS records instead ([`tls.md:669-675`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L669-L675)).
- **`spoof` / `spoof_method`** (1.14.0): injects a forged ClientHello with an allowed SNI ahead of the real one; the server drops it. Needs raw sockets (`CAP_NET_RAW` + `CAP_NET_ADMIN` on Linux, root on macOS, Administrator + WinDivert on Windows, no Windows ARM64). Methods: `wrong-sequence` (default), `wrong-checksum`, `wrong-ack`, `wrong-md5`, `wrong-timestamp` (not on macOS) ([`tls.md:677-715`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L677-L715)).
- **`utls`**: client only, marked `!!! failure "Not Recommended"`: it copies the ClientHello structure, but browsers "use completely different TLS stacks (Chrome uses BoringSSL, Firefox uses NSS)" whose behaviour cannot be replicated; the docs recommend NaiveProxy instead ([`tls.md:527-569`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L527-L569)). Fingerprints: `chrome` (default when empty), `firefox`, `edge`, `safari`, `360`, `qq`, `ios`, `android`, `random`, `randomized`. sing-box builds against the `metacubex/utls` fork ([`go.mod:30`](https://github.com/SagerNet/sing-box/blob/v1.14.1/go.mod#L30)), and the code needs the `with_utls` build tag ([`common/tls/reality_client.go:1`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/reality_client.go#L1)). The upstream project's motivation, "Golang's ClientHello has a very unique fingerprint", is from the [refraction-networking/utls README](https://github.com/refraction-networking/utls#clienthello-fingerprinting-resistance) (unpinned; the fork's README was not read).

Repo note: `scaffolds/client/outbounds.json:47-61` enables `utls` with `chrome` on the `shadowtls` outbound. It works on 1.14; it is simply a feature upstream now advises against.

## 9. Reality

- **Server** (inbound): `handshake` (the borrowed site plus dial fields, Required), `private_key` (Required), `short_id` list (Required), `max_time_difference` ("Check disabled if empty"). **Client** (outbound): `public_key` (Required), one `short_id`. Keypair from `sing-box generate reality-keypair` ([`tls.md:796-834`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L796-L834)).
- **Client hard requirements in source:** uTLS must be on: "uTLS is required by reality client" ([`common/tls/reality_client.go:59-60`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/reality_client.go#L59-L60)); `spoof` is refused: "spoof is unsupported in reality" ([`:63`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/reality_client.go#L63)). Both client and server files carry `//go:build with_utls`. The docs page does not mention the uTLS requirement.
- **Mechanism, inferred from the README and the client code:** the client hides its proof inside the ClientHello; the code copies the short id into the session id (`copy(hello.SessionId[8:], e.shortID[:])`, [`reality_client.go:190`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/reality_client.go#L190)). A client that cannot prove itself is forwarded to the `handshake` server, so a prober sees the real site. The REALITY README describes `shortIds` as "the acceptable shortId list, which can be used to distinguish different clients" and notes an empty string entry allows an empty client id ([README.en.md:49-50](https://github.com/XTLS/REALITY/blob/5dabb073/README.en.md?plain=1#L49-L50)). The full cryptographic flow was **not** traced.

### 9.1 `short_id` length: docs and source disagree

- Docs: "A hexadecimal string with zero to eight digits." ([`tls.md:822-826`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L822-L826))
- Same docs page, both example structures: `"0123456789abcdef"`, which is **16** hex digits ([`tls.md:101-103`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L101-L103), [`:155`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L155)).
- Source: the client decodes into `var shortID [8]byte` with `hex.Decode` and fails with "invalid short_id" otherwise ([`reality_client.go:78-84`](https://github.com/SagerNet/sing-box/blob/v1.14.1/common/tls/reality_client.go#L78-L84)). 8 bytes = up to 16 hex characters.
- The REALITY README states no length at all.
- Conclusion: the source and the examples agree on a 16-hex-character ceiling. "eight digits" most likely means eight *bytes*: **inferred**. Odd-length strings: `hex.Decode` rejects them; **unverified** by test.

## 10. Kernel TLS and client authentication

- **kTLS** (1.13.0): `kernel_tx`, `kernel_rx`. "Only supported on Linux 5.1+", "Only TLS 1.3 is supported". TX "may only improve performance when `splice(2)` is available (both ends must be TCP or TLS without additional protocols after handshake); otherwise, it will definitely degrade performance". RX "will definitely degrade performance even if `splice(2)` is in use, so enabling it is not recommended" ([`tls.md:465-499`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L465-L499)). Inbounds opt in per protocol: `http`/`mixed` always pass `KTLSCompatible: true` ([`protocol/mixed/inbound.go:58-63`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/mixed/inbound.go#L58-L63)); trojan only when no v2ray transport is set ([`protocol/trojan/inbound.go:52-58`](https://github.com/SagerNet/sing-box/blob/v1.14.1/protocol/trojan/inbound.go#L52-L58)).
- **Client authentication** (1.13.0, server only): `client_authentication` = `no` (default), `request`, `require-any`, `verify-if-given`, `require-and-verify`. One of `client_certificate`, `client_certificate_path`, `client_certificate_public_key_sha256` is required for the two verifying modes ([`tls.md:408-425`](https://github.com/SagerNet/sing-box/blob/v1.14.1/docs/configuration/shared/tls.md?plain=1#L408-L425)). The client answers with `client_certificate`(`_path`) + `client_key`(`_path`).

## 11. The pairing rule

Derived by lining the two structures up; each row follows from the cited field definitions rather than from one docs sentence, so treat the table as **inferred** synthesis.

| Outbound | Must match on the inbound | Failure mode |
|---|---|---|
| `server_name` | a name on the served certificate; with reality, the `handshake.server` site | verification error (§7) |
| `alpn` | overlapping `alpn` | handshake fails (§8) |
| `min_version` / `max_version` | overlapping range | handshake fails |
| `reality.public_key` | derived from `reality.private_key` | falls through to the decoy site (§9) |
| `reality.short_id` | one entry of `reality.short_id[]` | same |
| `ech.config` | generated with `ech.key` | **unverified** what the server does on mismatch |
| `client_certificate` + `client_key` | accepted by `client_authentication` + `client_certificate*` | handshake fails in `require-*` modes |

## Open questions / unknowns

- Actual server-side minimum TLS version of a v1.14.1 release binary (§2). Depends on the Go toolchain used for the release build; not checked.
- `hysteria` (v1) inbound constructor and the `ccm` / `ssm-api` option structs were not read (§3). Docs only.
- `direct`, `ssh`, `tor`, `wireguard` outbound pages were read on `testing`, not at the tag (§4).
- vmess `none` vs `zero` semantics, and any cross-check against v2fly's protocol docs (§5.3).
- HTTP-01 with `alternative_http_port`: whether the CA must still reach port 80 (§6). Owner is RFC 8555, not read.
- ECH server behaviour on config mismatch (§11).
- Should this repo drop `utls` from the client scaffold now that upstream marks it "Not Recommended"? The `shadowtls` server's tolerance for a Go-default ClientHello was not tested.
- The repo pins `v1.14.0`; nothing in this note is known to differ between 1.14.0 and 1.14.1, but the 1.14.0 tag was not diffed.

## Sources

- sing-box v1.14.1: https://github.com/SagerNet/sing-box/tree/v1.14.1 (`docs/configuration/shared/tls.md`, `option/tls.go`, `option/simple.go`, `option/{trojan,naive,anytls,vless,vmess,hysteria2,tuic,shadowtls}.go`, `protocol/{trojan,naive,anytls,hysteria2,tuic,mixed,socks}/inbound.go`, `protocol/anytls/outbound.go`, `common/tls/{reality_client,std_client,std_server}.go`, `docs/migration.md`, `go.mod`)
- sing-box docs site, fetched 2026-09-20: https://sing-box.sagernet.org/configuration/shared/tls/
- sing-box releases (1.14.1 latest stable, 1.15.0-alpha.6 pre-release on 2026-09-20): https://github.com/SagerNet/sing-box/releases
- sing-vmess v0.2.8: https://github.com/SagerNet/sing-vmess/tree/v0.2.8 (`vless/protocol.go`, `client.go`, `service.go`, `protocol.go`)
- Trojan protocol: https://github.com/trojan-gfw/trojan/blob/3e7bb9ae/docs/protocol.md
- REALITY README: https://github.com/XTLS/REALITY/blob/5dabb073/README.en.md
- uTLS README: https://github.com/refraction-networking/utls
- RFC 8446 (TLS 1.3): https://www.rfc-editor.org/rfc/rfc8446
- RFC 6066 §3 (SNI): https://www.rfc-editor.org/rfc/rfc6066#section-3
- RFC 7301 (ALPN): https://www.rfc-editor.org/rfc/rfc7301
- RFC 9849 (ECH): https://www.rfc-editor.org/rfc/rfc9849
