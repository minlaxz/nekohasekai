# MagicDNS

Applies to: Tailscale clients, sing-box `tailscale` endpoints, and any tailnet whose control server is Tailscale SaaS or headscale.

## One idea

MagicDNS = **every device on the tailnet gets a DNS name, answered by a resolver that runs on your own device**.

No DNS server on the internet knows these names. The control server sends every device a list of
peers (name + tailnet IP). Each device answers name lookups from that list, locally.

```
 control server ──── peer list: gpu-box = 100.64.0.7, nas = 100.64.0.3 ────▶ every device
                                                                              │
 app asks "gpu-box.example.internal" ──▶ 100.100.100.100 (on this device) ────┘ answers 100.64.0.7
```

Rule: **a MagicDNS name is only as fresh as the peer list, and only reaches apps whose DNS queries go to the tailnet resolver.**

## The pieces

| Piece | What it is |
|---|---|
| Machine name | Short label per device, e.g. `gpu-box`. Starts as the device hostname. Unique per tailnet. |
| Base domain | Tailnet-wide suffix, e.g. `example.internal`. Full name: `gpu-box.example.internal`. |
| `100.100.100.100` | "Quad100". A stub resolver inside the Tailscale process. Never leaves the device. |
| Search domain | The base domain is pushed as a search domain, so `gpu-box` alone also works. |
| Extra records | Hand-made name → IP entries pushed by the control server. Checked before machine names. |

Who answers a query, in order:

```
query ─▶ extra records? ─yes─▶ answer
          │no
          ▼
         machine name in peer list? ─yes─▶ answer (even if that peer is offline)
          │no
          ▼
         under the base domain? ─yes─▶ NXDOMAIN (answered locally, never forwarded)
          │no
          ▼
         split-DNS route for this suffix? ─yes─▶ forward to that nameserver
          │no
          ▼
         forward to global nameservers, or leave it to the OS resolver
```

## Without MagicDNS

```
laptop                                   tailnet (WireGuard)                gpu-box
┌──────────────────────────┐                                           ┌──────────────┐
│ curl http://100.64.0.7   │ ════════════════════════════════════════▶ │ :8000        │
│ (IP copied by hand from  │                                           │ 100.64.0.7   │
│  the admin console)      │                                           └──────────────┘
└──────────────────────────┘
          │
          ▼ gpu-box re-registers, gets 100.64.0.12
┌──────────────────────────┐
│ curl http://100.64.0.7   │ ══════════════════════▶ ✗ nothing there (or worse: a different device)
└──────────────────────────┘
```

Consequences:

- Every client hard-codes an IP. Any IP change means editing every client.
- Works everywhere, even in apps or clients that ignore tailnet DNS.
- Fine for devices whose IP never changes.

## With MagicDNS

```
laptop                                                                    gpu-box
┌───────────────────────────────────┐                                ┌──────────────┐
│ curl http://gpu-box.example.internal:8000                          │ :8000        │
│   │                               │                                │ 100.64.0.12  │
│   ▼ OS resolver: *.example.internal → 100.100.100.100              └──────────────┘
│ Quad100: peer list says gpu-box = 100.64.0.12                             ▲
│   │                               │                                       │
│   └──▶ connect 100.64.0.12 ═══════╪═══════════════════════════════════════┘
└───────────────────────────────────┘
```

Consequences:

- Clients use a name. The IP can change; the peer list update fixes every client at once.
- Only works when the app's DNS query reaches Quad100. The official client arranges that on the OS.
  A userspace client (no system DNS hook) must route tailnet names to the tailnet resolver itself.
- A name is not a health check: an offline peer still resolves to its old IP.

## Name collisions and ephemeral devices

An **ephemeral** device is deleted by the control server some time after it goes offline. If it
comes back with no saved state, it registers as a **new** device with new keys and a new IP.

```
boot 1:   gpu-box      = 100.64.0.7   (online)
power off ...           gpu-box still in peer list, offline, waiting for cleanup
boot 2:   gpu-box      = 100.64.0.7   (offline, not yet deleted)
          gpu-box-1    = 100.64.0.12  (new device, name taken so a suffix is added)

          gpu-box.example.internal   ─▶ 100.64.0.7   ✗ dead
          gpu-box-1.example.internal ─▶ 100.64.0.12  ✓
cleanup:  gpu-box deleted. gpu-box-1 keeps its "-1" name.
```

Consequences:

- The name you get depends on how long the device was off.
- For a stable name **and** a stable IP: make the device non-ephemeral and keep its state
  directory on persistent disk. Each boot is then the same device, not a new one.
- Or: an extra record under a label no device will ever take, updated by a script after each boot.

## What changes with headscale

Headscale is an open-source control server. MagicDNS works the same on the client; the knobs move
from the admin console into headscale's config file.

| Topic | Tailscale SaaS | headscale |
|---|---|---|
| Base domain | Generated (`tailXXXX.ts.net`) | You pick it: `dns.base_domain`. Must **not** equal or be a suffix of the headscale server's own domain, or clients would resolve the control server through MagicDNS and cut themselves off. |
| On/off | Console toggle | `dns.magic_dns` |
| Force all DNS through the tailnet | "Override local DNS" | `dns.override_local_dns` + `dns.nameservers.global` |
| Split DNS | Console | `dns.nameservers.split` |
| Custom records | Not available as plain A records | `dns.extra_records` (restart to change) or `dns.extra_records_path` (a watched JSON file; pick one, not both) |
| Pin a device's IP | Console "edit IP" | Not available |
| Key expiry | 180 days by default | `node.expiry`, default no expiry |

## Decision

```
Does the device's tailnet IP change?
├─ no  (non-ephemeral, state kept)
│     └─ use the IP or the MagicDNS name; both stay valid
└─ yes (ephemeral, or state wiped each boot)
      ├─ can you keep state on persistent disk?  → do that, make it non-ephemeral (preferred)
      └─ no
           ├─ clients can live with "name-1" and a stale window → MagicDNS name
           └─ need one fixed name                               → extra record + update script
Is the client userspace (no system DNS hook)?
└─ yes → add a resolver for tailnet names inside the client, or names will not resolve
```

## References

- MagicDNS: https://tailscale.com/kb/1081/magicdns
- Quad100: https://tailscale.com/kb/1381/what-is-quad100
- DNS in Tailscale: https://tailscale.com/kb/1054/dns
- Machine names: https://tailscale.com/kb/1098/machine-names
- Ephemeral nodes: https://tailscale.com/kb/1111/ephemeral-nodes
- headscale DNS: https://github.com/juanfont/headscale/blob/v0.29.3/docs/ref/dns.md
- headscale example config: https://github.com/juanfont/headscale/blob/v0.29.3/config-example.yaml
- sing-box `tailscale` DNS server: https://sing-box.sagernet.org/configuration/dns/server/tailscale/
