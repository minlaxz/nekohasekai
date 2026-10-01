# Cloudflare WARP under DPI censorship, and chaining WARP behind a proxy in sing-box

Research note, 2026-10-01. Checked against these sources:

- **sing-box v1.14.2**, commit `af6e64c`. Prefix: `https://github.com/SagerNet/sing-box/blob/v1.14.2/`. These are the same pinned versions used in `docs/research/sing-box-dpi-resistant-protocols.md`.
- **wgcf v2.3.0** (ViRb3/wgcf, latest tag on 2026-10-01), commit `ace873c`. Prefix: `https://github.com/ViRb3/wgcf/blob/v2.3.0/`.
- **WireGuard protocol page**, https://www.wireguard.com/protocol/, fetched 2026-10-01.
- **Cloudflare One Client firewall doc**, https://developers.cloudflare.com/cloudflare-one/team-and-resources/devices/cloudflare-one-client/deployment/firewall/, fetched 2026-10-01.
- **Cloudflare blog posts on MASQUE** (2023 consumer, 2024 Zero Trust).
- **net4people/bbs issues**. These are anecdotal reports, not measurements.

Anything not read directly in source or official docs is marked **inferred** or **unverified**. No config was changed and nothing was tested live.

Scope: this note covers WARP specifically. It builds on `docs/research/sing-box-dpi-resistant-protocols.md` and does not repeat it. That note covers which protocol to use on the censored leg (Reality, Hysteria2, ShadowTLS + SS, and the others).

## Questions

1. Can DPI censorship block Cloudflare WARP? What gives it away?
2. Flow A: client → proxy (VLESS/SS) → VPS → WARP. What does the censor see, and what does WARP add?
3. Flow B: the client runs the WARP WireGuard endpoint itself and uses a proxy outbound as its `detour`. Does sing-box support this, and how does it compare with Flow A?

## Short answer / recommendation

- **Yes, WARP is easy to block.**
  - **WireGuard mode** has a fixed handshake: type byte `1`, three zero bytes, and a 148-byte initiation (§1.1).
  - **Endpoints:** WARP uses a few published IP ranges on fixed ports (§1.2). A censor does not need DPI at all; an IP/port block is enough.
  - **Real-world blocking** has been reported for WARP and for WireGuard generally in Russia and Iran (§1.4, anecdotal). The repo owner confirms WireGuard is blocked in Myanmar (§1.4).
- **WARP is not a censorship-evasion tool.** Use it as the *exit* behind a DPI-resistant leg. On that path the censor sees only the leg to your VPS.
- **Flow A (WARP on the VPS) is the default choice.**
  - **Changes:** one server change, `scaffolds/server/endpoints.json` plus `route.json`.
  - **Clients:** no client changes.
  - **Exit IP:** sites see a Cloudflare IP, not the VPS IP.
  - **Effect on censorship:** none.
- **Flow B (WARP on the client, detoured through the proxy) works.** sing-box dial fields support `detour` on the WireGuard endpoint (§3).
  - **Use it when:** you do not trust the VPS host, or each user needs their own WARP identity.
  - **Costs:** worse throughput and a smaller MTU.
  - **Head-of-line blocking:** if the outer leg is TCP (Reality, ShadowTLS), the WireGuard UDP inside it stalls on packet loss.
  - **Better outer leg for Flow B:** Hysteria2 (UDP).
- **The repo today does not use WARP.**
  - The server runs ShadowTLS + SS with `final: direct-out` and `endpoints: []` (`scaffolds/server/route.json`, `scaffolds/server/endpoints.json`).
  - `unwarp()` in `api/app/utils.py` is unrelated. It is the method that builds a user's client config.

---

## 1. Why DPI can block WARP

### 1.1 WireGuard handshake fingerprint

The protocol page defines the first handshake message:

```
msg = handshake_initiation {
    u8 message_type
    u8 reserved_zero[3]
    u32 sender_index
    u8 unencrypted_ephemeral[32]
    u8 encrypted_static[AEAD_LEN(32)]
    u8 encrypted_timestamp[AEAD_LEN(12)]
    u8 mac1[16]
    u8 mac2[16]
}
...
msg.message_type = 1
msg.reserved_zero = { 0, 0, 0 }
```

- **Size:** with a 16-byte AEAD tag, the message is 1+3+4+32+48+28+16+16 = **148 bytes**.
- **Fingerprint:** a UDP payload of exactly 148 bytes that starts with `01 00 00 00` is a strong single-packet match. This is **inferred** from the format; no DPI vendor rule was read.
- **No obfuscation:** WireGuard has no obfuscation layer.
- **WARP's `reserved` bytes:** WARP clients put non-zero `reserved` bytes in the handshake. sing-box exposes these bytes as `peers.reserved` ([`docs/configuration/endpoint/wireguard.md:30,119-121`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/endpoint/wireguard.md?plain=1#L119-L121)). Their WARP meaning (a per-device client ID) is **unverified**; wgcf v2.3.0 does not mention it. Either way, they do not hide the message: the type byte and the length are still fixed.

### 1.2 Fixed ingress IPs and ports

From the Cloudflare One Client firewall doc ("WARP ingress IP"):

| Mode | IPv4 | IPv6 | Default port | Fallback ports |
|---|---|---|---|---|
| WireGuard | `162.159.193.0/24` | `2606:4700:100::/48` | UDP 2408 | UDP 500, 1701, 4500 |
| MASQUE | `162.159.197.0/24` | `2606:4700:102::/48` | UDP 443 | UDP 500, 1701, 4500, 4443, 8443, 8095; TCP 443 (HTTP/2 fallback) |

- The doc also says `162.159.192.0/24` "is used for the consumer WARP client (1.1.1.1 with WARP)".
- The table is written for the Zero Trust client. That consumer WARP uses the same ports is **inferred**.
- The doc says the client overrides whatever `engage.cloudflareclient.com` resolves to with these IPs. So blocking those ranges blocks the client, whatever DNS returns.

### 1.3 Registration API and MASQUE

- **Registration:** wgcf registers against `https://api.cloudflareclient.com` ([`cloudflare/api.go:24`](https://github.com/ViRb3/wgcf/blob/v2.3.0/cloudflare/api.go#L24)). If the censor blocks that host, a new device cannot register.
  - This only stops *new* registrations. An already generated profile keeps working until the ingress is blocked (**inferred**).
- **MASQUE:** MASQUE carries the tunnel over HTTP/3 (QUIC) ([2023 blog](https://blog.cloudflare.com/masque-building-a-new-protocol-into-cloudflare-warp/), [2024 blog](https://blog.cloudflare.com/zero-trust-warp-with-a-masque/)).
  - **QUIC SNI:** the QUIC Initial packet is encrypted with keys anyone can derive, so DPI can read its SNI. China has done this since 2024; see the QUIC SNI paper cited in `sing-box-dpi-resistant-protocols.md` §2.4.
  - **Which SNI WARP uses:** **unverified**.
  - **Ingress IPs:** they are fixed as well (§1.2), so an IP block works on MASQUE too.

### 1.4 Reported blocking (anecdotal)

- [net4people/bbs#464](https://github.com/net4people/bbs/issues/464) (2025-03, eastern Russia): links an ntc.party report that "The WARP VPN and Cloudflare DoH are both blocked".
- [net4people/bbs#140](https://github.com/net4people/bbs/issues/140) (2022-10, Iran): "WireGuard seems to be completely banned in Iran. No handshake is happening with servers outside the country."
- Myanmar: the repo owner confirmed on 2026-10-01 that WireGuard is blocked on their networks. This is a first-hand user report, not a measurement. Which method is used (handshake fingerprint, IP/port, or blanket UDP throttling) is **unverified**. Plain WARP in WireGuard mode is therefore not usable there; MASQUE mode was not tested.

## 2. Flow A: WARP on the VPS

```
Client ──ShadowTLS+SS / VLESS+Reality──▶ VPS (sing-box) ──WireGuard──▶ WARP ──▶ Internet
        └ only this leg crosses the censor ┘            └ datacenter to Cloudflare, not inspected ┘
```

- **Censor's view:** the censor sees only leg 1. How well that leg resists DPI is covered in the protocol note; WARP changes nothing there.
- **What WARP adds:** the exit IP is Cloudflare's, not the VPS's. This helps with sites that block or CAPTCHA datacenter ranges and with geo-locked services.
  - **Not verified:** that Cloudflare's IPs actually get fewer CAPTCHAs.
- **Server change** (sing-box 1.14):

```jsonc
// scaffolds/server/endpoints.json
"endpoints": [{
  "type": "wireguard",
  "tag": "warp",
  "address": ["<Address from wgcf-profile.conf>"],
  "private_key": "<PrivateKey from wgcf-profile.conf>",
  "mtu": 1280,
  "peers": [{
    "address": "162.159.192.1",
    "port": 2408,
    "public_key": "<PublicKey from wgcf-profile.conf>",
    "allowed_ips": ["0.0.0.0/0", "::/0"]
  }]
}]
// scaffolds/server/route.json: "final": "warp", or one rule with "outbound": "warp" for selected domains
```

Notes on the snippet:

- **Profile source:** run `wgcf register && wgcf generate`.
- **Peer public key:** comes from the registration API response, not a constant ([`cmd/generate/generate.go:55-65`](https://github.com/ViRb3/wgcf/blob/v2.3.0/cmd/generate/generate.go#L55-L65)). Copy it from the profile.
- **MTU:** wgcf writes `MTU = 1280` "just like the official Android app" ([`README.md:43-44`](https://github.com/ViRb3/wgcf/blob/v2.3.0/README.md?plain=1#L43-L44), [`wireguard/profile.go:15`](https://github.com/ViRb3/wgcf/blob/v2.3.0/wireguard/profile.go#L15)). sing-box's own default is `1408` ([`endpoint/wireguard.md:58-62`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/endpoint/wireguard.md?plain=1#L58-L62)), so set 1280 explicitly.
- **Peer address:** use an IP literal so the endpoint needs no DNS resolver. `162.159.192.1` sits in the consumer range from §1.2. That this exact host answers is **unverified**; the profile's `Endpoint` is authoritative.
- **Interaction with Full mode:** if `final` becomes `warp`, all server egress goes through WARP, including clash_api UI downloads. `external_ui_download_detour` is pinned to `direct-out` (`scaffolds/server/experimental.json`), so the UI download is unaffected.

## 3. Flow B: WARP on the client, detoured through the proxy

```
Client sing-box
 └─ WG endpoint "warp" ──detour──▶ proxy outbound ──▶ VPS ──UDP──▶ WARP ──▶ Internet
    censor sees the proxy leg       VPS sees only WireGuard ciphertext
```

- **Support:** the WireGuard endpoint accepts Dial Fields ([`endpoint/wireguard.md:133`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/endpoint/wireguard.md?plain=1#L133)). Dial Fields include `detour`: "The tag of the upstream outbound. If enabled, all other fields will be ignored." ([`shared/dial.md:68-72`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/dial.md?plain=1#L68-L72)).
- **UDP over VLESS:** the VLESS outbound carries UDP. `packet_encoding` defaults to `xudp` ([`outbound/vless.md:62-70`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/outbound/vless.md?plain=1#L62-L70)), so nothing needs to be set.
- **UDP in this repo:** the repo's client already has UDP-capable outbounds (`shadowsocks-udp`, and `shadowsocks-uot` over ShadowTLS; see the protocol note §1).
- **VPS side:** no change. It forwards the UDP to the WARP ingress through `direct-out`.

```jsonc
"endpoints": [{
  "type": "wireguard",
  "tag": "warp",
  "address": ["<from profile>"],
  "private_key": "<from profile>",
  "mtu": 1200,              // inferred: leaves room for the outer proxy's overhead
  "peers": [{ "address": "162.159.192.1", "port": 2408,
              "public_key": "<from profile>", "allowed_ips": ["0.0.0.0/0", "::/0"] }],
  "detour": "<proxy outbound tag>"
}]
```

### 3.1 Comparison

| | Flow A: WARP on the VPS | Flow B: WARP on the client |
|---|---|---|
| Censor sees | proxy leg only | proxy leg only |
| VPS can read traffic | yes (after the proxy terminates) | no, only WireGuard ciphertext |
| WARP account | one, shared | one per device/user |
| Config changes | one server file | every client; keys in the client config |
| Throughput | one tunnel on the client | two stacked tunnels, smaller MTU, more client CPU (**inferred**) |
| Lossy link | normal | over a TCP outer leg, WireGuard UDP inherits TCP head-of-line blocking (**inferred**) |

- **Default:** Flow A.
- **When Flow B:** only when the VPS host is untrusted or per-user WARP identity matters.
- **Outer leg for Flow B:** prefer a UDP outer leg (Hysteria2). `shadowsocks-udp` is fully encrypted UDP, which is the weakest choice against DPI (protocol note §2.1).
- **API impact:** in this repo, Flow B would need the API to inject per-user WARP keys into `endpoints`, next to `apply_mesh` in `api/app/utils.py`. That is new API surface; Flow A needs none.

## Open questions / unknowns

- The exact meaning of WARP's `reserved` bytes, and whether WARP drops handshakes that have zero `reserved`.
- The SNI that consumer WARP's MASQUE sends.
- How Myanmar blocks WireGuard, and whether WARP's MASQUE mode survives there.
- Whether `162.159.192.1:2408` is still a valid consumer endpoint, or whether profiles now point elsewhere.

## Sources

- WireGuard protocol: https://www.wireguard.com/protocol/
- Cloudflare One Client firewall: https://developers.cloudflare.com/cloudflare-one/team-and-resources/devices/cloudflare-one-client/deployment/firewall/
- Cloudflare blog, MASQUE (consumer, 2023): https://blog.cloudflare.com/masque-building-a-new-protocol-into-cloudflare-warp/
- Cloudflare blog, Zero Trust WARP with MASQUE (2024): https://blog.cloudflare.com/zero-trust-warp-with-a-masque/
- sing-box v1.14.2 docs: `endpoint/wireguard.md`, `outbound/vless.md`, `shared/dial.md` (links inline)
- wgcf v2.3.0: `README.md`, `cloudflare/api.go`, `wireguard/profile.go`, `cmd/generate/generate.go` (links inline)
- net4people/bbs #464: https://github.com/net4people/bbs/issues/464 ; #140: https://github.com/net4people/bbs/issues/140

Repo files read: `api/app/utils.py`, `scaffolds/server/{endpoints,route,outbounds,inbounds,experimental}.json`, `docs/research/{magicdns-headscale,sing-box-dpi-resistant-protocols}.md`.
