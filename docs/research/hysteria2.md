# sing-box Hysteria2 inbound: every field, and what it does on the wire

Research note, 2026-10-01. Checked against these pinned versions:

- **sing-box v1.14.2** (latest stable; `scaffolds/Dockerfile` pulls `ghcr.io/sagernet/sing-box:latest`), commit `af6e64c`. Prefix: `https://github.com/SagerNet/sing-box/blob/v1.14.2/`. Documentation claims cite the docs bundled in that tag. The live page `https://sing-box.sagernet.org/configuration/inbound/hysteria2/` was fetched 2026-10-01 and has the same field anchors.
- **sing-quic** `6a3a24d` (pseudo-version `v0.7.1-0.20260924092235-6a3a24d65b99`, pinned in sing-box `go.mod:53`). Prefix: `https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/`. This is the library that actually implements the Hysteria2 server for sing-box: authentication, congestion control choice, obfuscation.
- **sagernet/quic-go v0.61.0-sing-box-mod.7** (sing-box `go.mod:47`), only for one HTTP/3 detail in §6.
- **apernet/hysteria** `4a0f102` (release app/v2.12.3), the same commit as `sing-box-dpi-resistant-protocols.md`. Prefix: `https://github.com/apernet/hysteria/blob/4a0f102/`. `PROTOCOL.md` there is the protocol spec; the rendered copy at `https://v2.hysteria.network/docs/developers/Protocol/` was fetched 2026-10-01 and has the same text.
- **Hysteria "Full Server Config"** page, `https://v2.hysteria.network/docs/advanced/Full-Server-Config/`, fetched 2026-10-01. It is not versioned, so it is cited by section name.
- RFC 9001 (QUIC-TLS).

Source links point at a tag (or commit) plus a line anchor. Anything not read directly in source or official docs is marked **inferred** or **unverified**. Results marked **checked** come from running `sing-box check` with the local macOS binary (**v1.14.0**, `~/Downloads/sing-box/sing-box`) against small test configs with a throwaway self-signed certificate. `check` parses the config and builds the inbound, but it does not start a listener, so nothing about live traffic was tested.

Scope: the Hysteria2 **inbound** (server) only. The outbound is mentioned only where the two sides must agree. How Hysteria2 compares with other DPI-resistant protocols is in `docs/research/sing-box-dpi-resistant-protocols.md` §3.4, and the shared `tls` block is in `docs/research/sing-box-tls.md`. This note does not repeat them. No repo config was changed.

## Questions

1. What fields does the Hysteria2 inbound have, with what type and default, and since which sing-box version?
2. What does each field do on the wire, according to the Hysteria2 protocol spec?
3. How do `up_mbps`, `down_mbps` and `ignore_client_bandwidth` decide between Brutal and BBR, and in which direction?
4. What do the obfuscators (`salamander`, `gecko`) do, and what do they break?
5. When does a visitor see the `masquerade` site, and what are the string and object forms?
6. Why is `tls` required?
7. Where does sing-box differ from the official Hysteria server?

## Short answer / recommendation

- **The minimum working inbound is `listen`, `listen_port`, `users[].password` and `tls` with a certificate.** Everything else is optional. Without `tls.enabled` the inbound refuses to start with `TLS required` (§6).
- **Bandwidth is from the server's point of view.** `up_mbps` caps what the server sends (the client's download); `down_mbps` is what the server tells the client it may upload. Both only matter when Brutal is in use. If the client sends no download rate, sing-box falls back to BBR in **both** directions (§3).
- **`ignore_client_bandwidth` has two meanings.** With `up_mbps`/`down_mbps` unset it forces BBR for every client. With them set it does the opposite of what the name says: it **rejects** clients that want BBR. The docs say the two settings "conflict", but sing-box accepts both together without an error (§3.3).
- **Obfuscation (`obfs`) and masquerade do not mix.** With `salamander` or `gecko`, the port no longer speaks real QUIC, so it cannot look like an HTTP/3 website and probers get silence. Masquerade is only useful without `obfs` (§4, §5).
- **The masquerade site is shown to anyone who fails authentication**, and also for any HTTP/3 request that is not the Hysteria auth request. If no masquerade is set, every such request gets `404 Not Found` (§5).
- **sing-box has no `userpass` auth.** A client of the official Hysteria server that logs in as `user:pass` must be given the literal password `"user:pass"` in sing-box (§7).

## 1. The field list at a glance

The structure block is at [`inbound/hysteria2.md:16-60`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L16-L60) and the Go struct is `Hysteria2InboundOptions` at [`option/hysteria2.go:17-30`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/hysteria2.go#L17-L30). Version notes come from the docs header ([`inbound/hysteria2.md:5-14`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L5-L14)) and the changelog.

| Field | Type | Default | Version note |
|---|---|---|---|
| Listen fields (`listen`, `listen_port`, ...) | see §2 | `listen` is required | shared |
| `up_mbps` | integer (Mbit/s) | `0` = no limit | |
| `down_mbps` | integer (Mbit/s) | `0` = no limit | |
| `obfs.type` | `"salamander"` or `"gecko"` | no obfuscation (omit the whole `obfs` object) | `gecko` added in 1.14.0 |
| `obfs.password` | string | none; required when `obfs` is present | |
| `obfs.min_packet_size` | integer (bytes) | `512` | since 1.14.0, gecko only |
| `obfs.max_packet_size` | integer (bytes) | `1200` | since 1.14.0, gecko only |
| `users[].name` | string | empty | |
| `users[].password` | string | empty | |
| `ignore_client_bandwidth` | boolean | `false` | behaviour changed in 1.11.0 |
| `tls` | inbound TLS object | none; **required** | shared |
| QUIC fields (`initial_packet_size`, `idle_timeout`, ...) | see §2 | library defaults | shared QUIC/HTTP2 fields since 1.14.0 |
| `masquerade` | string (URL) or object | none: 404 page | object form and `string` type since 1.11.0 |
| `bbr_profile` | `"conservative"`, `"standard"`, `"aggressive"` | `"standard"` | since 1.14.0 |
| `brutal_debug` | boolean | `false` | |
| `realm` | object | none | since 1.14.0 |

The task brief did not ask about `bbr_profile` and `realm`, but they are on the page, so they are covered briefly in §8.

## 2. Listen fields and QUIC fields

**Listen fields** are shared by all inbounds ([`shared/listen.md:29-56`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/listen.md?plain=1#L29-L56)). The ones that matter for Hysteria2:

- `listen` (string, **required**): the listen address, for example `"::"` ([`listen.md:60-64`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/listen.md?plain=1#L60-L64)).
- `listen_port` (integer): a single UDP port. It is a `uint16` ([`option/inbound.go:81`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/inbound.go#L81)), so the inbound cannot listen on a port range. The official Hysteria server can (`listen: :20000-50000`, it installs nftables/iptables redirects itself; Full Server Config, section "Listen"). With sing-box, server-side port hopping needs your own firewall redirect to the one port (**inferred**). The client side of port hopping is the outbound's `server_ports` ([`outbound/hysteria2.md:93-99`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/outbound/hysteria2.md?plain=1#L93-L99)).
- `udp_fragment` (boolean): "Enable UDP fragmentation" ([`listen.md:140-142`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/listen.md?plain=1#L140-L142)). The docs show `false`, but the Hysteria2 inbound sets its own default to `true` ([`protocol/hysteria2/inbound.go:49`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L49)); the listener uses that default only when the field is not set ([`common/listener/listener_udp.go:39-46`](https://github.com/SagerNet/sing-box/blob/v1.14.2/common/listener/listener_udp.go#L39-L46)).
- `udp_timeout` (duration, default `5m`): "UDP NAT expiration time" ([`listen.md:144-148`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/listen.md?plain=1#L144-L148)). For Hysteria2 it is how long a proxied UDP session stays open without traffic ([`inbound.go:128-133`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L128-L133)).
- `detour`, `bind_interface`, `routing_mark`, `reuse_addr`, `netns` behave as for any inbound. The `tcp_*` fields do nothing here because Hysteria2 is UDP only (**inferred**: the inbound only calls `ListenUDP`, [`inbound.go:282`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L282)).

**QUIC fields** ([`shared/quic.md`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/quic.md?plain=1), since 1.14.0) are `initial_packet_size` and `disable_path_mtu_discovery`, plus the **HTTP2 fields** `idle_timeout`, `keep_alive_period`, `stream_receive_window`, `connection_receive_window`, `max_concurrent_streams` ([`shared/http2.md:9-43`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/shared/http2.md?plain=1#L9-L43)). The changelog says these were made shared in 1.14.0 and that the old Hysteria v1 tuning fields are deprecated, to be removed in 1.16.0 ([`changelog.md:370-381`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L370-L381)). When unset, sing-quic uses its own Hysteria defaults for windows, idle timeout and keep-alive ([sing-quic `hysteria2/service.go:82-94`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L82-L94)).

## 3. Bandwidth and congestion control: `up_mbps`, `down_mbps`, `ignore_client_bandwidth`

### 3.1 Background: Brutal vs BBR

Hysteria has its own congestion control called **Brutal**. It "operates on a fixed rate model and does not reduce its speed in response to packet loss or RTT changes"; when it falls short of the target rate it measures loss and sends faster to compensate. It "only works if you know (and accurately specify) the theoretical maximum speed" of the link, and setting it too high gives "a slow, unstable connection and wasted data" (Full Server Config, section "Congestion control details"). **BBR** is an ordinary congestion control that estimates bandwidth by itself and needs no number (same section).

On the wire, the rates are negotiated in the auth request. The client sends `Hysteria-CC-RX`, its maximum receive rate in bytes per second, with `0` meaning unknown. The server answers with its own receive rate, where `0` means unlimited and `"auto"` means "use congestion control yourself" ([`PROTOCOL.md:23-55`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L23-L55)). If the client sends `0`, the server "MUST use a congestion control algorithm (e.g., BBR, Cubic)" ([`PROTOCOL.md:119-127`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L119-L127)).

### 3.2 `up_mbps` and `down_mbps`

- **Type:** integer, in Mbit/s. sing-box multiplies by 125 000 to get bytes per second ([`inbound.go:188-189`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L188-L189); [sing-quic `hysteria/protocol.go:15`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria/protocol.go#L15)).
- **Default:** empty, which means "Not limited" ([`inbound/hysteria2.md:75-81`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L75-L81)).
- **What they do, from the server's view.** The official docs put it simply: "the server's upload speed is the client's download speed, and vice versa", and the server values act as per-client speed limits (Full Server Config, section "Bandwidth"). In the sing-quic code:
  - **Server to client (`up_mbps`).** If the client sent a non-zero download rate, the server uses Brutal at that rate, capped at `up_mbps` when `up_mbps` is set ([sing-quic `service.go:295-300`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L295-L300)).
  - **Client to server (`down_mbps`).** The server sends `down_mbps` back as its `Hysteria-CC-RX` ([`service.go:308-312`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L308-L312)). The sing-box client then uploads with Brutal at the smaller of that value and its own `up_mbps`; if its own `up_mbps` is unset it uses BBR ([sing-quic `client.go:582-593`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/client.go#L582-L593)).
- **Gotcha: no client download rate means BBR both ways in sing-box.** When the client sends `Hysteria-CC-RX: 0` (it has no `down_mbps`), the sing-quic server picks BBR for its own sending and also replies `auto` ([`service.go:301-307`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L301-L307)). The client then uses BBR for uploads too, even if it set `up_mbps` (**inferred** from the two code paths above). The official docs describe a mixed mode instead (client uploads with Brutal, server sends with BBR; Full Server Config, "Congestion control details"). So a sing-box client that wants Brutal in either direction should set **both** `up_mbps` and `down_mbps`.
- **Gotcha: the server limits only apply to Brutal.** The official docs say "The server's bandwidth limit only applies to Brutal at the moment. It has no effect on BBR or Reno" (Full Server Config, "Congestion control details"). The sing-quic BBR path takes no rate argument, which agrees ([`service.go:302-305`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L302-L305)). These fields are not a general rate limiter.

### 3.3 `ignore_client_bandwidth`

- **Type:** boolean. **Default:** `false`.
- **Docs:** when `up_mbps` and `down_mbps` are not set, it "Commands clients to use the BBR CC instead of Hysteria CC". When they are set, it will "Deny clients to use the BBR CC" ([`inbound/hysteria2.md:117-125`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L117-L125)). The second meaning was introduced in 1.11.0 ([`changelog.md:2708-2710`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L2708-L2710)).
- **What the code does** ([sing-quic `service.go:288-313`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L288-L313)). The deciding value is **`down_mbps` only**, not both fields:
  - `down_mbps` unset and `ignore_client_bandwidth: true`: the server ignores the client's rate, uses BBR for sending, and replies `auto`, so the client uses BBR too. Brutal is disabled in both directions, and `up_mbps` has no effect.
  - `down_mbps` set and `ignore_client_bandwidth: true`: a client that sends a rate gets normal Brutal. A client that sends `0` (wants BBR) is logged as "BBR disabled by server" and gets the masquerade response instead of `233`, so it fails to connect.
- **Gotcha: the docs say it "conflicts" with `up_mbps`/`down_mbps`, but nothing enforces it.** A config with all three set passes `sing-box check` (**checked**).
- **Gotcha: differs from the official server.** In official Hysteria, `ignoreClientBandwidth` always means "disregard any bandwidth hints set by clients and use the configured non-Brutal controller", in both directions (Full Server Config, "Ignore client bandwidth"). sing-box only does that when `down_mbps` is unset.
- **Minor (inferred):** in the reject path, sing-quic marks the session as authenticated before it serves the masquerade ([`service.go:288-294`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L288-L294)). A real client disconnects on any status other than 233 ([`PROTOCOL.md:61`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L61)), so this should not matter in practice. Not tested.

### 3.4 `brutal_debug`

- **Type:** boolean. **Default:** `false`.
- "Enable debug information logging for Hysteria Brutal CC" ([`inbound/hysteria2.md:196-198`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L196-L198)). It is passed to every Brutal sender the server creates ([`service.go:300`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L300)). It logs nothing for connections that run on BBR (**inferred**, since only the Brutal constructor receives it).

## 4. Obfuscation: `obfs`

### 4.1 Fields

- `obfs.type`: `"salamander"` or `"gecko"`. The docs say "Disabled if empty" ([`inbound/hysteria2.md:83-87`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L83-L87)), but `"type": ""` is a parse error: `unknown obfs type` (**checked**; [`option/hysteria2.go:87-99`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/hysteria2.go#L87-L99)). To disable obfuscation, **leave out the whole `obfs` object**.
- `obfs.password`: the shared secret ([`inbound/hysteria2.md:89-91`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L89-L91)). An empty password stops the inbound with `missing obfs password` ([`inbound.go:60-63`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L60-L63); **checked**). It must be identical on client and server (Full Server Config, "Obfuscation"). It is separate from the user password.
- `obfs.min_packet_size` / `obfs.max_packet_size` (since 1.14.0, gecko only, defaults `512` / `1200` bytes; [`inbound/hysteria2.md:93-107`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L93-L107)). sing-quic requires `0 < min <= max <= 2048`, otherwise `gecko: invalid packet size range` ([sing-quic `service.go:109-119`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L109-L119), [`gecko.go:16-27`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/gecko.go#L16-L27); **checked** with `min_packet_size: 1300`). The official docs state the same 2048 upper limit (Full Server Config, "Obfuscation").

### 4.2 What it does on the wire

- **Salamander.** Every QUIC packet gets an 8-byte random salt in front. The payload is XORed with `BLAKE2b-256(key + salt)`, repeated. The receiver "MUST" discard invalid packets ([`PROTOCOL.md:129-153`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L129-L153)). sing-quic implements exactly this ([`salamander.go:15`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/salamander.go#L15), [`salamander.go:47-65`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/salamander.go#L47-L65)). The result looks like random UDP, not QUIC. Note that Salamander has no integrity check of its own: a packet with the wrong key decodes to garbage, which the QUIC layer then drops (**inferred** from the code).
- **Gecko** "builds on Salamander and additionally fragments QUIC handshake packets into randomly-sized, randomly-padded chunks", and is marked experimental (Full Server Config, "Obfuscation"). In sing-quic the Gecko conn wraps a Salamander conn ([`gecko.go:55-57`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/gecko.go#L55-L57)). It is not in `PROTOCOL.md` at this commit.
- **When obfs is on, sing-quic also turns off QUIC version negotiation packets and stateless resets** ([`service.go:172-176`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L172-L176)). Both would be plain, recognisable QUIC packets (**inferred** reason).

### 4.3 Gotcha: obfs removes the HTTP/3 disguise

The official docs: "Enabling obfuscation will make your server incompatible with standard QUIC connections and it will no longer function as a valid HTTP/3 server" (Full Server Config, "Obfuscation"). By default Hysteria "mimics HTTP/3"; obfs is meant for networks that "specifically block QUIC or HTTP/3 traffic (but not UDP in general)" (same section). So it is a trade: without obfs the server looks like an HTTP/3 website and answers probes; with obfs it looks like random UDP and stays silent. The masquerade (§5) cannot be reached by a normal browser or prober once obfs is on (**inferred**; same conclusion as `sing-box-dpi-resistant-protocols.md` §3.4).

## 5. Users and authentication: `users`

- `users` (array) of `{ "name": string, "password": string }` ([`inbound/hysteria2.md:109-115`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L109-L115); [`option/hysteria2.go:116-119`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/hysteria2.go#L116-L119)). Both default to empty.
- **On the wire**, the client sends an HTTP/3 `POST /auth` with `:host: hysteria` and the password in the `Hysteria-Auth` header. On success the server answers status `233 HyOK` ([`PROTOCOL.md:23-47`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L23-L47); constants in [sing-quic `internal/protocol/http.go:9-17`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/internal/protocol/http.go#L9-L17)). Only after that does the QUIC connection carry proxy streams ([`PROTOCOL.md:63`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L63)).
- **Only the password identifies the user.** sing-quic builds a map from password to user ([sing-quic `service.go:151-157`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L151-L157)) and looks up the `Hysteria-Auth` value in it ([`service.go:282-287`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L282-L287)). `name` is used only for logs and for the `user` field in routing rules ([`inbound.go:240-242`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L240-L242)).
- **Gotchas:**
  - Two users with the same password are accepted by `check` (**checked**), but only the last one stays in the map, so the first name never appears (**inferred** from the map code).
  - An empty `users` list is also accepted (**checked**). Nobody can log in, and every request gets the masquerade (**inferred**).
  - A user with an empty password would match a client that sends an empty `Hysteria-Auth` (**inferred** from the map lookup; not tested). Do not leave passwords empty.

## 6. TLS: `tls`

- **Required** ([`inbound/hysteria2.md:127-131`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L127-L131)). The constructor returns `TLS required` if `tls` is missing or `enabled` is false ([`inbound.go:50-52`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L50-L52); [`constant/err.go:5`](https://github.com/SagerNet/sing-box/blob/v1.14.2/constant/err.go#L5); **checked**). The fields are the shared inbound TLS block, covered in `docs/research/sing-box-tls.md`.
- **Why it is required.** Hysteria2 "MUST be implemented on top of the standard QUIC transport protocol" ([`PROTOCOL.md:9-11`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L9-L11)), and QUIC always uses TLS for its handshake and keys ([RFC 9001](https://www.rfc-editor.org/rfc/rfc9001), abstract: "how Transport Layer Security (TLS) is used to secure QUIC"). There is no plaintext QUIC, so there is no Hysteria2 without a certificate. TLS terminated by a front proxy is not an option either (**inferred**).
- **ALPN.** If `tls.alpn` is not set, sing-quic sets it to `h3` ([`service.go:106-108`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L106-L108)), which is what a real HTTP/3 server offers. If you set `alpn` yourself, the client must offer a matching value (**inferred**; see `sing-box-tls.md` §11).
- **Certificate choice matters for the client.** Since 1.14.0 sing-box Hysteria2 clients parrot Chrome's QUIC handshake by default, which breaks servers with Ed25519 certificates (see `sing-box-dpi-resistant-protocols.md`, which cites [`changelog.md:559-571`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L559-L571)). Use an ECDSA or RSA certificate on the inbound.

## 7. Masquerade: `masquerade`

### 7.1 When it is reached

The spec says that to anyone without valid credentials the server "behaves just like a standard HTTP/3 web server", and that on failed auth it must either act like a web server that does not understand the request or reverse-proxy to the upstream site ([`PROTOCOL.md:17-21`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L17-L21), [`PROTOCOL.md:59`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L59)). sing-box describes `masquerade` as the "HTTP3 server behavior ... when authentication fails" ([`inbound/hysteria2.md:137-139`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L137-L139)).

In the code ([sing-quic `service.go:271-329`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L271-L329)), the masquerade handler serves:

1. any HTTP/3 request that is not `POST` to host `hysteria`, path `/auth` (for example a browser fetching `/`);
2. an auth request whose password is not in `users`;
3. the `ignore_client_bandwidth` reject case (§3.3).

If no masquerade is configured, the handler is Go's `NotFoundHandler`, so every such request gets `404` ([`service.go:103-105`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L103-L105); docs: "A 404 page will be returned if masquerade is not configured", [`inbound/hysteria2.md:148`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L148)). The spec says implementations SHOULD tell users to host real content or reverse-proxy a real site, because a bare 404 is a pattern probers can learn ([`PROTOCOL.md:21`](https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md?plain=1#L21)).

It is reachable only over QUIC/HTTP/3, and only when `obfs` is off (§4.3). The official server can also open TCP `listenHTTP`/`listenHTTPS` ports for the same content (Full Server Config, "HTTP/HTTPS Masquerading"); sing-box has no such fields. Its docs say there is "no evidence" censors check for the missing TCP site.

### 7.2 String form

`"masquerade": "<url>"` ([`inbound/hysteria2.md:141-146`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L141-L146)), parsed at [`option/hysteria2.go:145-164`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/hysteria2.go#L145-L164):

| Example | Becomes |
|---|---|
| `"file:///var/www"` | `{"type": "file", "directory": "/var/www"}` (the URL path) |
| `"http://127.0.0.1:8080"` or `"https://example.com"` | `{"type": "proxy", "url": <the string>}` (`rewrite_host` stays `false`) |

Any other scheme, **including an empty string**, is a parse error: `unknown masquerade URL scheme` (**checked** for `""` and `"ftp://x"`). The docs' structure block shows `"masquerade": ""` as a placeholder, but you cannot use it literally; omit the field instead. The string form "conflicts with" the object form ([`inbound/hysteria2.md:146`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L146)): it is one JSON value, so you use one or the other.

### 7.3 Object form

`masquerade.type` selects one of three handlers ([`inbound/hysteria2.md:150-186`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L150-L186); structs at [`option/hysteria2.go:195-208`](https://github.com/SagerNet/sing-box/blob/v1.14.2/option/hysteria2.go#L195-L208); handlers at [`inbound.go:75-116`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L75-L116)). The object form and the `string` type arrived in 1.11.0 ([`changelog.md:2700-2702`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/changelog.md?plain=1#L2700-L2702)).

- **`file`**, a static file server.
  - `directory` (string): the root directory. Environment variables are expanded. A directory that does not exist is tolerated at start-up ([`inbound.go:78-84`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L78-L84); **checked** with `/nonexistent`); visitors then get 404s (**inferred**). It uses Go's `http.FileServer`, so a directory without `index.html` shows a file listing (**inferred** from Go's documented `FileServer` behaviour; not tested). That listing is an unusual thing for a website to show.
- **`proxy`**, a reverse proxy.
  - `url` (string): the target site.
  - `rewrite_host` (boolean, default `false`): "Rewrite the `Host` header to the target URL" ([`inbound/hysteria2.md:172-174`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L172-L174)). With `false`, the upstream receives the visitor's original `Host` ([`inbound.go:90-96`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L90-L96)). For a public site on shared hosting or a CDN you almost always want `true`, because those servers pick the site by `Host` (the official docs give the same reason; Full Server Config, "Masquerade").
  - If the upstream fails, the visitor gets a bare `502` ([`inbound.go:97-99`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L97-L99)).
  - The official server also has `insecure` and `xForwarded` options here; sing-box does not.
- **`string`**, a fixed response.
  - `status_code` (integer): written only if non-zero ([`inbound.go:102-105`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L102-L105)); otherwise Go writes `200` on the first body write (**inferred**; the official server also documents `200` as its default).
  - `headers` (map of header name to string or list): added to the response. The code adds them *after* `WriteHeader`, which would drop them in Go's `net/http`, but the HTTP/3 writer in sagernet/quic-go only serialises headers on the first body write ([quic-go `http3/response_writer.go:80-98`, `:165-170`](https://github.com/sagernet/quic-go/blob/v0.61.0-sing-box-mod.7/http3/response_writer.go#L80-L98)), so they should still be sent (**inferred**; not tested live).
  - `content` (string): the body.

**Checked:** `"masquerade": {}` (no `type`) passes `check` with the 1.14.0 binary and behaves as "no masquerade", because the inbound only builds a handler when `type` is non-empty ([`inbound.go:76`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L76)). Why the option decoder does not reject the empty type was not traced.

## 8. The other 1.14.0 fields: `bbr_profile` and `realm`

- **`bbr_profile`** (since 1.14.0): `conservative`, `standard` (default) or `aggressive` ([`inbound/hysteria2.md:188-194`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L188-L194); [sing-quic `service.go:95-102`](https://github.com/SagerNet/sing-quic/blob/6a3a24d65b99/hysteria2/service.go#L95-L102)). It applies only to connections that end up on BBR (§3). The official docs say the congestion settings are "local to this endpoint and ... not negotiated", so set it on each side (Full Server Config, "Congestion").
- **`realm`** (since 1.14.0): registers the inbound with a Hysteria Realm rendezvous service so it can accept clients through NAT by STUN and UDP hole punching ([`inbound/hysteria2.md:200-282`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L200-L282)). Required sub-fields are `server_url`, `realm_id` (1–64 characters, `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`) and `stun_servers`. Optional: `token`, `stun_domain_resolver`, `ip_version` (`4` or `6`, must match `listen`, enforced at [`inbound.go:136-144`](https://github.com/SagerNet/sing-box/blob/v1.14.2/protocol/hysteria2/inbound.go#L136-L144)), `port_mapping` (UPnP/NAT-PMP, `timeout` default `10s`, `lifetime` default `10m`, IPv4 only), and `http_client`. A server with a public IP does not need it. Not researched further.

## 9. Differences from the official Hysteria server

Summarised from the sections above:

| Topic | Official Hysteria | sing-box inbound |
|---|---|---|
| Auth types | `password`, `userpass`, `http`, `command` (Full Server Config, "Authentication") | password list only; `userpass` must be written as the literal `"user:pass"` ([`inbound/hysteria2.md:62-67`](https://github.com/SagerNet/sing-box/blob/v1.14.2/docs/configuration/inbound/hysteria2.md?plain=1#L62-L67)) |
| `ignoreClientBandwidth` | always non-Brutal, both directions | forces BBR only if `down_mbps` unset; otherwise rejects BBR clients (§3.3) |
| Client without download rate | mixed: one direction Brutal, one BBR | BBR both ways (§3.2, **inferred**) |
| Bandwidth units | strings like `1 gbps` | integer Mbit/s |
| Port range listen | yes, Linux, auto firewall rules | no, single `listen_port` |
| Masquerade extras | `insecure`, `xForwarded`, TCP `listenHTTP`/`listenHTTPS` | none of these |
| Congestion choices | `bbr` or `reno` | BBR with `bbr_profile`; no Reno option found |

## 10. Minimal example

A server for this repo's style of deployment. Port `8443` is used because `docker-compose.yaml:22` already maps `443/udp` (to Caddy, per `sing-box-dpi-resistant-protocols.md`).

```jsonc
{
  "inbounds": [
    {
      "type": "hysteria2",
      "tag": "hy2-in",
      "listen": "::",
      "listen_port": 8443,

      // Optional. Leave both out for "no limit"; see §3 before setting them.
      // "up_mbps": 100,
      // "down_mbps": 50,

      "users": [
        { "name": "alice", "password": "change-me-long-random" }
      ],

      "tls": {
        "enabled": true,
        "server_name": "hy2.example.com",
        // ECDSA or RSA, not Ed25519 (§6)
        "certificate_path": "/etc/sing-box/cert.pem",
        "key_path": "/etc/sing-box/key.pem"
      },

      // Shown to probers and to failed logins. Only useful without "obfs".
      "masquerade": {
        "type": "proxy",
        "url": "https://www.example.com",
        "rewrite_host": true
      }

      // To look like random UDP instead of HTTP/3, add this and drop "masquerade":
      // "obfs": { "type": "salamander", "password": "another-long-random" }
    }
  ]
}
```

This shape (with `obfs` left out, and with `masquerade` in the string and object forms) passes `sing-box check` on v1.14.0 (**checked**). It was not started or connected to.

## Open questions / unknowns

- Server behaviour was read in source and validated with `sing-box check` only. No live client was connected, so the Brutal/BBR choices in §3 and the masquerade responses in §7 are not observed on the wire.
- Why `"masquerade": {}` is accepted when the option decoder seems to reject an empty `type` (§7.3).
- Whether `string` masquerade headers really reach the client over HTTP/3 (§7.3).
- What happens with a user whose password is empty (§5).
- Gecko's design: only the official docs' one-line description and the sing-quic constants were read; `gecko.go` was not traced, and it is not in `PROTOCOL.md` at this commit (§4.2).
- Whether sing-box's BBR uses Reno anywhere, or offers it: no option was found, but the congestion package was not read (§9).
- The local binary is 1.14.0 while the source is 1.14.2. `option/hysteria2.go` differs between the two only in realm code, not in the fields tested.

## Sources

- sing-box v1.14.2: https://github.com/SagerNet/sing-box/tree/v1.14.2 (`docs/configuration/inbound/hysteria2.md`, `docs/configuration/outbound/hysteria2.md`, `docs/configuration/shared/{listen,quic,http2}.md`, `docs/changelog.md`, `option/hysteria2.go`, `option/inbound.go`, `protocol/hysteria2/inbound.go`, `common/listener/listener_udp.go`, `constant/err.go`, `go.mod`)
- sing-box v1.14.0 `option/hysteria2.go` (diffed against v1.14.2): https://github.com/SagerNet/sing-box/blob/v1.14.0/option/hysteria2.go
- sing-box docs site, fetched 2026-10-01: https://sing-box.sagernet.org/configuration/inbound/hysteria2/
- sing-quic `6a3a24d65b99`: https://github.com/SagerNet/sing-quic/tree/6a3a24d65b99 (`hysteria2/{service,client,salamander,gecko}.go`, `hysteria2/internal/protocol/http.go`, `hysteria/protocol.go`)
- sagernet/quic-go v0.61.0-sing-box-mod.7: https://github.com/sagernet/quic-go/blob/v0.61.0-sing-box-mod.7/http3/response_writer.go
- Hysteria 2 protocol spec: https://github.com/apernet/hysteria/blob/4a0f102/PROTOCOL.md (rendered: https://v2.hysteria.network/docs/developers/Protocol/, fetched 2026-10-01)
- Hysteria Full Server Config, fetched 2026-10-01: https://v2.hysteria.network/docs/advanced/Full-Server-Config/ (sections Listen, Obfuscation, Bandwidth, Ignore client bandwidth, Congestion, Congestion control details, Authentication, Masquerade, HTTP/HTTPS Masquerading)
- RFC 9001 (Using TLS to Secure QUIC): https://www.rfc-editor.org/rfc/rfc9001
