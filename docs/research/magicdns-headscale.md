# MagicDNS on headscale: ephemeral nodes, sing-box, and a stable name for `tailscale-nodes/`

Research note, 2026-09-14, for issue #19. Checked against these pinned versions, the same ones the repo runs:

- **headscale v0.29.3** (`scales/docker-compose.yaml`), commit `5aff68b5`. Prefix: `https://github.com/juanfont/headscale/blob/v0.29.3/`
- **sing-box v1.14.0** (`tailscale-nodes/docker-compose.yaml`), commit `0b899587`. Prefix: `https://github.com/SagerNet/sing-box/blob/v1.14.0/`
- **SagerNet/tailscale v1.102.1-sing-box-1.14-mod.4**, the fork pinned in sing-box `go.mod:62`, commit `c8e28eef`. Prefix: `https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/`. Where the fork and upstream share code, the fork is what both the node and the sing-box clients actually run.
- Tailscale KB pages, fetched 2026-09-14.

Source links point at a tag plus a line anchor. Anything not read directly in source or official docs is marked **inferred** or **unverified**.

Scope: this file is deliverable 3 of the issue. The concept doc (`docs/concepts/magicdns.md`), its index entry, and the commit are separate.

## Questions

1. What is MagicDNS? Covers the `100.100.100.100` resolver, `hostname.base_domain` names, and search domains, and who answers each query.
2. What do headscale's `dns:` keys do? Covers `magic_dns`, the `base_domain` rules, `override_local_dns`, `nameservers.global`/`split`, `search_domains`, and `extra_records`/`extra_records_path`.
3. A new ephemeral node registers as `vllm` while the old ephemeral `vllm` still exists. Is the new node renamed? Does `vllm.<base_domain>` point to the old IP or the new one?
4. Does sing-box's `tailscale` endpoint resolve MagicDNS names, and what does it need? What about the official client with a TUN on macOS/Linux?
5. How do the alternatives compare for a node that is off most of the time: a fixed IP in headscale, `extra_records`, or a non-ephemeral node with persisted state?

## Short answer / recommendation

- **With today's setup, MagicDNS does not give a stable name.** Each boot registers a *new* node. Headscale gives it the name `vllm` only if no other node holds `vllm`. Otherwise it gets `vllm-1`, `vllm-2`, and so on. The old, offline `vllm` stays in every peer's netmap until the 30m inactivity GC deletes it. Until then, `vllm.minlaxz.internal` resolves to the **old, dead IP**. After the GC runs, the new node **keeps** `vllm-1`: the name is only re-derived when the reported hostname changes. The name you get therefore flips between boots depending on timing. The IP also changes on every boot, because the allocator walks forward and never hands the old one back.
- **Headscale 0.29.3 cannot pin a node's IP.** There is no RPC or CLI command for it.
- **Recommendation: make the vLLM node non-ephemeral, keep its tailscale state on the persistent `/data` EBS volume, and register it with a tagged key.** The same node then comes back with the same IP and the same name `vllm`. Nothing is GC'd, and tagged nodes never expire. Peers can use `100.64.x.y` or `vllm.minlaxz.internal` directly.
- **Fallback: a dynamic `extra_records_path` record** (e.g. `llm.minlaxz.internal`). Use it only if the node must stay ephemeral, because it needs something on the headscale host to rewrite the JSON on every boot.
- **sing-box clients do not resolve MagicDNS names today.** `scaffolds/client/dns.json` has no `tailscale` DNS server, so `*.minlaxz.internal` queries go to `dns-remote` (NextDNS). To use names, add a `{"type":"tailscale","endpoint":"ts-ep"}` server and a `preferred_by` DNS rule, but only for Mesh users. A `tailscale` DNS server whose endpoint is missing fails at startup, and the API strips `ts-ep` for users without a Mesh key.
- **Official clients (TUN, accept-dns on by default)** resolve MagicDNS names through `100.100.100.100` with no extra setup.

---

## 1. What MagicDNS is, and who answers

- **Names.** The Tailscale KB says MagicDNS "automatically registers DNS names for devices in your network". The FQDN is "a machine name, which you can change" plus "your tailnet DNS name" ([KB 1081](https://tailscale.com/kb/1081/magicdns)). On headscale, the tailnet DNS name is `dns.base_domain`. The peer name sent in the netmap is `GivenName + "." + base_domain + "."` ([`hscontrol/types/node.go:546-570`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/node.go#L546-L570), used for `tailcfg.Node.Name` at [`node.go:1243`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/node.go#L1243)).
- **Quad100.** `100.100.100.100` is the Tailscale service IP ([`net/tsaddr/tsaddr.go:52-53`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/net/tsaddr/tsaddr.go#L52-L53)). The KB describes it as a device-local stub resolver that "resolves hostnames in your tailnet locally using MagicDNS and forwards DNS requests to exit nodes (when configured)" ([KB 1381](https://tailscale.com/kb/1381/what-is-quad100)). In netstack, UDP to the service IP on port 53 is served in-process by `handleMagicDNSUDP` ([`wgengine/netstack/netstack.go:1942-1948`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/wgengine/netstack/netstack.go#L1942-L1948)). Packets headed for quad-100 are "always terminated locally on this node; it must never be forwarded out over WireGuard" ([`netstack.go:842-870`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/wgengine/netstack/netstack.go#L842-L870)).
- **Who answers a query.** The internal resolver's `resolveLocal` handles every query in this order ([`net/dns/resolver/tsdns.go:722-780`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/net/dns/resolver/tsdns.go#L722-L780)):
  1. `Hosts` (control's `ExtraRecords`).
  2. The live `MagicDNSHosts` source (every node in the netmap).
  3. Parent names of nodes that have the subdomain-resolve attribute.
  4. If the name falls under a *local domain* (authoritative suffix), **NXDOMAIN**.
  5. Otherwise **REFUSED**, which tells the resolver to forward.
- **Where forwarded queries go.** Forwarding follows `Routes` (split DNS) and `DefaultResolvers`, as built below in §2.
- **Authoritative suffixes.** With MagicDNS on, the client routes the base domain, `0.e.1.a.c.5.1.1.a.7.d.f.ip6.arpa.`, and `64.100.in-addr.arpa.` through `127.100.in-addr.arpa.` to "resolve internally" ([`ipn/ipnlocal/local.go:6491-6513`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/local.go#L6491-L6513), [`ipn/ipnlocal/node_backend.go:1522-1525`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/node_backend.go#L1522-L1525)). An unknown `x.minlaxz.internal` is therefore answered NXDOMAIN locally and is never forwarded.
- **Name index.** The client indexes both the FQDN and the short name (FQDN minus the MagicDNS suffix) of **every peer in the netmap** ([`node_backend.go:767-805`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/node_backend.go#L767-L805)). It has no online/offline filter.
- **Search domains.** The KB says "With these search domains you only need to type the machine name" ([KB 1081](https://tailscale.com/kb/1081/magicdns)). Headscale always puts `base_domain` first in `Domains`, then `search_domains` ([`hscontrol/types/config.go:980-984`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L980-L984)). The client copies `Domains` into `SearchDomains` only when accept-dns (`CorpDNS`) is on ([`node_backend.go:1511-1521`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/node_backend.go#L1511-L1521)).

## 2. Headscale `dns:` block (0.29.3)

The config is loaded in `dns()` and turned into `tailcfg.DNSConfig` by `dnsToTailcfgDNS` ([`config.go:862-988`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L862-L988)).

| Key | Effect (source) | Repo value |
|---|---|---|
| `magic_dns` | Becomes `tailcfg.DNSConfig.Proxied` (the client comment says it "actually means 'enable MagicDNS'"). Default `true` ([`config.go:405`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L405), [`:968`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L968)). | `true` |
| `base_domain` | Required when `magic_dns` is on; headscale exits otherwise ([`config.go:963-965`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L963-L965)). It **must not equal the `server_url` host** and **must not be a suffix of it**, so that "Tailscale takes over the domain in BaseDomain, causing the headscale server and DERP to be unreachable" cannot happen ([`isSafeServerURL`, `config.go:1323-1350`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L1323-L1350), called at [`:1203-1208`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L1203-L1208)). The example config says it "_must_ be different from the server_url domain" and "must be a FQDN, without the trailing dot" ([`config-example.yaml:327-330`](https://github.com/juanfont/headscale/blob/v0.29.3/config-example.yaml#L327-L330)). | `minlaxz.internal` vs `badabing.myaddr.dev`: valid |
| `override_local_dns` | `true`: `nameservers.global` become `Resolvers`, the default for all queries. `false`: they become `FallbackResolvers` ([`config.go:971-975`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L971-L975)). The code default is `true` ([`config.go:407`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L407)). On the client, `FallbackResolvers` become defaults only in the cases handled by the final `switch`, e.g. when an exit node is in use ([`node_backend.go:1597-1618`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/node_backend.go#L1597-L1618)). Otherwise the device keeps its own resolver for non-tailnet names. The KB wording: "devices connected to your tailnet ignore their local DNS settings and always use the global nameservers" ([KB 1054](https://tailscale.com/kb/1054/dns)). | `false` |
| `nameservers.global` | IPs or DoH URLs; invalid entries are ignored with a warning ([`config.go:899-923`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L899-L923)). | Cloudflare v4/v6 |
| `nameservers.split` | Map of domain to resolvers, sent as `Routes` ([`config.go:929-959`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L929-L959), [`:977-979`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L977-L979)). The KB: a restricted nameserver "only applies to DNS queries matching a specific search domain" ([KB 1054](https://tailscale.com/kb/1054/dns)). | `{}` |
| `search_domains` | Appended after `base_domain` in `Domains` ([`config.go:984`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L984)). | `[]` |
| `extra_records` | Static list, read at startup, sent as `ExtraRecords` ([`config.go:880-888`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L880-L888), [`:970`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L970)). Changes "require a restart" ([`docs/ref/dns.md`](https://github.com/juanfont/headscale/blob/v0.29.3/docs/ref/dns.md)). The client only uses records of type `""`, `A`, or `AAAA` whose value parses as an IP, and puts them in `Hosts` ([`node_backend.go:1491-1509`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/node_backend.go#L1491-L1509)). `Hosts` is checked **before** node names ([`tsdns.go:753-756`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/net/dns/resolver/tsdns.go#L753-L756)). | `[]` |
| `extra_records_path` | JSON file watched with fsnotify and re-read on change; peers get a push ([`hscontrol/app.go:669-678`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/app.go#L669-L678), [`app.go:375-382`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/app.go#L375-L382), [`hscontrol/dns/extrarecords.go`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/dns/extrarecords.go)). Headscale exits if **both** `extra_records` and `extra_records_path` are set ([`config.go:570-571`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L570-L571)). | commented out (line 311) |

Repo observations:

- `scales/docker-compose.yaml:40` mounts `headscale-dns_records.json` at `/etc/headscale/dns_records.json`, but `extra_records_path` is commented out. Headscale does not read that file today. `scales/NOTES.md` calls it "extra MagicDNS records", which only becomes true once the path is set. The same mount appears on headplane (line 16); how headplane uses it was not checked.
- To turn on `extra_records_path`, **remove** the `extra_records: []` line. The check at `config.go:570` uses `viper.IsSet`. Viper most likely reports a key present in the file as set even when its value is empty, but that viper behaviour was not checked (see open questions).
- `ephemeral_node_inactivity_timeout` is a deprecated key. It still works, with a warning. The new key is `node.ephemeral.inactivity_timeout`, default `120s`, and it must be greater than `65s` ([`config.go:447`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L447), [`:481-494`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L481-L494), [`:556`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L556), [`:606-615`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L606-L615)).

## 3. Ephemeral nodes: names and IPs across reboots

### 3.1 Each boot is a brand-new node

- `tailscale-nodes/` stores state on tmpfs (`docker-compose.yaml`, `tmpfs: /var/lib/tailscale`) and sets `"ephemeral": true` (`config.json:11`). tsnet logs in with `LoginEphemeral` ([`tsnet/tsnet.go:952-953`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/tsnet/tsnet.go#L952-L953)).
- With no saved state, every start has fresh keys, so headscale takes the new-node path. That path allocates new IPs and seeds `GivenName` from the sanitised hostname ([`hscontrol/state/state.go:1915-1929`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/state.go#L1915-L1929)).

### 3.2 Name collision: the new node becomes `vllm-1`

- On every node write, `NodeStore` calls `resolveGivenName` ([`hscontrol/state/node_store.go:450-453`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/node_store.go#L450-L453)).
- The function reads: "On collision the label is bumped as base, base-1, base-2, …, first unused wins". It checks against **all** nodes except the node itself ([`node_store.go:574-605`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/node_store.go#L574-L605)). It ignores online status and ignores whether the node is ephemeral.
- `GivenName` is also a unique column ([`node.go:141`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/node.go#L141)).
- This matches Tailscale SaaS: "the new machine will get a name like `<hostname>-1`" ([KB 1098](https://tailscale.com/kb/1098/machine-names)).

**So yes, while the old `vllm` still exists, the new node is named `vllm-1`.**

### 3.3 `vllm.<base_domain>` keeps pointing at the old IP until the GC runs

- The old node stays in the peer map while offline. Headscale's only online filters in `NodeStore` are for primary-route election and HA probing ([`node_store.go:695-698`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/node_store.go#L695-L698), [`:924-927`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/node_store.go#L924-L927)). Peers are marked `Online: false`, not removed ([`node.go:511`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/node.go#L511)).
- Clients index every `nm.Peers` entry by name (§1), so `vllm.minlaxz.internal` (and the short name `vllm`) answers with **the old node's IP**. The new node answers only as `vllm-1.minlaxz.internal`.

### 3.4 When the old node goes away

- When a map session ends, `afterServeLongPoll` schedules deletion after the inactivity timeout ([`hscontrol/poll.go:101-105`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/poll.go#L101-L105)). A reconnect cancels it ([`poll.go:245-248`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/poll.go#L245-L248)).
- On timeout, the GC calls `DeleteNode` ([`app.go:155-173`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/app.go#L155-L173)), which frees its IPs ([`state.go:613`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/state.go#L613)).
- On headscale startup, every existing ephemeral node is rescheduled ([`app.go:658-667`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/app.go#L658-L667)).
- An explicit logout deletes an ephemeral node **immediately** ([`hscontrol/auth.go:215-230`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/auth.go#L215-L230); KB: "immediately removed from your network if you run `tailscale logout`", [KB 1111](https://tailscale.com/kb/1111/ephemeral-nodes)).
- sing-box does **not** log out on shutdown. `Endpoint.Close` closes the tsnet server ([`protocol/tailscale/endpoint.go:712-729`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/endpoint.go#L712-L729)), and tsnet's `close()` shuts down netstack and the LocalBackend without a logout call ([`tsnet.go:607-660`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/tsnet/tsnet.go#L607-L660)). A `docker compose down` or EC2 stop therefore leaves the old node in place for the full 30m.

### 3.5 After the GC, the new node keeps its `-N` suffix

- `GivenName` is re-derived only when a MapRequest carries a **changed** hostname, and only if the current name is still auto-derived ([`state.go:3051-3063`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/state.go#L3051-L3063), [`isAutoDerivedGivenName`, `state.go:2906-2922`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/state.go#L2906-L2922)).
- The hostname stays `vllm`, so the node stays `vllm-1`. This matches SaaS: "this machine will still maintain the `<hostname>-1` machine name" ([KB 1098](https://tailscale.com/kb/1098/machine-names)).
- The next boot gets `vllm` if both the old `vllm` and `vllm-1` are gone by then, and another `-N` if not. **The name depends on reboot timing.** (Inferred from the code above; not tested live.)

### 3.6 IPs are not reused

- With `allocation: sequential`, the allocator starts from the prefix's network address when headscale starts ([`hscontrol/db/ip.go:95-103`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/db/ip.go#L95-L103)). Each allocation walks forward from the *previous allocation*, skipping used and reserved addresses, and never wraps ([`ip.go:205-248`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/db/ip.go#L205-L248)).
- A deleted node's IP goes back into the free set ([`ip.go:406-412`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/db/ip.go#L406-L412)), but it is below `prev`, so it is not handed out again until headscale restarts. After a restart the walk begins again at the bottom and picks the lowest free address.
- KB: "The next time an ephemeral node is created, it will have a new IP address" ([KB 1111](https://tailscale.com/kb/1111/ephemeral-nodes)).

## 4. Resolving MagicDNS names from clients

### 4.1 sing-box `tailscale` endpoint (userspace, as in `scaffolds/client/`)

- **The endpoint on its own does not feed sing-box's DNS module.** Names are resolved by a separate DNS server of `type: tailscale` that points at the endpoint ([`docs/configuration/dns/server/tailscale.md`](https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/dns/server/tailscale.md)). When the endpoint is dialed with a *domain* destination, it resolves through the global `dnsRouter` ([`endpoint.go:764-770`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/endpoint.go#L764-L770)). Without a `tailscale` server and a matching rule, `vllm.minlaxz.internal` goes to whatever `dns.final` is.
- **What the `tailscale` server answers.** On every reconfig it copies netmap `Hosts` (extra records), `Routes`, `SearchDomains`, and `DefaultResolvers`, and it takes the **live** MagicDNS host source from the backend (`ExportMagicDNSHosts`, a fork-only export) ([`protocol/tailscale/dns_transport.go:109-171`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/dns_transport.go#L109-L171); [`ipn/ipnlocal/local_export.go`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/local_export.go)). A query is handled as follows ([`dns_transport.go:358-404`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/dns_transport.go#L358-L404)):
  1. Answer from `Hosts`, then from the MagicDNS host source.
  2. Otherwise, forward through split `Routes`.
  3. Otherwise, use the default resolvers only if `accept_default_resolvers`.
  4. Otherwise, **NXDOMAIN**. The docs: "if not enabled, `NXDOMAIN` will be returned for non-Tailscale domain queries".
- **Single-label names** (`vllm`) need `accept_search_domain: true` (new in 1.14). The server then retries against each search domain ([`dns_transport.go:306-345`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/dns_transport.go#L306-L345)).
- **Routing queries to it.** In 1.14 the documented pattern is a DNS rule `{"preferred_by": "ts", "action": "route", "server": "ts"}`. `preferred_by` with a `tailscale` server matches "MagicDNS hosts and DNS route suffixes" ([`docs/configuration/dns/rule.md:527-538`](https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/dns/rule.md#L527-L538); implemented by `PreferredDomain`, [`dns_transport.go:265-284`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/dns_transport.go#L265-L284)). Before 1.14 the pattern was `ip_accept_any`.
- **Accept-dns is on.** The endpoint starts from `ipn.NewPrefs()` ([`endpoint.go:692`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/endpoint.go#L692)), where `CorpDNS: true` ([`ipn/prefs.go:746`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/prefs.go#L746)), and `editPrefs` never turns it off ([`endpoint.go:587-615`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/endpoint.go#L587-L615)). Routes and search domains are therefore populated.
- **Footgun for this repo.** A `tailscale` DNS server fails at start with `endpoint not found: ts-ep` if the endpoint is missing ([`dns_transport.go:84-87`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/dns_transport.go#L84-L87)). Only one such server is allowed per endpoint (`:92-94`). The API strips Mesh sections for users without `ts_auth_key` (`api/app/utils.py`, CONTEXT.md "Mesh key"). The DNS server and its rule must be injected **with** the endpoint, not added to the shared template.
- **Current client behaviour (inferred).** `scaffolds/client/dns.json` has no `tailscale` server and `final: dns-remote` (NextDNS DoH). A query for `vllm.minlaxz.internal` is sent to NextDNS and should come back NXDOMAIN. Apps have to use the `100.x` IP.
- **Explicit queries to `100.100.100.100:53`** (e.g. `dig @100.100.100.100`). `route.json` now puts `ip_cidr 100.64.0.0/10 → ts-ep` (line 215) *above* the `port: 53 → hijack-dns` rule (line 219), so the packet is sent into `ts-ep`. sing-box dials it on the tsnet gVisor stack ([`endpoint.go:430-442`](https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/endpoint.go#L430-L442)). Tailscale's outbound intercept should hand quad-100 traffic to `handleMagicDNSUDP` ([`netstack.go:446`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/wgengine/netstack/netstack.go#L446), [`:842-870`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/wgengine/netstack/netstack.go#L842-L870)). **Unverified end to end.** Also, `docs/research/sing-box-route-matching.md` (2026-09-07) describes the opposite rule order; that part is out of date.

### 4.2 Official Tailscale client with a TUN (macOS / Linux)

- Accept-dns is on by default. The CLI reference: "Defaults to accepting DNS settings" ([KB 1080](https://tailscale.com/kb/1080/cli)). `NewPrefs` sets `CorpDNS: true` (above).
- With `magic_dns: true` the client installs `Routes` for the base domain and the reverse zones (§1). `compileConfig` then either points the OS at quad-100 for those suffixes (split DNS) or, when there are default resolvers "plus other stuff", sends everything "through quad-100" ([`net/dns/manager.go:306-354`](https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/net/dns/manager.go#L306-L354)).
- With `override_local_dns: false` and no split routes, only the tailnet suffixes are routed to quad-100. Other names keep using the OS resolver.
- On Linux, Tailscale works through systemd-resolved, or "backs up and replaces /etc/resolv.conf with its own DNS server (100.100.100.100)" ([KB 1188](https://tailscale.com/kb/1188/linux-dns)).
- Net effect: `vllm.minlaxz.internal` and `vllm` resolve with no config. They are subject to the stale-name and `-N` behaviour in §3.
- The per-OS mechanism (macOS `NetworkExtension` resolver settings) was not traced in source.

## 5. Alternatives for a node that is off most of the time

| Option | Stable name? | Stable IP? | What it costs |
|---|---|---|---|
| **A. Today: ephemeral + tmpfs + MagicDNS** | No. `vllm` or `vllm-N` depending on timing, and `vllm` can point at a dead IP for up to 30m (§3). | No: new IP every boot (§3.6). | Nothing to maintain, but callers cannot hard-code anything. |
| **B. Fixed IP assigned in headscale** | Name issues unchanged | **Not supported.** The node RPCs are Register/Delete/Expire/Rename/List/BackfillNodeIPs/SetTags/SetApprovedRoutes; none sets an address ([`proto/headscale/v1/headscale.proto:83-134`](https://github.com/juanfont/headscale/blob/v0.29.3/proto/headscale/v1/headscale.proto#L83-L134); CLI [`cmd/headscale/cli/nodes.go`](https://github.com/juanfont/headscale/blob/v0.29.3/cmd/headscale/cli/nodes.go)). `backfillips` only adds or removes IPs of a missing family. Editing the SQLite row is unsupported, and an ephemeral delete frees the IP anyway. | Not viable. |
| **C. `extra_records_path` record, e.g. `llm.minlaxz.internal → <current IP>`** | Yes, if you pick a label no node will ever take. `Hosts` wins over node names (§2). | No, but the record can follow the IP. | Something **on the headscale host** must rewrite the JSON after each boot, with the IP read via `headscale nodes list`. Nothing in headscale does this. The record also goes stale for the whole time the node is off. Only sing-box clients with a `tailscale` DNS server, and official clients, see it. Remove `extra_records: []` first (§2). |
| **D. Non-ephemeral node, state persisted on `/data` (EBS)** | **Yes, `vllm`.** Same node on every boot, so no collision and no GC. | **Yes.** Headscale's re-register path updates the existing node in place instead of allocating ([`state.go:2488-2520`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/state.go#L2488-L2520), existing-node branch). | The node key sits on disk; protect `/data`. It shows as offline in `headscale nodes list` while EC2 is off, which is harmless. Node key expiry: **tagged nodes never expire** ([`state.go:1899-1903`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/state/state.go#L1899-L1903)), so register with a tagged, non-ephemeral key. EBS snapshots copied to another AZ carry the same identity, so never run two copies at once. |

**Recommendation for `tailscale-nodes/`:** option D. Applied after this note (steps 1-3 and 5, sing-box profile variant). A tag turned out unnecessary: headscale 0.29.3 defaults `node.expiry` to `0`, "no default expiry (nodes never expire)" ([`config.go:83-87`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L83-L87), [`:446`](https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go#L446)).

1. Set `"ephemeral": false` in `config.json`.
2. Replace the `tmpfs` with a bind mount such as `/data/tailscale-nodes/state:/var/lib/tailscale`. `/data` is the hand-attached EBS volume from `userdata.sh`.
3. Mint a non-ephemeral pre-auth key with a tag. The key is only needed on first registration.
4. Delete the stale `vllm`/`vllm-N` nodes once, so the fresh registration gets the plain `vllm` label.
5. On the client side, a Mesh user can then use `http://vllm.minlaxz.internal:8000` in one of two ways:
   - Official client: works as is.
   - sing-box profile: the API adds a `tailscale` DNS server (`endpoint: ts-ep`) and a `preferred_by` rule next to `ts-ep`, only for users with a Mesh key.

   Or they can simply use the now-stable `100.64.x.y`.

## Open questions / unknowns

- **Viper `IsSet` on `extra_records: []`.** Not checked in viper source. The fatal "both set" check may or may not fire when the key is present but empty. Remove the line to be safe.
- ~~**`node.expiry` default in 0.29.3 for untagged nodes.**~~ Resolved: `0`, never expires (see §5).
- ~~**Pre-auth key syntax.**~~ Resolved: `headscale preauthkeys create --user <id> [--reusable] [--ephemeral] [--tags tag:x] [--expiration d]`; `--user` is a numeric ID ([`cmd/headscale/cli/preauthkeys.go:25-33`](https://github.com/juanfont/headscale/blob/v0.29.3/cmd/headscale/cli/preauthkeys.go#L25-L33)).
- **Headplane.** Whether it reads or writes `/etc/headscale/dns_records.json` was not checked.
- **quad-100 through the sing-box `ts-ep` outbound** (§4.1, last bullet). The path is inferred from source, not tested.
- **macOS mechanism.** How the official macOS client installs per-domain resolvers was not traced below `compileConfig`.
- **Line anchors.** The re-register branch (`state.go:2488-2520`, keyed on machine key + user) was checked. The edges of the `FallbackResolvers` switch range (`node_backend.go:1597-1618`) are approximate; re-check before quoting in a PR.
- **Live test.** Not done. A quick check: stop EC2, start it within 30m, then run `headscale nodes list` and `dig @100.100.100.100 vllm.minlaxz.internal` from an official client.

## Sources

Headscale v0.29.3 (primary):
- `config-example.yaml` DNS section: https://github.com/juanfont/headscale/blob/v0.29.3/config-example.yaml#L300-L374
- `hscontrol/types/config.go`: https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/config.go
- `hscontrol/types/node.go`: https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/types/node.go
- `hscontrol/state/state.go`, `node_store.go`: https://github.com/juanfont/headscale/tree/v0.29.3/hscontrol/state
- `hscontrol/db/ip.go`, `hscontrol/db/node.go` (ephemeral GC): https://github.com/juanfont/headscale/tree/v0.29.3/hscontrol/db
- `hscontrol/app.go`, `poll.go`, `auth.go`: https://github.com/juanfont/headscale/tree/v0.29.3/hscontrol
- `hscontrol/dns/extrarecords.go`: https://github.com/juanfont/headscale/blob/v0.29.3/hscontrol/dns/extrarecords.go
- `docs/ref/dns.md`: https://github.com/juanfont/headscale/blob/v0.29.3/docs/ref/dns.md
- `proto/headscale/v1/headscale.proto`: https://github.com/juanfont/headscale/blob/v0.29.3/proto/headscale/v1/headscale.proto

sing-box v1.14.0 (primary):
- `protocol/tailscale/dns_transport.go`: https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/dns_transport.go
- `protocol/tailscale/endpoint.go`: https://github.com/SagerNet/sing-box/blob/v1.14.0/protocol/tailscale/endpoint.go
- DNS server `tailscale` docs: https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/dns/server/tailscale.md (rendered: https://sing-box.sagernet.org/configuration/dns/server/tailscale/)
- DNS rule `preferred_by`: https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/dns/rule.md
- Tailscale endpoint docs: https://github.com/SagerNet/sing-box/blob/v1.14.0/docs/configuration/endpoint/tailscale.md

SagerNet/tailscale v1.102.1-sing-box-1.14-mod.4 (primary; fork of tailscale/tailscale):
- `ipn/ipnlocal/node_backend.go`: https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal/node_backend.go
- `ipn/ipnlocal/resolve.go`, `local.go`, `local_export.go`: https://github.com/SagerNet/tailscale/tree/v1.102.1-sing-box-1.14-mod.4/ipn/ipnlocal
- `net/dns/resolver/tsdns.go`: https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/net/dns/resolver/tsdns.go
- `net/dns/manager.go`: https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/net/dns/manager.go
- `wgengine/netstack/netstack.go`: https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/wgengine/netstack/netstack.go
- `tsnet/tsnet.go`: https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/tsnet/tsnet.go
- `ipn/prefs.go`: https://github.com/SagerNet/tailscale/blob/v1.102.1-sing-box-1.14-mod.4/ipn/prefs.go

Tailscale KB (primary, vendor docs):
- MagicDNS: https://tailscale.com/kb/1081/magicdns
- DNS in Tailscale: https://tailscale.com/kb/1054/dns
- Ephemeral nodes: https://tailscale.com/kb/1111/ephemeral-nodes
- Quad100: https://tailscale.com/kb/1381/what-is-quad100
- Machine names: https://tailscale.com/kb/1098/machine-names
- Linux DNS: https://tailscale.com/kb/1188/linux-dns
- CLI: https://tailscale.com/kb/1080/cli

Repo files read: `scales/headscale-config.yaml`, `scales/docker-compose.yaml`, `scales/NOTES.md`, `scales/headscale-dns_records.json` (empty), `tailscale-nodes/{config.json,docker-compose.yaml,entrypoint.sh,README.md}`, `scaffolds/client/{endpoints,dns,route}.json`, `api/app/utils.py`, `CONTEXT.md`.
