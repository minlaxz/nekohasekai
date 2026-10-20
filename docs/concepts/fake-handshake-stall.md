# Fake-handshake stall: why "IPv6 hangs" is worse than "IPv6 fails"

Applies to: any TUN-based proxy client (sing-box, and others) whose TUN has an
IPv6 address while the path behind the proxy has no IPv6.

Assumes you have read [tun-inbound](tun-inbound.md), especially
"When does the app's `connect()` succeed?".

## One idea

An app can recover from a connection that **fails fast**. It cannot recover
from a connection that **says it worked** and then goes silent.

A TUN with an IPv6 address, in front of a path with no IPv6, turns every IPv6
attempt into the second kind.

```
 fails fast:   connect() ──▶ error in 1 ms   ──▶ app tries IPv4 ──▶ page loads
 fake success: connect() ──▶ "connected"     ──▶ app sends request
                                             ──▶ nothing comes back
                                             ──▶ app waits 10-60 s ──▶ page stuck
```

## How apps pick IPv6 or IPv4: Happy Eyeballs

Most modern apps and OSes use Happy Eyeballs (RFC 8305). Roughly:

```
 resolve name ──▶ got AAAA (IPv6) and A (IPv4)
       │
       ▼
 try IPv6 connect()
       │
       ├── succeeds within ~250 ms ──▶ use IPv6, cancel IPv4   ◀── done, no fallback
       │
       └── fails or is slow        ──▶ start IPv4 connect() in parallel
                                       first to succeed wins
```

The key detail: Happy Eyeballs only races the **connect** step. Once a
connect succeeds, the decision is final. If that connection later carries no
data, Happy Eyeballs does not step in. The app is on its own.

## Why blocking AAAA in DNS is not enough

The natural first defence: "our resolver refuses AAAA answers, so no app
learns an IPv6 address, so IPv6 is never tried." Apps get IPv6 addresses
around that resolver:

| source of the IPv6 address                    | goes through your resolver? |
|-----------------------------------------------|-----------------------------|
| app's own DoH (browsers, some big apps)       | no                          |
| OS "Private DNS" / DoT                        | often no                    |
| answers cached before the VPN came up         | no                          |
| IPv6 literals in app code or config           | no                          |
| your resolver, AAAA query                     | yes, blocked                |

So "no AAAA from us" still leaves some apps holding IPv6 addresses. What
happens next depends on the route table.

## Without an IPv6 address on the TUN: fast failure

```
 app has 2001:db8::10 (learned via its own DoH)
       │
       ▼
 connect(2001:db8::10)
       │
       ▼
 kernel routing table, IPv6:
   (no default route at all)
       │
       ▼
 ENETUNREACH, instantly  ──▶ Happy Eyeballs starts IPv4 ──▶ IPv4 via TUN ──▶ works
```

Consequences:

- IPv6 is "missing", which apps handle every day.
- Fallback cost: about 1 ms. The user never notices.

## With an IPv6 address on the TUN: fake success

Giving the TUN an IPv6 address makes the client install an IPv6 default route
into it. Now the kernel has somewhere to send IPv6.

```
 app has 2001:db8::10
       │
       ▼
 connect(2001:db8::10)
       │
       ▼
 kernel: ::/0 via tun0  ──▶ tun0 ──▶ user-space stack ──▶ proxy outbound
                                                              │
                                     link to proxy server is up (IPv4, fine)
                                                              │
                         SYN-ACK to app  ◀────────────────────┘   ◀── app: "connected!"
                                                              │
                                                              ▼
                                     proxy server dials 2001:db8::10
                                     server has no IPv6 ──▶ dial fails
                                                              │
                                     relay closes, or never sends data
                                                              │
 app: sent TLS ClientHello, waiting for ServerHello ... ... ... timeout
```

Why the app was told "connected": with most proxy protocols, the client-side
stack answers the app once the **proxy server** link is up. It cannot know
whether the server will reach the destination. The handshake the app saw was
real, but it proved the wrong thing.

Consequences:

- Happy Eyeballs already picked IPv6. It never tries IPv4.
- The app waits for its own read timeout (often 10-60 s), then shows an error
  or retries, sometimes over IPv6 again.
- Symptom: "VPN connected, some sites load, others spin forever." Sites that
  answer AAAA from the app's own resolver are the ones that hang.
- IPv4-only tests (`ping 1.1.1.1`, `curl -4`) pass, so the VPN looks healthy.

## Side by side

| TUN has IPv6 address? | path has IPv6? | IPv6 connect() result      | user sees          |
|-----------------------|----------------|----------------------------|--------------------|
| no                    | no             | ENETUNREACH at once        | works (IPv4)       |
| yes                   | yes            | real success               | works (IPv6)       |
| yes                   | no             | fake success, then silence | **sites hang**     |
| no                    | yes            | ENETUNREACH at once        | works (IPv4 only)  |

Only one row breaks: an IPv6 door into the TUN with no IPv6 road behind it.

## Decision tree

```
 Does the path behind the proxy carry IPv6 end to end?
   │
   ├── yes ──▶ give the TUN an IPv6 address; resolve AAAA normally
   │
   └── no  ──▶ remove the IPv6 address from the TUN
               (blocking AAAA in DNS is a nice extra, not a fix)
```

## Mental model to keep

- A fast "no" is cheap. A slow "yes, then nothing" is expensive.
- Happy Eyeballs protects the connect step only.
- A TUN IPv6 address is a promise that IPv6 works. Make it only if true.
- DNS filtering cannot stop IPv6 attempts. The route table can.
