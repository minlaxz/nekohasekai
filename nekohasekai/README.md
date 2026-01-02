**Notes**

> Using TCP brutal in multiplexing

Brutal essentially flattens the traffic to a constant bitrate.

Making it more suspicious to traffic analysis.

So use with caution or better disable it if ISP is known to do DPI.

---

> Using ECH (Encrypted Client Hello) TLS extension

1. Inbound: tls > `server_name`
2. Outbound: `server`

`server_name` and `server` is completely independent from `domain` used in `sing-box generate ech-keypair domain` command.

For example,
- Let's say ECH is generated for `google.com`
- When client connects to the `server`, SNI will be set to `google.com` (encrypted), but the actual TLS connection is made to `server` 
- `server` could be an IP address or another completely different domain `trojan.your-domain.tld`

- ECH basically encrypts the Client Hello SNI field.
- So just make sure the `server_name` used in inbound TLS config match with the outbound `server` used in outbound.

---