# ADR 0002: SS-2022 keys are derived from the PSK, not reissued

**Status:** accepted (2026-10-03, #24)

## Context

The Shadowsocks inbound moves from `xchacha20-ietf-poly1305` to `2022-blake3-aes-128-gcm` for its mandatory replay filter. SS-2022 user keys must be base64 of at least 16 bytes. A PSK (`k`) is 20 base64 characters plus `==`, which does not decode at all. Every existing user would need a new key and a new link.

sing-box 1.14.2 handles keys differently on its two sides: the server (sing-shadowsocks v0.2.8) reduces a key longer than 16 bytes to 16 with SHA-256; the client (sing-shadowsocks2 v0.2.1) refuses anything but exactly 16 bytes.

## Decision

Users keep their PSK. Nothing they hold changes. The API derives two forms from it, in one place:

- **SSM key**, what ssm-api holds: PSK without `==` plus its first 4 characters (24 characters, 18 bytes).
- **Client key**, what the Profile config carries: SHA-256 of the decoded SSM key, cut to 16 bytes. This is exactly what the server keeps internally for the SSM key, so both sides agree.

The Users file records the PSK only. The derivation rejects anything that is not a PSK, so a bad entry is skipped and logged instead of posted to ssm-api, which keeps a user whose key failed to apply.

The server PSK (`SHADOWSOCKS_PASSWORD`) is a Deploy value of exactly 16 bytes, written once by Init into the inbound and into both Client template Shadowsocks outbounds; the API appends `:<Client key>`. Init resets the ssm-api cache in the same step, since it holds users under keys the new method cannot decode; the API reseeds them from the Users file on its next start.

## Consequences

- No reissue, no new links; users refresh their Profile config once.
- No extra entropy: the SS-2022 key is only as strong as the PSK (about 103 bits).
- Only sing-box clients are known to work; the derivation is this project's, not SIP022's.
- Per-user traffic counters restart from zero when a volume upgrades.
- Changing the PSK generator to native 16-byte keys stays possible but is not needed.
