# Network diagnostics: IPv6 and WARP

Index: [network-diag.md](network-diag.md).

Profile under test: a WARP key and an `r6` rule set. DNS strategy
`ipv4_only`, except `r6` domains (`prefer_ipv4`, AAAA included). Route rule
`ip_version: 6 → warp-ep` sits before `mm-ip-rules`, `clash_mode` and the
`r4` rules. Tun inbound has a ULA IPv6 address (`fdfe:dcba:9876::1/126`).

Key point: routing keys on the IP version of the connection, not on the DNS
query type. An app that gets an IPv6 address by any means and connects over
IPv6 goes to `warp-ep`.

## What the system resolver answers

```sh
dscacheutil -q host -a name <domain>        # macOS system resolver
doggo <domain> A AAAA                        # shows which nameserver answered
```

Expected under the profile: `r6` domains get an `ipv6_address`, every other
domain gets none (`dns: strategy rejected` for AAAA in the sing-box debug
log). An IPv6-only domain outside `r6` (e.g. `ipv6.google.com`) does not
resolve at all: `curl` exits with code 6.

## What a DoH resolver answers (bypasses sing-box DNS)

```sh
doggo <domain> A AAAA @https://<doh-provider>/dns-query
curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=<domain>&type=AAAA'
curl -s --doh-url https://cloudflare-dns.com/dns-query https://<domain>/ -o /dev/null -w '%{http_code} %{remote_ip}\n'
```

`hijack-dns` catches only plain DNS on port 53. DoH is ordinary HTTPS on
443, so sing-box routes it as a normal connection and cannot filter the
answer. A browser with encrypted DNS on (Brave/Chrome "Use secure DNS",
Firefox DoH, iCloud Private Relay) therefore gets AAAA records the profile
would have refused.

## Is IPv6 traffic going through WARP

```sh
curl -s 'https://[2606:4700:4700::1111]/cdn-cgi/trace' | grep -E '^(ip|loc|warp)='
```

`ip=` an IPv6 address and `warp=on` means the IPv6 connection left through
the WARP endpoint. In the sing-box log, look for `warp-ep` next to an IPv6
destination.

## Which address family the browser picks

```text
brave://net-internals/#dns       (chrome://net-internals/#dns)  look up <domain>
brave://net-internals/#sockets   "Flush socket pools" before retesting
```

The lookup lists resolved addresses in the order Chromium will try them.
Chromium sorts by RFC 6724, which prefers a destination whose scope matches
the source address. The host's only IPv6 source is the tun's ULA address,
and public IPv6 destinations do not match it, so IPv4 sorts first.
Happy Eyeballs then tries IPv4 and falls back to IPv6 only if IPv4 has not
connected after about 300 ms.

Flush socket pools before testing: Chromium reuses open connections (and
QUIC sessions) and skips the lookup otherwise.

## Worked case: IPv6 sites load in the browser, not in curl (2026-10-13)

Symptom: with `r6` listing only `ip6only.me` and `test-ipv6.com`, other
IPv6-only sites (`ipv6.google.com`, `42.be`) still loaded in Brave. Some
images on `42.be` did not.

Findings:

1. System resolver: `ipv6.google.com` and `42.be` had no AAAA; `curl` failed
   with exit code 6. The profile worked as written.
2. Brave had encrypted DNS on. Its DoH answers included AAAA for both
   (`42.be` has no A record at all). Brave connected over IPv6, and the
   `ip_version: 6` rule sent it to `warp-ep` (`warp=on`, `loc=SG`).
3. `42.be` loads 1000 images, each from a different IPv6 address on port
   8080. Fetched one by one through WARP, 24 of 25 sampled loaded; the one
   failure (`[2001:470:79a1::0000]`) timed out on port 80 too, so that
   origin host was down. Not verified: whether hundreds of parallel
   connections through WARP over the proxy cause the rest of the losses.
4. Dual-stack sites: `brave://net-internals/#dns` for `youtube.com` returned
   four A and four AAAA records, A first. The sing-box log showed
   `www.youtube.com`, `yt3.ggpht.com` and `*.googlevideo.com` over IPv4
   QUIC, matched by no proxy rule, out `direct`. No `warp-ep` lines.

Resulting model:

```text
Browser (own DoH) - dual-stack site  -> IPv4 first -> direct / Proxy
                  - IPv6-only site   -> IPv6       -> warp-ep
Other apps (sing-box DNS, ipv4_only) - normal site -> IPv4 -> direct / Proxy
                                     - r6 domain   -> IPv6 -> warp-ep
Any app - IPv6 literal (e.g. [2606:4700::1111])    -> warp-ep
```

Caveats:

- If an IPv4 attempt stalls past the Happy Eyeballs delay, the browser's
  IPv6 fallback goes to `warp-ep`. Expect occasional `warp-ep` lines for
  dual-stack sites.
- IPv4-first holds only while the tun's IPv6 address is ULA. A global-scope
  address would make the browser prefer IPv6, and most browser traffic
  would move to WARP, skipping `mm-ip-rules → direct` and the `r4` rules.
- To make the browser follow the profile, turn off its encrypted DNS.
