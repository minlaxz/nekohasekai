# DPI- and probe-resistant protocols in sing-box, compared with this repo's ShadowTLS + Shadowsocks

Research note, 2026-09-29. Checked against these pinned versions:

- **sing-box v1.14.2** (latest stable on 2026-09-29; `scaffolds/Dockerfile` pulls `ghcr.io/sagernet/sing-box:latest`), commit `af6e64c`. Prefix: `https://github.com/SagerNet/sing-box/blob/v1.14.2/`. Documentation claims cite the docs bundled in that tag; the rendered site is `https://sing-box.sagernet.org/`.
- **sing-shadowsocks v0.2.8** (pinned in sing-box `go.mod:54`), commit `e061249`. Prefix: `https://github.com/SagerNet/sing-shadowsocks/blob/v0.2.8/`.
- **Protocol specs and reference repos**, commit-pinned because they do not tag their docs: ihciah/shadow-tls `02dd0bc` (release v0.2.25), XTLS/REALITY `3c98159`, apernet/hysteria `4a0f102` (release app/v2.12.3), anytls/anytls-go `fd6167a` (release v0.0.13), klzgrad/naiveproxy `11c798a9`, Shadowsocks-NET/shadowsocks-specs `20b4952e`.
- **Measurement papers** (primary): USENIX Security 2023 (fully encrypted traffic), IMC 2020 (Shadowsocks probing), USENIX Security 2024 (encapsulated TLS handshakes), USENIX Security 2025 (QUIC SNI censorship). Plus net4people/bbs issues by the original reporters.

Source links point at a tag (or commit) plus a line anchor. Anything not read directly in source, official docs, or the papers is marked **inferred**, **unverified**, or **anecdotal** (a single user report, not a measurement).

Scope: this note compares protocols. It builds on `docs/research/sing-box-tls.md` (2026-09-20) and does not repeat it. In particular, the `tls` block fields, the REALITY config fields and `short_id` length, and the decision to keep `utls` on the ShadowTLS client are covered there. No config was changed and nothing was tested live.

## Questions

1. What does the repo run today? Is ShadowTLS at v3, and is the Shadowsocks cipher a 2022 one?
2. What are the three passive detection families (fully-encrypted/entropy, TLS-in-TLS, JA3/JA4-style handshake fingerprints), and what is the evidence for each?
3. For each candidate protocol in sing-box: how does it resist passive fingerprinting and active probing, how much does it depend on UDP, what does it cost to run, and what known weaknesses or blocking events exist?
4. Which of them should this repo adopt, in what order?

## Short answer / recommendation

- **ShadowTLS is v3 with `strict_mode: true`. The Shadowsocks cipher is not a 2022 one.** Both the server inbound and all client outbounds use `xchacha20-ietf-poly1305`, a legacy AEAD method (`scaffolds/server/inbounds.json:8`, `scaffolds/client/outbounds.json:7,24,40`).
- **The biggest weakness is not the protocol choice. It is that the raw Shadowsocks TCP port is published.** `docker-compose.yaml:76-77` exposes `SHADOWSOCKS_PORT` on both TCP and UDP. The TCP side is a plain fully-encrypted service on the same IP as the ShadowTLS port, which is exactly what the GFW's passive fully-encrypted detector targets (§2.1) and what its Shadowsocks prober targets (§2.2). The ShadowTLS path does not need that port: the ShadowTLS inbound hands connections to the Shadowsocks inbound in-process via `detour`. Removing the `/tcp` mapping is a one-line change. **Inferred**: nothing else in the repo dials the raw TCP port; the `shadowsocks-tcp` and `shadowsocks-uot` outbounds both go through `shadowtls`.
- **Moving to SS-2022 buys replay protection, not invisibility.** SS-2022 is still a fully-encrypted stream, so it falls into the same entropy class as today's cipher. What it adds is a mandatory timestamp and salt replay filter that defeats the replay probes seen in 2020 (§3.1). It is not a drop-in change here: the managed (ssm-api) multi-user mode only accepts `2022-blake3-aes-128-gcm` or `-aes-256-gcm`, and it needs a base64 server key plus base64 per-user keys (§3.1).
- **Ranked recommendation for this repo** (hedged; most evidence is about China's GFW, and the Russian and Iranian reports are anecdotal):
  1. **Fix the baseline first**: stop publishing the raw SS TCP port, then move to `2022-blake3-aes-128-gcm`. This is cheap and keeps ssm-api's no-restart user management.
  2. **Add VLESS + REALITY + `xtls-rprx-vision`** as the primary new transport. It needs no domain, active probes see a real third-party site, and Vision pads the inner TLS handshake. The costs: sing-box has no managed-user API for VLESS (users are static config and need a restart), and there are two documented weaknesses (IP-to-SNI mismatch and a post-handshake `NewSessionTicket` fingerprint, §3.2).
  3. **Add Trojan or VLESS over WebSocket/HTTPUpgrade behind a CDN** as the survivability fallback. The repo already runs Caddy on 443 with an ACME domain (`docker-compose.yaml:10-35`). This is TLS-in-TLS-exposed and slower, but it survives IP blocking of the VPS.
  4. **Hysteria2** only where UDP is known to work well. It conflicts with Caddy on `443/udp`, so it needs another port.
  5. **AnyTLS** is a reasonable alternative to (2) for padding-based TLS-in-TLS mitigation, but it has weaker active-probe behaviour unless it is paired with REALITY.
  6. **NaiveProxy** has the best passive story on paper, but sing-box's *inbound* does not do the probe resistance that the reference Caddy server does, and the sing-box *outbound* is platform-limited.
  7. **TUIC** is last: it is UDP-only, has no masquerade, and its upstream was archived and then restarted.

---

## 1. What the repo runs today

| Item | Value | Where |
|---|---|---|
| ShadowTLS version | `3`, `strict_mode: true`, one shared user | `scaffolds/server/inbounds.json:16-30`, `scaffolds/entrypoint.sh:57` |
| ShadowTLS client | `version: 3`, `utls` `chrome` | `scaffolds/client/outbounds.json:47-61` |
| SS cipher | `xchacha20-ietf-poly1305` (legacy AEAD) | server `inbounds.json:8`; client `outbounds.json:7,24,40` |
| SS users | `managed: true` (ssm-api) | `inbounds.json:10` |
| Multiplex | server enabled, `padding: false`; client disabled | `inbounds.json:11-14`; `outbounds.json:10-17` |
| Published ports | SS TCP + UDP, ShadowTLS TCP; Caddy 80, 443/tcp, 443/udp | `docker-compose.yaml:19-22,76-78` |
| UDP path | `shadowsocks-udp` goes straight to the raw SS UDP port; `shadowsocks-uot` tunnels UDP over ShadowTLS | `outbounds.json:19-46` |

ShadowTLS v3 facts from sing-box's docs: `version` 1 is the default, 3 is ihciah's v3 spec, `users` and `strict_mode` exist only in v3 ([`inbound/shadowtls.md:51-91`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/shadowtls.md?plain=1#L51-L91)). The v3 spec says: "The V3 protocol only supports handshake servers using TLS1.3 in strict mode" ([`protocol-v3-en.md:28-33`](https://github.com/ihciah/shadow-tls/blob/02dd0bc/docs/protocol-v3-en.md?plain=1#L28-L33)). So the `SHADOWTLS_SNI` site must support TLS 1.3, or strict-mode handshakes fail. **Unverified** for the SNI the repo actually deploys.

## 2. The detection families (evidence)

### 2.1 Fully-encrypted ("looks like nothing") detection

- **USENIX Security 2023** (Wu et al., "How the Great Firewall of China Detects and Blocks Fully Encrypted Traffic"). Starting in November 2021, the GFW passively blocks connections whose **first client TCP payload** matches none of five exemptions: Ex1, popcount/len ≤ 3.4 or ≥ 4.6; Ex2, the first six bytes are printable ASCII; Ex3, more than 50% of bytes are printable; Ex4, more than 20 contiguous printable bytes; Ex5, "It matches the protocol fingerprint for TLS or HTTP". The GFW "only monitors 26% of connections and only to specific IP ranges of popular data centers". Blocking is by 3-tuple (client IP, server IP, server port) for 180 seconds. "UDP traffic is not affected." ([paper page](https://gfw.report/publications/usenixsecurity23/en/)).
- Consequence: anything that is TLS on the wire (ShadowTLS, REALITY, AnyTLS, Trojan, VLESS+TLS, Naive) is exempt through Ex5. Raw Shadowsocks of any cipher, including SS-2022, is the target class. The paper's mitigation (a customizable printable prefix) was shipped in shadowsocks-rust and shadowsocks-android, not in sing-box's options (**inferred** from the sing-box docs listing no such field).

### 2.2 Active probing

- **IMC 2020** (GFW Report et al., "How China Detects and Blocks Shadowsocks"): "the GFW uses the length and entropy of the first data packet in each connection to identify probable Shadowsocks traffic, then sends seven different types of active probes"; "The probes are partial replays of past legitimate connections, and random probes of varied lengths." Server reactions to replays "differ depending on replay detection and stream/AEAD ciphers" ([paper page](https://gfw.report/publications/imc20/en/)).
- The Trojan inbound docs carry an upstream opinion worth noting: "There is no evidence that GFW detects and blocks Trojan servers based on HTTP responses, and opening the standard http/s port on the server is a much bigger signature" ([`inbound/trojan.md:48-54`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/trojan.md?plain=1#L48-L54)).

### 2.3 TLS-in-TLS (encapsulated handshake) detection

- **USENIX Security 2024** (Xue, Kallitsis, Houmansadr, Ensafi, "Fingerprinting Obfuscated Proxy Traffic with Encapsulated TLS Handshakes"). The authors detect the nested TLS handshake that every proxied HTTPS connection carries, and deployed the detector in an ISP "serving upwards of one million users". Their evaluation of defences finds "stream multiplexing shows promise", but that "existing obfuscations based on multiplexing and random padding alone are inherently limited" because they "cannot reduce the size of traffic bursts or the number of round trips" ([paper page](https://www.usenix.org/conference/usenixsecurity24/presentation/xue-fingerprinting)).
- This applies to **every** candidate below that tunnels the user's HTTPS, including today's ShadowTLS + SS. The only differences are how much padding or multiplexing each protocol applies.
- **October 2022 event** (GFW Report, [net4people #129](https://github.com/net4people/bbs/issues/129)): from 2022-10-03, more than 100 users reported TLS-based servers blocked: "trojan, Xray, V2Ray TLS+Websocket, VLESS, and gRPC". "We have not received any report of the blocking of naiveproxy though." Blocking was by port, escalating to IP, and domains were not added to DNS or SNI blocklists. The cause was not established.

### 2.4 Handshake fingerprints (JA3/JA4, QUIC)

- The TCP TLS ClientHello side (utls, Go-default hellos, and sing-box's own warning about utls) is covered in `sing-box-tls.md` §8 and its resolved open question. It is not repeated here.
- **QUIC**: sing-box 1.14.0 made Hysteria2 clients "parrot Chrome's QUIC handshake by default", which breaks servers with Ed25519 certificates ([`changelog.md:559-571`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L559-L571); [`outbound/hysteria2.md:183-191`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/outbound/hysteria2.md?plain=1#L183-L191)).
- **USENIX Security 2025** (GFW Report et al., QUIC SNI censorship): "the Great Firewall of China (GFW) has begun blocking QUIC connections to specific domains since April 7, 2024". It "decrypts QUIC Initial packets at scale" with a blocklist that "substantially differs" from the TLS one. "As of January 2025, the GFW does not reassemble a TLS Client Hello when it is split across multiple UDP datagrams". The mitigation shipped in sing-box 1.12.0-beta.17 and in quic-go v0.52.0 ([paper page](https://gfw.report/publications/usenixsecurity25/en/)).

## 3. Candidates

### 3.1 Baseline: ShadowTLS v3 + Shadowsocks (legacy AEAD today, SS-2022 proposed)

- **Passive.** The handshake is a real TLS 1.3 handshake relayed from the SNI site, so Ex5 exempts it. After the switch, data travels in `application_data` records with a 4-byte HMAC ([`protocol-v3-en.md:54-66`](https://github.com/ihciah/shadow-tls/blob/02dd0bc/docs/protocol-v3-en.md?plain=1#L54-L66)). No padding is applied to the inner stream, and the repo has multiplex padding off, so the nested user TLS handshake is exposed (§2.3). **Inferred.**
- **Active.** A ClientHello that fails the SessionID HMAC is relayed to the real handshake server ("mark it as active detection traffic and start TCP forwarding directly", [`protocol-v3-en.md:93`](https://github.com/ihciah/shadow-tls/blob/02dd0bc/docs/protocol-v3-en.md?plain=1#L93)). v3 also detects traffic hijacking ([`:35-52`](https://github.com/ihciah/shadow-tls/blob/02dd0bc/docs/protocol-v3-en.md?plain=1#L35-L52)).
- **Known weaknesses.**
  - The FOCI 2023 paper "Chasing Shadows" (Wang et al.) broke **v1** passively and actively and found ~15,000 TLS servers that responded like ShadowTLS. Its fixes (utls, `application_data` framing with a MAC) are what v2/v3 adopted ([net4people #322](https://github.com/net4people/bbs/issues/322), summary by wkrp).
  - **Aparecium** (2025-05) is a PoC that detects ShadowTLS v3 and REALITY by their handling of TLS 1.3 post-handshake `NewSessionTicket` messages, "especially against OpenSSL-based servers". ShadowTLS's 4-byte HMAC "tainting" makes it "particularly vulnerable" ([net4people #481](https://github.com/net4people/bbs/issues/481); [aparecium README](https://github.com/ban6cat6/aparecium)). It is a PoC, and no deployment by a censor is reported.
  - IP-to-SNI mismatch: the SNI's DNS does not resolve to the VPS (see §3.2, it applies equally).
- **SS-2022 vs legacy AEAD.** SIP022 "allows and mandates full replay protection": timestamps more than 30 s off "MUST be treated as replay", and "Servers MUST store all incoming salts for 60 seconds". Servers must also not reveal how many bytes they consumed before closing, "This defends against probes that send one byte at a time" ([spec `:11`, `:146-174`](https://github.com/Shadowsocks-NET/shadowsocks-specs/blob/20b4952e/2022-1-shadowsocks-2022-edition.md?plain=1#L146-L174)). sing-shadowsocks implements a 60 s salt filter for 2022 ([`shadowaead_2022/service.go:75,160`](https://github.com/SagerNet/sing-shadowsocks/blob/v0.2.8/shadowaead_2022/service.go#L160)); a search for `replay` in the legacy `shadowaead` package finds nothing (**inferred**: no replay filter for the repo's current cipher). Behind ShadowTLS, probes rarely reach the SS layer; the benefit matters most for the **exposed raw port**.
- **Migration cost in this repo (source-verified).** `managed: true` always takes the multi-user path ([`protocol/shadowsocks/inbound.go:35-39`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/shadowsocks/inbound.go#L35-L39)). For 2022 methods that path calls `NewMultiServiceWithPassword(options.Method, options.Password, …)` ([`inbound_multi.go:66-81`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/shadowsocks/inbound_multi.go#L66-L81)), which rejects every method except the two AES-GCM ones ([`service_multi.go:50-56`](https://github.com/SagerNet/sing-shadowsocks/blob/v0.2.8/shadowaead_2022/service_multi.go#L50-L56)). So:
  - The server inbound needs a `password` (the base64 server PSK).
  - Each user key must be base64 of the method's key length (16 bytes for aes-128, [`inbound/shadowsocks.md:64-87`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/shadowsocks.md?plain=1#L64-L87)).
  - `2022-blake3-chacha20-poly1305` cannot be used with ssm-api.
  - The client password format (**inferred** from SIP022 identity headers, not traced in sing-box's client) is `<server PSK>:<user PSK>`.
  - Existing `users.json` passwords are not valid keys. `create_upsk` (`api/app/routes/ssm.py:36-41`) makes 20 random `[a-z0-9]` characters plus `==` (22 characters). A base64 16-byte key is 24 characters, so `UpdateUsersWithPasswords` fails with `decode psk` ([`service_multi.go:103-116`](https://github.com/SagerNet/sing-shadowsocks/blob/v0.2.8/shadowaead_2022/service_multi.go#L103-L116)). Every user must be reissued.
  - ShadowTLS is not affected: its password is one shared secret set by `scaffolds/entrypoint.sh:49-57`, separate from the per-user Shadowsocks PSK.
  - ssm-api `Add` stores the user in its map before `postUpdate` runs and does not remove it on error ([`service/ssmapi/user.go:56-64`](https://github.com/SagerNet/sing-box/blob/v1.14.2/service/ssmapi/user.go#L56-L64)). One bad key therefore makes every later add fail until restart (**inferred** from source, not tested).
- **UDP.** TCP-only through ShadowTLS; UDP either goes raw to the SS port or uses UoT v2 over ShadowTLS.
- **Cost.** No domain and no certificate. It does need a TLS 1.3 third-party SNI.

### 3.2 VLESS + REALITY (with or without `xtls-rprx-vision`)

- **Passive.** Real TLS 1.3 on the wire (Ex5), and there is no server TLS fingerprint of its own: REALITY "can **eliminate the detectable TLS fingerprint on the server side**" ([REALITY `README.en.md:73`](https://github.com/XTLS/REALITY/blob/3c98159/README.en.md?plain=1#L73)).
  - **Vision** (`flow: xtls-rprx-vision`, [`outbound/vless.md:42-48`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/outbound/vless.md?plain=1#L42-L48)) targets TLS-in-TLS. The design post says "the most obvious characteristic is the length of these 5 packets" of the inner handshake and pads short packets "to a range of 900 to 1400". It also admits it does not address timing ([Xray-core discussion #1295](https://github.com/XTLS/Xray-core/discussions/1295), yuhan6665, 2022-10-31, in Chinese). Xray v1.8.0 extended the padding to "0-256" plus non-TLS header padding ([release v1.8.0](https://github.com/XTLS/Xray-core/releases/tag/v1.8.0)).
  - Without Vision, VLESS+REALITY carries unpadded TLS-in-TLS, like the baseline.
- **Active.** An unauthenticated client is forwarded to the `handshake` target and sees the real site. A client that gets the real certificate enters "spider" mode ([`README.en.md:121-131`](https://github.com/XTLS/REALITY/blob/3c98159/README.en.md?plain=1#L121-L131); mechanism in `sing-box-tls.md` §9).
- **UDP.** TCP only; UDP is carried inside VLESS.
- **Cost.** No domain and no certificate. The target should be "out of China's GFW, support TLSv1.3 and H2", and have an IP "closer to proxy IP" ([`README.en.md:76-78`](https://github.com/XTLS/REALITY/blob/3c98159/README.en.md?plain=1#L76-L78)).
  - Repo-specific: VLESS users are UUIDs in static config. ssm-api manages only Shadowsocks inbounds ([`service/ssm-api.md:39`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/service/ssm-api.md?plain=1#L39)), so user add/remove would need a config rewrite and a restart. That breaks the "no sing-box restart" property in CONTEXT.md.
- **Implementation note.** sing-box's REALITY server is not the XTLS library. It calls `utls.RealityServer` from `metacubex/utls` ([`common/tls/reality_server.go:203`](https://github.com/SagerNet/sing-box/blob/v1.14.2/common/tls/reality_server.go#L203)). **Inferred**: fixes in XTLS/REALITY (e.g. for Aparecium) do not reach sing-box automatically.
- **Weaknesses and events.**
  - Aparecium also covers REALITY (§3.1). In the thread, Xray developers acknowledged the length feature and discussed padding post-handshake records (net4people #481 comments, 2025). Fix status is unknown (open question).
  - **SNI-to-DNS consistency.** The SNI's DNS never points at the VPS, and nDPI (2025-10) already flags TLS SNIs "not previously resolved to that IP" ([net4people #668](https://github.com/net4people/bbs/issues/668), 2026-09-25; [ntop blog](https://www.ntop.org/when-snis-cannot-be-trusted/)). The same argument hits ShadowTLS. It is an argument, and no censor deployment is documented.
  - **Anecdotal**: Russia, 2025-11: some home ISPs cut VLESS+REALITY+Vision once data flowed, including "self steal" setups, with recovery after ~60 s ([net4people #546](https://github.com/net4people/bbs/issues/546)). Also a single report of fast REALITY detection versus a real certificate ([#438](https://github.com/net4people/bbs/issues/438)).

### 3.3 AnyTLS

- **Passive.** Real TLS (Ex5). The protocol exists to "mitigate nested TLS handshake fingerprinting (TLS in TLS)" ([README.md:3](https://github.com/anytls/anytls-go/blob/fd6167a/README.md?plain=1#L3)). It uses a server-updatable padding scheme ([`inbound/anytls.md:39-58`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/anytls.md?plain=1#L39-L58)) and session multiplexing, the direction USENIX 2024 calls promising (§2.3). The FAQ admits the default scheme "cannot be guaranteed not to be blocked" ([`docs/faq.md:27-29`](https://github.com/anytls/anytls-go/blob/fd6167a/docs/faq.md?plain=1#L27-L29)).
- **Known weaknesses (the author's own list, [`faq.md:56-69`](https://github.com/anytls/anytls-go/blob/fd6167a/docs/faq.md?plain=1#L56-L69)).** Extra round trips from TLS-over-TLS; no downstream shaping; bursts of three or more packets within the first RTT; packets exceeding MTU; and "since this is not an HTTP server, active probing problems may still exist".
  - sing-box found that the client metadata field was used "to profile and discriminate against users". It is empty by default since 1.13.16 and 1.14.0-beta.5 ([`changelog.md:575-598`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L575-L598); [`manual/misc/anytls-client-metadata.md`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/manual/misc/anytls-client-metadata.md)).
- **Active.** The reference server closes the connection or falls back on auth failure ([`docs/protocol.md:187`](https://github.com/anytls/anytls-go/blob/fd6167a/docs/protocol.md?plain=1#L187)); sing-box's inbound has no fallback field ([`option/anytls.go`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/anytls.go)). The inbound builds its TLS with the generic `tls.NewServer` ([`protocol/anytls/inbound.go:48`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/anytls/inbound.go#L48)), which dispatches to REALITY when `reality.enabled` is set. **Inferred and untested**: AnyTLS + REALITY is valid, and it would give REALITY's probe behaviour plus AnyTLS padding.
- **UDP.** TCP only. **Cost.** Needs a certificate (self-signed plus pinning is possible) or REALITY. Users are static config (same restart cost as VLESS).

### 3.4 Hysteria2 (with or without Salamander, and `gecko` in 1.14)

- **Passive.** QUIC. Without obfs, it is Chrome-parroted QUIC since 1.14.0 (§2.4), and the SNI is exposed to the GFW's QUIC SNI filter (§2.4, blocklist-based).
  - **Salamander** XORs every packet with BLAKE2b-256(key‖salt) ([`PROTOCOL.md:129-160`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L129-L160)), so the wire is random bytes rather than QUIC. That is fully-encrypted-looking UDP. USENIX 2023 found UDP unaffected by that detector (§2.1); nothing newer was checked.
  - **`gecko`** (sing-box 1.14.0-alpha.26) is a second obfs type with `min_packet_size`/`max_packet_size` ([`inbound/hysteria2.md:83-107`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L83-L107); [`changelog.md:1004-1015`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L1004-L1015)). Its design was not traced, and it is not in apernet's spec at this commit.
- **Active.** Without obfs, the server "behaves just like a standard HTTP/3 web server" to unauthenticated probers ([`PROTOCOL.md:17-21`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L17-L21)); sing-box exposes this as `masquerade` ([`inbound/hysteria2.md:137-186`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L137-L186)). With Salamander, "Any invalid packet MUST be discarded", so the port is silent to probes. **Inferred**: the masquerade is then unreachable.
- **UDP.** Fully dependent.
  - **Anecdotal**: Iran, 2022-12: Hysteria and TUIC failed on some VPS IPs while raw UDP worked ([net4people #181](https://github.com/net4people/bbs/issues/181)). China, 2023-07: intermittent blocking of all QUIC ([#264](https://github.com/net4people/bbs/issues/264)).
  - USENIX 2025 also shows the QUIC filter can be weaponized to block UDP between arbitrary hosts (§2.4).
- **Cost.** Needs a certificate (QUIC requires `tls`, see `sing-box-tls.md` §3; Ed25519 certificates break the Chrome parrot). Repo conflict: Caddy already binds `443/udp` (`docker-compose.yaml:22`).

### 3.5 TUIC

- **Passive.** QUIC with TLS, like Hysteria2 without obfs. No Chrome-parrot option is documented for TUIC (**inferred** from the docs).
- **Active.** No masquerade field in sing-box's inbound docs. There is an `auth_timeout`, and `zero_rtt_handshake` carries the warning "Disabling this is highly recommended, as it is vulnerable to replay attacks" ([`inbound/tuic.md:55-68`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/tuic.md?plain=1#L55-L68)). What an unauthenticated QUIC client sees was not traced.
- **UDP.** Fully dependent (same events as §3.4).
- **Project status.** EAimTY/tuic was "Archived + Cleared the default `master` branch" on 2023-11-03 ([net4people #303](https://github.com/net4people/bbs/issues/303)). Development restarted under `tuic-protocol/tuic` in 2025 ([#502](https://github.com/net4people/bbs/issues/502)).
- **Cost.** Certificate needed.

### 3.6 Trojan / VLESS over TLS + WebSocket, HTTPUpgrade, or gRPC behind a CDN

- **Passive.** Real TLS from the CDN edge (Ex5). The client's JA3 is whatever sing-box sends (see `sing-box-tls.md` §8). Inner TLS-in-TLS is unpadded. These are exactly the transports named in the October 2022 event (§2.3); the servers there were mostly not behind CDNs (**inferred**; the report does not say).
- **Active.** Probers hit the CDN or Caddy, which serve a normal site; the proxy path is only a URL path. Trojan also has `fallback` (§2.2).
- **Survivability.** The VPS IP is hidden, so IP blocking of the server does nothing. Blocking needs the CDN's IPs or the domain.
- **Transports.** sing-box supports WebSocket (with `max_early_data`), gRPC, and HTTPUpgrade ([`shared/v2ray-transport.md:101-230`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/v2ray-transport.md?plain=1#L101-L230)); XHTTP is not supported (no match in the docs or `option/`). Cloudflare proxies WebSockets ([docs](https://developers.cloudflare.com/network/websockets/)) and gRPC; on gRPC, "When gRPC is not enabled on a zone, Cloudflare will respond to gRPC requests with a 403" ([docs](https://developers.cloudflare.com/network/grpc-connections/)).
- **UDP.** TCP only.
- **Cost.** A domain and a CDN account. The repo already has a domain and ACME via Caddy (`APP_HOST`), so this is the lowest-friction TLS option. **Inferred**: a `reverse_proxy` label on a path to a sing-box WS/HTTPUpgrade inbound.

### 3.7 NaiveProxy

- **In sing-box?** Yes, both sides. The **inbound** has existed for a long time (`with_quic` for HTTP/3). The **outbound** was added in 1.13.0 ([`changelog.md:1480`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L1480)) and is built on cronet, "only available on Apple platforms, Android, Windows and certain Linux builds" ([`outbound/naive.md:31-45`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/outbound/naive.md?plain=1#L31-L45)).
- **Passive.** The reference design defeats TLS parameter fingerprinting "by reusing Chrome's network stack" and mitigates length analysis "by padding and fragmentation" ([naiveproxy README:7-10](https://github.com/klzgrad/naiveproxy/blob/11c798a9/README.md?plain=1#L7-L10)). sing-box's own utls warning recommends NaiveProxy for this reason (`sing-box-tls.md` §8). `insecure_concurrency` "makes the tunneling easier to detect" ([`outbound/naive.md:75-77`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/outbound/naive.md?plain=1#L75-L77)). It was not named in the 2022 event (§2.3).
- **Active: sing-box's inbound is weaker than the reference.** The reference expects a frontend that routes on the auth header, "preventing active probing of proxy existence" (Caddy forwardproxy with `probe_resistance`, [README:18-55](https://github.com/klzgrad/naiveproxy/blob/11c798a9/README.md?plain=1#L18-L55)). sing-box's inbound answers:
  - a non-CONNECT request, or one missing the `Padding` header, with `400`;
  - a bad password with `407 Proxy Authentication Required`;
  - over HTTP/1.1 it hijacks the connection and sets `SO_LINGER 0` (a RST) ([`protocol/naive/inbound.go:152-172,238-250`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/naive/inbound.go#L152-L172)).

  **Inferred**: a 407 to a probe is a proxy tell. Use the Caddy naive fork as the server and sing-box only as the client.
- **UDP.** Optional `quic`; UoT is available. **Cost.** Domain plus certificate, and a custom Caddy build. Client limited to cronet-capable builds.

## 4. Comparison

| | Passive: FET (§2.1) | TLS-in-TLS (§2.3) | Handshake FP | Active probing | UDP need | Needs domain/cert | Users via ssm-api |
|---|---|---|---|---|---|---|---|
| ShadowTLS v3 + SS | exempt (TLS) | unpadded | utls chrome | relayed to real site | no | no | yes |
| raw SS port (today) | **target** | n/a | none | legacy: no replay filter | UDP side yes | no | yes |
| VLESS+REALITY+Vision | exempt | padded (lengths only) | utls required | relayed to real site | no | no | no |
| AnyTLS (+REALITY) | exempt | padded, server-tunable | utls | close; REALITY if paired | no | cert or REALITY | no |
| Hysteria2 | QUIC / random with obfs | QUIC-level only | Chrome QUIC parrot | HTTP/3 masquerade (none with obfs) | **yes** | cert | no |
| TUIC | QUIC | none | not parroted | not documented | **yes** | cert | no |
| Trojan/VLESS WS via CDN | exempt | unpadded | utls | CDN/site | no | domain + CDN | no |
| Naive (Caddy server) | exempt | padded | real Chrome | Caddy probe_resistance | optional | domain + cert | no |

## Open questions / unknowns

- **Which censor?** Almost all measurements are about China's GFW. The deploy region's behaviour (UDP throttling, whitelisting, Russian-style connection policing) is unknown, and it changes the ranking of Hysteria2 and REALITY most.
- **Aparecium fix status.** Whether XTLS/REALITY, `metacubex/utls`'s `RealityServer`, or sing-shadowtls v0.2.1 now pad or emulate `NewSessionTicket` was not checked in source.
- **SS-2022 client password format in sing-box** (`server:user`) is inferred from SIP022 and not traced. ssm-api does no key validation of its own; the error surfaces from sing-shadowsocks (§3.1).
- **SNI for ShadowTLS/REALITY.** Does the deployed `SHADOWTLS_SNI` support TLS 1.3 (strict mode), and what does it send post-handshake (OpenSSL's two tickets vs Go's)?
- **Multiplex padding.** Whether turning on sing-mux `padding` ([`shared/multiplex.md:32-34`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/multiplex.md?plain=1#L32-L34)) on the ShadowTLS path meaningfully blunts TLS-in-TLS detection. USENIX 2024 suggests partly; nothing sing-box-specific was measured.
- **`gecko` obfs design.** Not traced beyond the packet-size fields.
- **Raw SS UDP port.** It stays published for `shadowsocks-udp`. Whether to keep it (fully random UDP, unaffected per the 2023 paper) or route UDP only via UoT is a product decision.
- **Live tests.** None were done. A cheap one: remove the `/tcp` mapping, confirm `shadowsocks-tcp` and `shadowsocks-uot` still pass urltest.

## Sources

sing-box v1.14.2 (primary):
- Tag: https://github.com/SagerNet/sing-box/tree/v1.14.2 (`docs/changelog.md`; `docs/configuration/inbound/{shadowtls,shadowsocks,trojan,anytls,hysteria2,tuic,naive}.md`; `docs/configuration/outbound/{vless,hysteria2,naive}.md`; `docs/configuration/shared/{v2ray-transport,multiplex}.md`; `docs/configuration/service/ssm-api.md`; `docs/manual/misc/anytls-client-metadata.md`; `protocol/shadowsocks/{inbound,inbound_multi}.go`; `protocol/naive/inbound.go`; `protocol/anytls/inbound.go`; `common/tls/reality_server.go`; `option/anytls.go`; `go.mod`)
- Rendered docs: https://sing-box.sagernet.org/configuration/inbound/shadowtls/ , https://sing-box.sagernet.org/changelog/
- sing-shadowsocks v0.2.8: https://github.com/SagerNet/sing-shadowsocks/tree/v0.2.8/shadowaead_2022

Protocol specs and reference implementations (primary):
- ShadowTLS v3: https://github.com/ihciah/shadow-tls/blob/02dd0bc/docs/protocol-v3-en.md
- REALITY: https://github.com/XTLS/REALITY/blob/3c98159/README.en.md
- XTLS Vision design: https://github.com/XTLS/Xray-core/discussions/1295 ; releases https://github.com/XTLS/Xray-core/releases/tag/v1.7.0 , https://github.com/XTLS/Xray-core/releases/tag/v1.8.0
- Hysteria 2 protocol: https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md
- AnyTLS: https://github.com/anytls/anytls-go/blob/fd6167a/README.md , `docs/faq.md`, `docs/protocol.md`
- NaiveProxy: https://github.com/klzgrad/naiveproxy/blob/11c798a9/README.md
- Shadowsocks 2022 (SIP022): https://github.com/Shadowsocks-NET/shadowsocks-specs/blob/20b4952e/2022-1-shadowsocks-2022-edition.md

Papers (primary):
- Wu et al., "How the Great Firewall of China Detects and Blocks Fully Encrypted Traffic", USENIX Security 2023: https://gfw.report/publications/usenixsecurity23/en/
- Alice et al., "How China Detects and Blocks Shadowsocks", IMC 2020: https://gfw.report/publications/imc20/en/
- Xue et al., "Fingerprinting Obfuscated Proxy Traffic with Encapsulated TLS Handshakes", USENIX Security 2024: https://www.usenix.org/conference/usenixsecurity24/presentation/xue-fingerprinting (abstract page; the PDF download timed out)
- GFW Report et al., QUIC SNI censorship, USENIX Security 2025: https://gfw.report/publications/usenixsecurity25/en/
- Wang et al., "Chasing Shadows: A security analysis of the ShadowTLS proxy", FOCI 2023, via https://github.com/net4people/bbs/issues/322 (paper PDF link returned 404 on 2026-09-29)

net4people/bbs (original reporters; anecdotal unless noted):
- #129 Oct 2022 TLS blocking (GFW Report): https://github.com/net4people/bbs/issues/129
- #136 modified Shadowsocks (GFW Report): https://github.com/net4people/bbs/issues/136
- #181 Iran UDP: https://github.com/net4people/bbs/issues/181 ; #264 China QUIC: https://github.com/net4people/bbs/issues/264
- #303 archived tools: https://github.com/net4people/bbs/issues/303 ; #502 TUIC restart: https://github.com/net4people/bbs/issues/502
- #438 REALITY detection: https://github.com/net4people/bbs/issues/438 ; #481 Aparecium: https://github.com/net4people/bbs/issues/481 (PoC: https://github.com/ban6cat6/aparecium)
- #546 Russia TLS policing: https://github.com/net4people/bbs/issues/546 ; #668 SNI-to-DNS check: https://github.com/net4people/bbs/issues/668 (ntop: https://www.ntop.org/when-snis-cannot-be-trusted/)

Vendor docs: Cloudflare WebSockets https://developers.cloudflare.com/network/websockets/ , gRPC https://developers.cloudflare.com/network/grpc-connections/

Repo files read: `CONTEXT.md`, `docker-compose.yaml`, `scaffolds/Dockerfile`, `scaffolds/entrypoint.sh`, `scaffolds/server/inbounds.json`, `scaffolds/client/outbounds.json`, `docs/research/{magicdns-headscale,sing-box-tls}.md`.
