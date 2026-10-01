# Hysteria2: a proxy that looks like an HTTP/3 website

Applies to: sing-box `hysteria2` inbound (the server). Checked against sing-box 1.14.

See also: [inbound-tls](inbound-tls.md) for the `tls` block, which Hysteria2 cannot run without.

## One idea

Hysteria2 = **a proxy tunnel inside QUIC (UDP), dressed up as an ordinary HTTP/3 web server.**

- Someone with the right password gets a fast tunnel.
- Everyone else (a browser, a censor's probe, a wrong password) gets a normal web page.

```
                         UDP port, QUIC + TLS 1.3
 client ──────────────────────────────────────────▶ sing-box hysteria2
   POST /auth  Hysteria-Auth: <password>             │
                                                     ├─ password matches  → "233 HyOK" → tunnel open
                                                     └─ anything else     → masquerade web page (or 404)
```

Three words to know first:

- **QUIC**: a transport that runs over UDP instead of TCP. It always encrypts with TLS 1.3. HTTP/3 is HTTP on top of QUIC.
- **Congestion control**: the rule that decides how fast to send. Normal TCP slows down when packets get lost. On a lossy or throttled link that makes everything crawl.
- **Brutal**: Hysteria's own congestion control. It sends at a fixed rate you give it and does **not** slow down for loss. It sends extra to make up for lost packets. **BBR** is the polite alternative. It measures the link by itself and needs no number.

## Why it exists

### Without Hysteria2 (a TCP proxy on a lossy link)

```
 client ══ TCP ══▶ [ lossy / throttled path, 5% loss ] ══ TCP ══▶ server
                         │
                         └─ every loss: TCP halves its speed, waits, ramps up slowly
```

Consequences:

- Throughput falls far below what the link can carry.
- Long-distance links (high RTT) recover even more slowly.
- A plain TLS-over-TCP proxy can still be fingerprinted by timing and handshake shape.

### With Hysteria2

```
 client ══ QUIC/UDP ══▶ [ same lossy path ] ══ QUIC/UDP ══▶ server
                │
                └─ Brutal: keep sending at e.g. 100 Mbit/s, resend lost packets, no back-off
```

Consequences:

- Speed stays near the number you set, even with loss.
- The traffic is QUIC, which looks like HTTP/3 from Google, Cloudflare and others.
- A wrong guess at the speed hurts. If you set Brutal too high you get a slow, unstable link and wasted data.
- Some networks block or throttle all UDP. On those networks Hysteria2 does not work at all, and a TCP protocol is the only choice.

## Minimal server

```jsonc
{
  "type": "hysteria2",
  "tag": "hy2-in",
  "listen": "::",
  "listen_port": 8443,
  "users": [
    { "name": "alice", "password": "long-random-secret" }
  ],
  "tls": {
    "enabled": true,
    "server_name": "hy2.example.com",
    "certificate_path": "/etc/sing-box/cert.pem",   // ECDSA or RSA, not Ed25519
    "key_path": "/etc/sing-box/key.pem"
  },
  "masquerade": {
    "type": "proxy",
    "url": "https://www.example.com",
    "rewrite_host": true
  }
}
```

The only required fields are `listen`, `listen_port`, `users` and `tls`. All the others are optional.

## Every field

### Fields at a glance

| Field | Type | Default | Since |
|---|---|---|---|
| `listen`, `listen_port` | string, integer | `listen` required | |
| `up_mbps`, `down_mbps` | integer (Mbit/s) | unset = no limit | |
| `obfs.type` | `salamander` / `gecko` | no obfs (omit object) | `gecko` 1.14.0 |
| `obfs.password` | string | required if `obfs` present | |
| `obfs.min_packet_size`, `max_packet_size` | integer (bytes) | `512`, `1200` | 1.14.0, gecko only |
| `users[].name`, `users[].password` | string | empty | |
| `ignore_client_bandwidth` | boolean | `false` | meaning changed 1.11.0 |
| `tls` | inbound TLS object | **required** | |
| `masquerade` | URL string or object | none = 404 | object form 1.11.0 |
| `bbr_profile` | `conservative` / `standard` / `aggressive` | `standard` | 1.14.0 |
| `brutal_debug` | boolean | `false` | |
| `realm` | object | none | 1.14.0 |
| QUIC tuning (`idle_timeout`, `keep_alive_period`, ...) | various | library defaults | shared since 1.14.0 |

### `listen` / `listen_port`

The address and the **single UDP port** the server waits on. `"::"` means all addresses.

- UDP only. The `tcp_*` listen fields do nothing here.
- One port, not a range. Port hopping (the client jumps between many ports to dodge per-port throttling) works only if a firewall rule on the server sends the whole range to this one port. The client side of port hopping is the outbound's `server_ports`.
- `udp_fragment` defaults to `true` for this inbound, even though the shared docs show `false`.
- `udp_timeout` (default `5m`) is how long an idle proxied UDP session stays open.

### `users`

```jsonc
"users": [
  { "name": "alice", "password": "secret-a" },
  { "name": "bob",   "password": "secret-b" }
]
```

- **The password alone identifies the user.** The server looks up the password the client sends. `name` is used only in logs and in routing rules that match on `user`.
- **The password is not the TLS key.** TLS still protects the password on the wire, so nobody on the path can read it.
- Two users with the same password: the last one wins, and the first name never shows up in logs.
- Never leave a password empty. A client that sends an empty password could then log in.
- sing-box has no `user:pass` mode. If a client of the official Hysteria server logs in as `alice:secret`, put the literal string `"alice:secret"` as the password.

### `tls`

Required. If it is missing or `enabled` is false, the server will not start and logs `TLS required`.

Why: QUIC has no plaintext mode. Its handshake is TLS 1.3. So no certificate means no QUIC, and no QUIC means no Hysteria2. A front proxy (Caddy, nginx) cannot terminate TLS for it either.

- `alpn` defaults to `h3`, which is what real HTTP/3 servers offer. If you change it, the client must offer the same value.
- Use an **ECDSA or RSA** certificate. Since 1.14.0, sing-box clients copy Chrome's QUIC handshake by default, and that handshake fails against Ed25519 certificates.

Full field list: [inbound-tls](inbound-tls.md).

### `up_mbps` / `down_mbps`

Speeds in Mbit/s, seen **from the server's side**:

```
              up_mbps (server sends)
 server ═══════════════════════════════▶ client     = client's download
 server ◀═══════════════════════════════ client     = client's upload
              down_mbps (server receives)
```

- `up_mbps` caps how fast the server sends to each client.
- `down_mbps` is sent to the client during login as "you may upload this fast".
- They only apply to **Brutal**. A connection that runs on BBR ignores them. They are **not** a general rate limiter.

Brutal or BBR? Both sides must give a number:

```
 client sets down_mbps?  ── no  ──▶ BBR in BOTH directions (sing-box)
        │
        yes
        ▼
 server sends with Brutal at min(client down_mbps, server up_mbps)
 client uploads with Brutal at min(server down_mbps, client up_mbps)
        (client up_mbps unset → client uploads with BBR)
```

Consequences:

- Want Brutal? Set `up_mbps` **and** `down_mbps` on the client to the link's real speed.
- Unsure of the real speed? Leave them all out and let BBR measure the link. A wrong Brutal number is worse than BBR.
- The official Hysteria server differs here. If the client gives no download rate, it mixes the two: one direction uses Brutal and the other uses BBR. sing-box uses BBR both ways.

### `ignore_client_bandwidth`

Boolean, default `false`. Its effect depends on whether `down_mbps` is set:

| `down_mbps` on server | `ignore_client_bandwidth: true` does |
|---|---|
| unset | Ignores the client's numbers. Forces **BBR both ways** for every client. |
| set | Clients that send a rate get Brutal as normal. Clients that want BBR are **rejected**: they get the masquerade page instead of a login. |

Consequences:

- Use it with no `*_mbps` set when you want "no Brutal on my server, ever". For example, Brutal is unfair to other users on a shared VPS.
- With `down_mbps` set, it does the opposite of what its name suggests. Clients that want BBR can no longer connect.
- The docs say it "conflicts" with `up_mbps`/`down_mbps`. sing-box does not check this and accepts all three together.

### `obfs`

Hides the fact that the traffic is QUIC at all.

```jsonc
"obfs": { "type": "salamander", "password": "another-shared-secret" }
```

- `type`:
  - `salamander`: puts an 8-byte random salt in front of every packet, then XORs the packet with a key made from `BLAKE2b-256(password + salt)`. The result looks like random UDP.
  - `gecko` (1.14.0, experimental): Salamander, plus it splits the QUIC handshake into randomly sized, padded pieces. `min_packet_size` / `max_packet_size` set the piece sizes (default `512`–`1200`, ceiling `2048`).
- `password`: shared secret. It must be the same on client and server, and it is separate from the user password. If it is empty, the server will not start.
- No obfs? **Leave out the whole `obfs` object.** `"type": ""` is a parse error, even though the docs say "disabled if empty".

The trade-off:

```
 WITHOUT obfs                               WITH obfs
 ┌──────────────────────────────┐           ┌──────────────────────────────┐
 │ looks like: HTTP/3 website   │           │ looks like: random UDP noise │
 │ probe gets: a web page       │           │ probe gets: silence          │
 │ blocked by: "block all QUIC" │           │ blocked by: "block odd UDP"  │
 │ masquerade: works            │           │ masquerade: unreachable      │
 └──────────────────────────────┘           └──────────────────────────────┘
```

Consequences:

- Turn on obfs only when the network blocks QUIC or HTTP/3 but still allows other UDP.
- With obfs on, a normal browser cannot reach the server, so `masquerade` does nothing.
- Salamander has no integrity check. A wrong password does not cause a clear error. The packets decode to garbage and are silently dropped, so the client just times out.

### `masquerade`

Decides what a visitor who is **not** a valid client sees. The server shows it for:

1. any HTTP/3 request that is not the Hysteria login (a browser opening `/`),
2. a login with a wrong password,
3. a client rejected by `ignore_client_bandwidth`.

#### Without masquerade

```
 prober ── GET / (HTTP/3) ──▶ server ──▶ 404 Not Found, for every path
```

Consequences: a site where every page is 404 is unusual, and a censor can learn to spot it. The protocol spec asks servers to host real content.

#### With masquerade

```
 prober ── GET / (HTTP/3) ──▶ server ── proxy ──▶ https://www.example.com
                               ◀────── real page ──────┘
```

Consequences: to a prober the server looks like a real website served over HTTP/3.

There are two ways to write it.

**String form**, the short version:

| Value | Means |
|---|---|
| `"file:///var/www"` | serve files from `/var/www` |
| `"https://www.example.com"` | reverse-proxy that site (`rewrite_host` = `false`) |

Other schemes fail to parse. An empty string `""` fails to parse too, so leave the field out instead.

**Object form** (since 1.11.0). Use exactly one `type`:

- `file`: a static file server.
  - `directory`: the root folder. If the folder has no `index.html`, visitors see a file listing, which is an odd thing for a website to show.
- `proxy`: a reverse proxy to a real site.
  - `url`: the target site.
  - `rewrite_host` (default `false`): sends the target's own hostname in the `Host` header. Set it to `true` for any public site or CDN, because those servers choose the site by `Host`.
  - If the target is down, visitors get a bare `502`.
- `string`: a fixed reply.
  - `status_code`: for example `200`. If it is unset, the server sends `200`.
  - `headers`: a map of header name to value.
  - `content`: the body text.

Masquerade works only over HTTP/3 on the same UDP port. sing-box does not open a matching TCP website, which the official server can do.

### `bbr_profile` (1.14.0)

`conservative`, `standard` (default) or `aggressive`. It sets how hard BBR pushes. It only affects connections that end up on BBR. This setting is not negotiated, so set it on both sides.

### `brutal_debug`

`true` logs Brutal's internal numbers (rates, loss) for debugging. It prints nothing for BBR connections.

### `realm` (1.14.0)

Lets a server behind NAT (with no public IP) accept clients. The server registers with a "Realm" rendezvous service and uses STUN and UDP hole punching. Required sub-fields are `server_url`, `realm_id` and `stun_servers`. A server with a public IP does not need it.

### QUIC tuning fields

`initial_packet_size`, `disable_path_mtu_discovery`, `idle_timeout`, `keep_alive_period`, `stream_receive_window`, `connection_receive_window`, `max_concurrent_streams`. These have been shared with the other QUIC protocols since 1.14.0. Leave them unset unless you are tuning a specific problem. The defaults are Hysteria's own.

## Decision

```
Does the network let UDP through?
├─ no  → Hysteria2 cannot work; use a TCP protocol
└─ yes
   ├─ QUIC / HTTP/3 itself blocked? → add obfs (salamander); masquerade becomes useless
   └─ QUIC allowed                 → no obfs; set masquerade to a real site
        │
        Do you know the real link speed?
        ├─ yes → client sets up_mbps + down_mbps (Brutal); server *_mbps as per-user caps
        └─ no  → leave all *_mbps out (BBR)
```

## References

- sing-box Hysteria2 inbound: https://sing-box.sagernet.org/configuration/inbound/hysteria2/
- sing-box listen fields: https://sing-box.sagernet.org/configuration/shared/listen/
- sing-box QUIC fields: https://sing-box.sagernet.org/configuration/shared/quic/
- Hysteria2 protocol spec: https://v2.hysteria.network/docs/developers/Protocol/
- Official Hysteria server config (Brutal vs BBR, obfs, masquerade): https://v2.hysteria.network/docs/advanced/Full-Server-Config/
- RFC 9001, QUIC uses TLS: https://www.rfc-editor.org/rfc/rfc9001
