# sing-box route matching: how `route.rules` are evaluated

Research note, 2026-09-07. Verified against sing-box **v1.14.0** (latest release, tagged 2026-08-31) source and the docs bundled in that tag (`docs/` in the repo, which is what sing-box.sagernet.org renders). Source citations use `path:line` at tag `v1.14.0`; prefix with `https://github.com/SagerNet/sing-box/blob/v1.14.0/`.

## TL;DR

- **Rules are evaluated top to bottom in one pass; the first rule whose action is *final* (`route`, `reject`, `hijack-dns`, or `bypass` with an outbound) wins and stops evaluation.** Non-final actions (`sniff`, `resolve`, `route-options`) run their side effect and evaluation **continues with the next rule**, never restarting from the top. [`route/route.go:593-694`]
- **Domain matchers (`domain*`, `rule_set` domain entries) read `metadata.Domain`, falling back to `Destination.Fqdn`.** On a TUN inbound with no fake-ip, the destination is always an IP, so before `sniff` a domain rule can only match via the DNS reverse-mapping cache (`dns.reverse_mapping: true`). After `sniff` it matches on the sniffed SNI / Host. [`route/rule/rule_item_domain.go:62-72`, `route/route.go:534-580`]
- **`ip_cidr` never matches a domain destination before `resolve`** (it returns `false` unless the rule-set `accept_empty` flag is set). It matches the literal IP destination, or the addresses produced by a preceding `resolve` action. [`route/rule/rule_item_cidr.go:76-100`]
- **`port: 53` works without sniff; `protocol: dns` needs sniff** (or the TUN's own derived DNS address, which is pre-marked as DNS and hijacked *before* the rule loop runs). `hijack-dns` hands the query to the DNS module, where `dns.rules` are walked with the same first-final-match model and `dns.final` is the fallback. [`route/rule/rule_item_port.go:30-36`, `route/rule/rule_item_protocol.go:27-29`, `protocol/tun/inbound.go:546-584`, `route/route.go:101-104`, `dns/router.go:580-767`]
- **Applied to `scaffolds/client/route.json`: the order is correct.** `sniff` must precede the TCP/UDP domain rules (A: yes). Port-53 hijack at the top is fine and idiomatic (B). The `100.64.0.0/10 → ts-ep` rule works before sniff because TUN always supplies an IP (C). Footguns (D): the port-53 rule sits *above* the Tailscale CIDR rule, so DNS to MagicDNS `100.100.100.100:53` is hijacked rather than sent to `ts-ep`; `clash_mode: Partial` inside the only routing rules means `Global`/`Direct` modes both fall to `final: direct`; a `sniff` timeout of `100ms` (default `300ms`) silently degrades to `direct` for slow first-byte clients.

---

## 1. Evaluation order of `route.rules`

The router builds `r.rules` in config order [`route/router.go:74-84`] and `matchRule` iterates them in a single labelled loop:

```go
match:
	for currentRuleIndex, currentRule := range r.rules {
		metadata.ResetRuleCache()
		if !currentRule.Match(metadata) {
			continue
		}
		...
		actionType := currentRule.Action().Type()
		if actionType == C.RuleActionTypeRoute ||
			actionType == C.RuleActionTypeReject ||
			actionType == C.RuleActionTypeHijackDNS {
			selectedRule = currentRule
			selectedRuleIndex = currentRuleIndex
			break match
		}
		if actionType == C.RuleActionTypeBypass { ... break match (only if it names an outbound) }
	}
```
[`route/route.go:593-694`]

So: top to bottom, first rule with a final action wins. A rule that matches but carries a non-final action does not stop the loop.

**What "match" means for a default rule.** `abstractDefaultRule.Match` [`route/rule/rule_abstract.go:54-67`] evaluates `matchInner`: every "other" item must match (AND), and the address/port item *groups* are OR within a group and AND across groups [`route/rule/rule_abstract.go:69-86`, `:106-148`]. The docs state this as:

> (`domain` || `domain_suffix` || `domain_keyword` || `domain_regex` || `geosite` || `geoip` || `ip_cidr` || `ip_is_private`) && (`port` || `port_range`) && (`source_geoip` || `source_ip_cidr` || `source_ip_is_private`) && (`source_port` || `source_port_range`) && `other fields`
> — https://sing-box.sagernet.org/configuration/route/rule/#default-fields [`docs/configuration/route/rule.md:206-217`]

A rule with no items at all matches everything (`len(r.allItems) == 0 → true`) [`route/rule/rule_abstract.go:55-57`]. That is why `{"action": "sniff"}` with no matchers applies to every connection.

**Logical rules.** `abstractLogicalRule.Match` [`route/rule/rule_abstract.go:204-245`]: `and` requires every sub-rule to match (short-circuits on first failure), `or` requires any (short-circuits on first success). Each sub-rule is evaluated against a copy of the metadata. `invert` flips the final result of the rule it is on (default or logical) [`route/rule/rule_abstract.go:60-66`, `:239-244`]. Docs: `mode` is `and` or `or`; `invert` "Invert match result." [`docs/configuration/route/rule.md:516-518`, `:538-548`]. Sub-rules inside a logical rule may not carry their own `action`; only the outer rule acts (`ValidateNoNestedRuleActions`, [`route/rule/rule_nested_action.go:11-22`], enforced at [`route/router.go:76-79`]).

## 2. Terminal vs non-terminal actions

The docs split actions into "Final actions" (`route`, `bypass`, `reject`, `hijack-dns`) and "Non-final actions" (`route-options`, `sniff`, `resolve`) [`docs/configuration/route/rule_action.md:26`, `:138`; https://sing-box.sagernet.org/configuration/route/rule_action/]. The source agrees exactly:

| action | effect in `matchRule` | stops evaluation? | source |
|---|---|---|---|
| `route` (default when `outbound` is given) | applies its route-options to metadata, selects the outbound | yes | `route/route.go:608-611`, `:677-683` |
| `bypass` (1.13+) | like route; only final when it names an outbound | yes if `outbound` set | `route/route.go:684-692` |
| `reject` | selected; connection closed / dropped by caller | yes | `route/route.go:677-683`, `:140-145` |
| `hijack-dns` | selected; connection handed to DNS module | yes | `route/route.go:677-683`, `:146-150` |
| `route-options` | mutates metadata (override address/port, udp timeout, TLS fragment...) | **no** | `route/route.go:609-611`, `:618-660` |
| `sniff` | runs `actionSniff`, appends the peeked buffer, sets Protocol/Domain/Client | **no** | `route/route.go:660-670` |
| `resolve` | runs `actionResolve`, sets `DestinationAddresses` | **no** | `route/route.go:671-676` |

After `sniff` or `resolve` the loop simply proceeds to `currentRuleIndex + 1`; there is no restart. There is one `for ... range r.rules` and the only exits are `break match` (final action) or falling off the end (no rule selected). [`route/route.go:593-694`]

Two sniff details that matter for ordering:

- A second `sniff` rule is a no-op once `metadata.Protocol` is set ("duplicate sniff skipped"), and sniffing is skipped entirely for server-first ports (SMTP 25/465/587, IMAP 143/993, POP3 110/995) [`route/route.go:702-708`, `common/sniff/sniff.go:25-39`].
- A sniff failure (timeout, unrecognised protocol) is **not fatal**: `metadata.SniffError` is recorded and matching continues with `Domain`/`Protocol` still empty [`route/route.go:738-740`].

## 3. Metadata before vs after `sniff` / `resolve`

**Before the loop**, `prepareMatchMetadata` runs once [`route/route.go:534-580`, called at `:590`]. It populates:

1. process info (`find_process`), neighbor MAC/hostname (`find_neighbor`) [`:535-552`];
2. **fake-ip reverse lookup**: if the destination IP is inside the fake-ip store, `Destination` is rewritten to `{Fqdn: domain, Port}` and `metadata.FakeIP = true` [`:553-566`];
3. otherwise, if `metadata.Domain` is empty, **DNS reverse mapping**: `r.dns.LookupReverseMapping(Destination.Addr)` fills `metadata.Domain` [`:567-572`]. The mapping is written on every non-fake-ip DNS answer that passed through the DNS module [`dns/router.go:1109-1122`, `:1200`], which is exactly what `hijack-dns` produces. It is gated by `dns.reverse_mapping` [`docs/configuration/dns/index.md:130-135`];
4. `IPVersion` from the destination [`:574-578`].

Other inbound-provided domains: SOCKS/HTTP/mixed inbounds pass the client's requested hostname as `Destination.Fqdn`; TUN never does (it only has the packet's IP) [`protocol/tun/inbound.go:546-563`].

**What each matcher reads:**

| matcher | reads | available before sniff on TUN? |
|---|---|---|
| `domain`, `domain_suffix`, `domain_keyword`, `domain_regex`, rule-set domain entries | `metadata.Domain`, else `Destination.Fqdn`; `false` if both empty | only via fake-ip rewrite or reverse-mapping hit |
| `protocol`, `client` | `metadata.Protocol` / `.Client` | only the TUN-derived DNS address pre-mark (see 5) |
| `ip_cidr`, `ip_is_private` | `Destination.Addr` if IP; else `DestinationAddresses` (from `resolve`); else `IPCIDRAcceptEmpty` | yes, always (TUN destination is an IP) |
| `port`, `port_range`, `network`, `inbound`, `clash_mode`, `source_*` | plain metadata fields | yes |

Sources: [`route/rule/rule_item_domain.go:62-72`], [`route/rule/rule_item_rule_set.go` uses the same `DomainItem` via `NewRawDomainItem`, `rule_item_domain.go:55-60`], [`route/rule/rule_item_protocol.go:27-29`], [`route/rule/rule_item_cidr.go:76-100`], [`route/rule/rule_item_port.go:30-36`], [`route/rule/rule_item_clash_mode.go:31-35`].

**After `sniff`:** the sniffers write `metadata.Protocol` and, for TLS/HTTP/QUIC, `metadata.Domain` (SNI / Host), plus `metadata.Client` for QUIC and SSH [`common/sniff/tls.go:25`, `common/sniff/http.go:26`, `common/sniff/quic.go:309`; protocol table at `docs/configuration/route/sniff.md`, https://sing-box.sagernet.org/configuration/route/sniff/]. `Destination` is **not** rewritten unless the deprecated `sniff_override_destination` path is in effect [`route/route.go:741-747`]. So after sniff, domain rules match on the sniffed name while `ip_cidr` rules keep matching the real IP.

**After `resolve`:** only `metadata.DestinationAddresses` is set, and only when `Destination.IsDomain()` [`route/route.go:887-912`]. On a TUN inbound without fake-ip the destination is never a domain, so `resolve` is a no-op there.

**Consequence for the question "domain rule placed before the sniff rule":** it matches only on inbound-provided or reverse-mapped domain, never on the sniffed domain. Because the loop never restarts, moving `sniff` below the domain rules means those rules were already evaluated with an empty `Domain` and will not be revisited.

## 4. `route.final`

Docs: "Default outbound tag. the first outbound will be used if empty." [`docs/configuration/route/index.md:78-80`, https://sing-box.sagernet.org/configuration/route/#final]

Source: `route.final` is passed to the outbound manager as `defaultTag` [`box.go:213`]. At start, if the tag is set the manager resolves it (also from endpoints); if nothing is set it registers the first outbound, and if there are no outbounds at all it synthesises a `direct` fallback [`adapter/outbound/manager.go:51-75`, `:295-305`]. When `matchRule` returns `selectedRule == nil`, the router uses `r.outbound.Default()` for TCP and UDP [`route/route.go:154-160`, `:286-292`]. An endpoint tag (for example the Tailscale endpoint) is a valid `outbound`/`final` target because `Manager.Outbound(tag)` falls back to `endpoint.Get(tag)` [`adapter/outbound/manager.go:201-209`].

## 5. `hijack-dns`

**What it does.** When selected, the router does not dial an outbound. For TCP it wraps the buffered connection and calls `hijackDNSStream`; for UDP `hijackDNSPacket` [`route/route.go:146-150`, `:282-283`; `route/dns.go:20-44`]. Both read DNS messages and call `router.ExchangeAsync` on the DNS module, which is the `dns.rules` walker [`protocol/dns/handle.go:22-50`, `dns/router.go:1178-1202`, `:1204-1226`]. Docs: "`hijack-dns` hijack DNS requests to the sing-box DNS module." [`docs/configuration/route/rule_action.md:128-136`]

**Interaction with `dns.rules`.** The hijacked query carries the connection's `InboundContext` (inbound tag, source, process...) into DNS rule matching (`adapter.WithContext(ctx, &metadata)` in `handle.go:44`), so `dns.rules` can match on `inbound`, `source_ip_cidr`, `process_name`, etc. Answers are recorded into the reverse-mapping cache (section 3) [`dns/router.go:1200`].

**TUN pre-hijack that happens before any rule.** With `dns_mode` unset (default `hijack`) and `dns_address` unset, the TUN inbound derives one DNS address per family (the IP after the first `address` entry; for `10.10.10.0/24` that is `10.10.10.1`) [`protocol/tun/inbound.go:330-338`; docs `docs/configuration/inbound/tun.md:248-292`, https://sing-box.sagernet.org/configuration/inbound/tun/#dns_address]. Connections to that address get `metadata.Protocol = dns` set by the inbound itself [`protocol/tun/inbound.go:553-556`, `:572-575`], and the router short-circuits to the DNS module **before `matchRule` is called**:

```go
if metadata.InboundType == C.TypeTun && metadata.Protocol == C.ProtocolDNS {
	N.CloseOnHandshakeFailure(conn, onClose, r.hijackDNSStream(ctx, conn, metadata))
	return nil
}
```
[`route/route.go:101-104` (TCP), `:240-242` (UDP)]. The TUN docs call this "equivalent to a `hijack-dns` route action" [`docs/configuration/inbound/tun.md:284-288`]. A `hijack-dns` route rule is therefore only needed for DNS sent to *other* resolvers (apps with hard-coded `1.1.1.1:53`, or an OS resolver that is not the TUN one).

**`port: 53` vs `protocol: dns`.** `PortItem` compares `Destination.Port` and needs nothing else [`route/rule/rule_item_port.go:30-36`]. `ProtocolItem` compares `metadata.Protocol`, which is empty until a `sniff` action ran (or the TUN pre-mark above) [`route/rule/rule_item_protocol.go:27-29`]. The official client example uses both, after a global sniff: `{"action":"sniff"}` then `logical or [ {protocol: dns}, {port: 53} ] → hijack-dns` [`docs/manual/proxy/client.md:429-446`, https://sing-box.sagernet.org/manual/proxy/client/]. Placing `port: 53 → hijack-dns` at the very top is valid: it needs no sniff, and being final it also prevents port-53 traffic from being sniffed later, which is harmless.

## 6. `dns.rules`

Same model. In v1.14.0 the non-legacy walker `walkDNSRules` iterates `rules` in listed order; a non-matching rule `continue`s; `route-options` merges its options and continues; `route`, `reject`, `predefined`, and the 1.14 `respond` action terminate; if the loop ends the default transport is used [`dns/router.go:580-767`; legacy equivalent `matchDNS` at `:285-369`]. The default transport is `dns.final` ("Default dns server tag. The first server will be used if empty.") [`docs/configuration/dns/index.md:52-56`, `box.go:214`].

Docs on order: "By default, rules are matched one after another in listed order" [`docs/configuration/dns/rule_action.md:47-58`, https://sing-box.sagernet.org/configuration/dns/rule_action/]. Action list: `route` (default), `route-options`, `reject` (`default` = REFUSED, `drop`), `predefined` (1.12+), plus 1.14's `evaluate`/`respond`/`race`/`match_response` [`docs/configuration/dns/rule_action.md:21-58`, `:271-330`]. DNS logical rules and `invert` use the same `abstractLogicalRule` code as route rules [`route/rule/rule_dns.go`, `route/rule/rule_abstract.go:204-245`].

Route/DNS interaction, end to end: connection → `route.rules` → `hijack-dns` (or TUN pre-mark) → DNS module → `dns.rules` → server (`dns.final` fallback) → answer recorded into reverse mapping → later connections to that IP see `metadata.Domain` before sniff (section 3).

Note that domain resolution triggered by the `resolve` action, `domain_resolver`, or `default_domain_resolver` does **not** go through `dns.rules` in 1.14 [`docs/migration.md:216-264`, https://sing-box.sagernet.org/migration/#ip_version-and-query_type-behavior-changes-in-dns-rules].

## 7. `reject` methods and `sniff` timeout

`reject`: `method: default` replies TCP RST / ICMP port-unreachable; `method: drop` silently drops. With `default`, after 50 triggers in 30 s the method is temporarily switched to `drop` unless `no_drop` is set [`route/rule/rule_action.go:469-496`; docs `docs/configuration/route/rule_action.md:89-126`]. On TUN, "the specified method is used for reject tun connections if `sniff` action has not been performed yet"; established connections are just closed [`docs/configuration/route/rule_action.md:105-107`]. `reply` exists for ICMP echo only and errors for TCP/UDP [`route/route.go:142-144`, `:278-280`].

`sniff.timeout`: docs say "`300ms` is used by default" [`docs/configuration/route/rule_action.md:299-303`]; source `C.ReadPayloadTimeout = 300 * time.Millisecond` [`constant/timeout.go:10`], applied when the action's timeout is zero for streams [`common/sniff/sniff.go:41-44`] and packets [`route/route.go:809-812`]. The timeout bounds the wait for the first client payload; on expiry the connection continues unsniffed (section 2).

## 8. `ip_cidr` against a domain destination

```go
func (r *IPCIDRItem) Match(metadata *adapter.InboundContext) bool {
	if r.isSource || metadata.IPCIDRMatchSource { return r.ipSet.Contains(metadata.Source.Addr) }
	if metadata.DestinationAddressMatchFromResponse { ... DNS response matching ... }
	if metadata.Destination.IsIP() { return r.ipSet.Contains(metadata.Destination.Addr) }
	if len(metadata.DestinationAddresses) > 0 { return common.Any(metadata.DestinationAddresses, r.ipSet.Contains) }
	return metadata.IPCIDRAcceptEmpty
}
```
[`route/rule/rule_item_cidr.go:76-100`]

So for a domain destination (SOCKS/HTTP inbound, or fake-ip rewritten) an `ip_cidr` rule placed before `resolve` returns `IPCIDRAcceptEmpty`, which is `false` except inside a rule-set with `rule_set_ip_cidr_accept_empty` (DNS-rule only) [`route/rule/rule_item_rule_set.go:105-110`]. After `resolve`, it matches any resolved address. On TUN without fake-ip the destination is always an IP and the first branch applies.

---

## Applied to `scaffolds/client/route.json`

Context from the sibling scaffolds: inbound is a single `tun` (`10.10.10.0/24`, `auto_route`, `strict_route`, gvisor; no `dns_mode`/`dns_address`, no deprecated `sniff` fields) [`scaffolds/client/inbounds.json`]. DNS has no `fakeip` server, no `dns.rules`, `reverse_mapping: true`, `final: dns-remote` (DoH) [`scaffolds/client/dns.json`]. `ts-ep` is a `tailscale` endpoint with `detour: shadowsocks-uot` [`scaffolds/client/endpoints.json`]. Clash API `default_mode: Partial` [`scaffolds/client/experimental.json`].

Rule order under evaluation:

1. `port: 53 → hijack-dns` (final)
2. `or(tcp port 5222/853, ip_cidr 5.28.195.2/32 0.0.0.0/32 ::/128) → reject drop` (final)
3. `ip_cidr 100.64.0.0/10 → ts-ep` (final)
4. `sniff timeout 100ms` (non-final, matches everything)
5. `and(tcp, or(rule_set[24], domain gstatic.com, domain_suffix .gstatic.com), clash_mode Partial) → TCP` (final)
6. same for `udp → UDP` (final)
7. `final: direct`

### A. Must `sniff` come before the TCP/UDP domain rules? **Yes.**

On this TUN inbound `Destination` is always an IP and `Destination.Fqdn` is empty [`protocol/tun/inbound.go:546-563`]. `DomainItem.Match` then depends entirely on `metadata.Domain` [`route/rule/rule_item_domain.go:62-72`], which before rule 4 can only be filled by the reverse-mapping lookup in `prepareMatchMetadata` [`route/route.go:567-572`]. That lookup works only when the app's DNS query went through sing-box's DNS module *and* the answer TTL has not expired; the docs flag it as unreliable where the OS caches DNS (macOS) [`docs/configuration/dns/index.md:130-135`]. With rules 5/6 placed *before* sniff, any connection that missed the reverse map would be evaluated once with an empty domain and, since the loop never revisits earlier rules [`route/route.go:593-694`], fall through to `final: direct`. Keeping `sniff` at rule 4 makes rules 5/6 see the TLS SNI / HTTP Host / QUIC SNI. Rule-set domain entries use the identical matcher, so the same applies to all 24 `rule_set` tags.

Reverse mapping is still useful here as a second source (for non-TLS traffic with no sniffable name), so `reverse_mapping: true` and the sniff rule complement each other.

### B. `hijack-dns` on `port: 53` at the top: correct and idiomatic. No sniff needed.

- `PortItem` reads only `Destination.Port` [`route/rule/rule_item_port.go:30-36`], so this rule works with an empty `Protocol`. Switching it to `protocol: dns` alone would break it: `Protocol` is empty until sniff [`route/rule/rule_item_protocol.go:27-29`], and sniff is rule 4. The official example uses `or(protocol dns, port 53)` after a global sniff [`docs/manual/proxy/client.md:429-446`]; `port: 53` on its own is the strict subset that does not depend on sniff order.
- DNS to the TUN's derived resolver `10.10.10.1` never reaches this rule at all: the inbound pre-marks it and the router hijacks it before `matchRule` [`protocol/tun/inbound.go:553-575`, `route/route.go:101-104`, `:240-242`]. Rule 1 only catches DNS aimed at other resolvers (hard-coded `8.8.8.8:53` etc.), which is exactly what you want for a "no DNS leaks" setup with `strict_route`.
- Downsides: (1) any non-DNS traffic on port 53 is fed to the DNS parser and closed on parse failure [`protocol/dns/handle.go:22-40`]; rare in practice. (2) Because rule 1 is above rule 3, UDP/TCP 53 to `100.100.100.100` (Tailscale MagicDNS, inside `100.64.0.0/10`) is hijacked into sing-box DNS instead of going to `ts-ep`. Whether that matters depends on whether anything on the host is configured to query MagicDNS; see D and Open questions. (3) Rule 1 also precedes rule 2, so TCP 53 to `5.28.195.2` is hijacked rather than dropped; cosmetic.
- Adding `protocol: dns` as an `or` alternative would only add value for DNS on non-53 ports, and would require moving the rule below sniff. Not needed here.

### C. `ip_cidr 100.64.0.0/10 → ts-ep` before sniff: behaves correctly.

`IPCIDRItem.Match` takes the `Destination.IsIP()` branch [`route/rule/rule_item_cidr.go:91-93`]; TUN always supplies an IP, and there is no fake-ip server that could have rewritten it to a domain [`route/route.go:553-566`, `scaffolds/client/dns.json`]. `ts-ep` resolves as an outbound through the endpoint fallback in `Manager.Outbound` [`adapter/outbound/manager.go:201-209`]. Being final, it also means Tailscale-bound flows are never sniffed, which saves the 100 ms peek. Two notes: `100.64.0.0/10` is the whole CGNAT range, not Tailscale-specific, so a CGNAT-addressed LAN/ISP host would also be sent to the endpoint; and the endpoint's own control/DERP traffic is dialed through its `detour` (`shadowsocks-uot`), not through these rules.

### D. Redundancies, ordering issues, footguns

1. **`clash_mode: Partial` is the only mode with routing rules.** sing-box gives `clash_mode` no built-in behaviour; it is just a string compared against the Clash API's current mode [`route/rule/rule_item_clash_mode.go:31-35`; no other consumer under `route/`]. Selecting `Global` or `Direct` in a Clash dashboard makes rules 5/6 stop matching, so *both* modes route everything to `final: direct`. If `Global` is meant to mean "proxy everything", add `{"clash_mode": "Global", "outbound": "TCP"}`-style rules (TCP and UDP variants) after rule 4.
2. **MagicDNS ordering.** Rule 1 captures `*:53` before rule 3 can claim `100.100.100.100`. If MagicDNS is desired, put a `{"ip_cidr": "100.100.100.100/32", "outbound": "ts-ep"}` rule above rule 1, or move rule 3 above rule 1 (the CIDR rule needs no sniff either). If nothing queries MagicDNS, no change is needed.
3. **`sniff` timeout `100ms` vs default `300ms`.** On expiry, sniff fails silently and rules 5/6 see no domain, so the connection goes `direct` [`route/route.go:738-740`, `constant/timeout.go:10`]. TLS clients normally send ClientHello immediately, so this is usually fine, but a tighter value trades correctness for latency on slow apps. The default is the safer choice unless the 200 ms matter.
4. **`domain: gstatic.com` + `domain_suffix: .gstatic.com`** is two entries for what `domain_suffix: gstatic.com` (no leading dot) covers since 1.9.0: it matches `(domain|.+\.domain)` [`docs/migration.md:1252-1257`]. Not wrong, just redundant.
5. **Tailscale rule-set vs CIDR rule are not in conflict.** The `tailscale` rule-set matches domains (control plane, DERP, login) and sends them via the `TCP`/`UDP` urltest groups; rule 3 matches IPs inside the tailnet. They address different traffic. The endpoint itself does not use the rule-set (it dials via `detour`).
6. **`clash_mode` inside a logical `and` is fine** [`route/rule/rule_abstract.go:204-218`]. Sub-rules must not carry `action`/`outbound`; the config correctly keeps them on the outer rule [`route/rule/rule_nested_action.go:11-22`].
7. **Reject rule before sniff is intended.** `reject` on TUN uses the configured `method` when sniff has not run [`docs/configuration/route/rule_action.md:105-107`]; `drop` there gives a clean packet drop with no 100 ms peek. Placing it above sniff is the right order.
8. **Rules 5 and 6 duplicate the 24-tag list.** They must stay separate while TCP and UDP go to different urltest groups. If they ever share an outbound, they collapse to one rule with `network: ["tcp","udp"]`.
9. **No `dns.rules`, so every hijacked query goes to `dns.final` (`dns-remote`, DoH with an empty `server` placeholder).** Rule 1 and the TUN pre-hijack both end there. Domains that rules 5/6 send `direct` are still resolved through the remote DoH; that is a policy choice, not a bug, but it means `direct` sites see the DoH provider's egress for resolution.
10. **`resolve` is absent and unnecessary.** With a TUN-only inbound and no fake-ip, destinations are never domains, so `ip_cidr` rules never need `resolve` (section 8).

## Open questions / unverified

- Whether anything on the client host actually queries Tailscale MagicDNS (`100.100.100.100`) when Tailscale runs as an in-process sing-box endpoint rather than the system daemon. Not verified; only matters for D.2.
- Behaviour of `experimental.clash_api.default_mode` on first start versus persisted mode in `cache.db` was not traced; D.1 assumes the dashboard can switch modes.
- I did not run the config through `sing-box check`; the analysis is from source reading of v1.14.0 only. Behaviour on the `testing` branch (default branch at `60b504a`) was not compared.
- The `dns-remote` server has empty `server`/`path` placeholders in the scaffold; DNS behaviour was analysed assuming these are filled at render time.

## Sources

Docs (rendered from `docs/` at tag v1.14.0):
- https://sing-box.sagernet.org/configuration/route/ (`docs/configuration/route/index.md`)
- https://sing-box.sagernet.org/configuration/route/rule/ (`docs/configuration/route/rule.md`)
- https://sing-box.sagernet.org/configuration/route/rule_action/ (`docs/configuration/route/rule_action.md`)
- https://sing-box.sagernet.org/configuration/route/sniff/ (`docs/configuration/route/sniff.md`)
- https://sing-box.sagernet.org/configuration/dns/ (`docs/configuration/dns/index.md`)
- https://sing-box.sagernet.org/configuration/dns/rule/ (`docs/configuration/dns/rule.md`)
- https://sing-box.sagernet.org/configuration/dns/rule_action/ (`docs/configuration/dns/rule_action.md`)
- https://sing-box.sagernet.org/configuration/inbound/tun/ (`docs/configuration/inbound/tun.md`)
- https://sing-box.sagernet.org/configuration/shared/listen/ (`docs/configuration/shared/listen.md`, deprecated `sniff`/`sniff_override_destination`/`sniff_timeout` since 1.11.0, removed 1.13.0)
- https://sing-box.sagernet.org/migration/ (`docs/migration.md`: 1.11.0 "Migrate legacy inbound fields to rule actions", 1.9.0 `domain_suffix` change, 1.14.0 DNS-rule bypass for `resolve`/`domain_resolver`)
- https://sing-box.sagernet.org/manual/proxy/client/ (`docs/manual/proxy/client.md`)

Source (https://github.com/SagerNet/sing-box, tag `v1.14.0`, release 2026-08-31):
- `route/route.go` (`routeConnection`, `routePacketConnection`, `prepareMatchMetadata`, `matchRule`, `actionSniff`, `actionResolve`)
- `route/router.go` (`Initialize`)
- `route/dns.go` (`hijackDNSStream`, `hijackDNSPacket`, `HijackDNSPacket`)
- `route/rule/rule_abstract.go` (`abstractDefaultRule.Match`, `abstractLogicalRule.Match`)
- `route/rule/rule_action.go` (`NewRuleAction`, `RuleActionReject.Error`, `RuleActionSniff.build`)
- `route/rule/rule_item_cidr.go`, `rule_item_domain.go`, `rule_item_protocol.go`, `rule_item_port.go`, `rule_item_clash_mode.go`, `rule_item_rule_set.go`, `rule_nested_action.go`, `rule_dns.go`
- `dns/router.go` (`matchDNS`, `walkDNSRules`, `Exchange`, `recordReverseMapping`, `LookupReverseMapping`)
- `protocol/tun/inbound.go` (`Start`, `JudgeFlow`, `NewDNSPacket`, `NewConnectionEx`, `NewPacketConnectionEx`)
- `protocol/dns/handle.go` (`HandleStreamDNSRequest`)
- `adapter/outbound/manager.go` (`Start`, `Outbound`, `Default`), `box.go:213-214`
- `common/sniff/sniff.go` (`Skip`, `PeekStream`), `common/sniff/tls.go`, `http.go`, `quic.go`
- `constant/timeout.go`
