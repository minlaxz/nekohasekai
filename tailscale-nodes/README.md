# tailscale-nodes

Standalone. Puts a compose service on the Mesh (headscale), same idea as `../multiplexers/`,
but the thing exposed is another container instead of a sing-box service.

`docker-compose.yaml`, two containers:

- `ts` — sing-box with a `tailscale` endpoint. Owns the network namespace.
- `vllm` — `network_mode: service:ts`, so vLLM's `:8000` is `127.0.0.1:8000` inside `ts`.
  Route rule `ts-ep -> direct-out, override_address 127.0.0.1` sends tailnet traffic there.

Tailnet `100.x.x.x:8000` → `ts` → `127.0.0.1:8000` → vLLM.

## Files

| File | Role |
|---|---|
| `config.json` | sing-box config template. `${TSN_*}` placeholders. |
| `entrypoint.sh` | Fills placeholders from env, `sing-box check`, `sing-box run`. |
| `docker-compose.yaml` | `ts` + `vllm`. |
| `.env.sample` | Copy to `.env`. |

## Setup (on the EC2 host)

1. Mint a reusable, ephemeral key.
   ```sh
   headscale preauthkeys create --user <user> --reusable --ephemeral --expiration 1y
   ```
2. `cp .env.sample .env`, fill `TSN_*`.
3. Run.
   ```sh
   docker compose up -d
   docker compose logs -f ts
   ```

Ephemeral: state is a tmpfs, so each start is a new node. Headscale drops it after
`ephemeral_node_inactivity_timeout` (30m) once the EC2 is off. The IP may change per start.

## Client

From any Mesh node (no ACL policy set in headscale, so all nodes reach each other):

```sh
curl http://100.x.x.x:8000/v1/models
tailscale ping 100.x.x.x
```

## Traffic and costs

Only traffic to the node's tailnet IP enters the tailnet. sing-box's tailscale is userspace:
no TUN, no routes, no exit node. So model downloads leave EC2 the normal Docker way.

```
HF download:   vllm → docker bridge → EC2 → huggingface.co      (headscale not involved)
LLM request:   100.64.0.10 ⇄ WireGuard ⇄ ts → 127.0.0.1:8000   (tailnet)
```

What reaches the headscale VPS:

| Traffic | Size | When |
|---|---|---|
| Control (register, peer map) | KB | Always |
| LLM requests/responses | Small (text, images ≤ 1 MP) | Only if peers can't connect direct and fall back to DERP |

EC2 has a public IP, so peers normally go direct. A client riding ShadowTLS (see
`../scales/NOTES.md`) sends its tailnet traffic through the sing-box VPS instead: still not
headscale, but that VPS pays the bandwidth.

AWS: downloads into EC2 are free. A private subnet behind a NAT Gateway is not
(~$0.045/GB processed); use a public subnet with a public IP for big models.

## Verify

Downloads skip the tailnet:

```sh
# Public IP vllm uses for the internet: must be the EC2 IP, not a VPS IP
docker exec vllm python3 -c "import urllib.request; print(urllib.request.urlopen('https://checkip.amazonaws.com').read().decode())"
# ts only logs tailnet connections: no huggingface here during a download
docker compose logs ts | grep -i huggingface
```

Tailnet peers are direct, not relayed (from a tailscale CLI node, e.g. 100.64.0.10):

```sh
tailscale ping 100.x.x.x
# direct:  pong from vllm (100.x.x.x) via 3.x.x.x:41641 in 12ms
# relayed: pong from vllm (100.x.x.x) via DERP(headscale) in 80ms
tailscale status | grep vllm   # "direct 3.x.x.x:41641" vs "relay \"headscale\""
```

`tailscale ping` keeps trying to upgrade a relayed path to direct; a few DERP pongs first is normal.

No CLI on the client (sing-box client): on the headscale VPS, watch NET I/O while sending a big
request. Flat = direct.

```sh
docker stats headscale
```

## Notes

- No auth on vLLM: anyone on the tailnet can use it. Add `--api-key` to the vllm command if that matters.
- Plain ICMP `ping` rides sing-box's ping forwarding; `tailscale ping` (disco) works regardless.
- `ts` owns the netns. If `ts` alone restarts, `vllm` loses its network:
  `docker compose up -d --force-recreate`.
- All tailnet ports forward to `127.0.0.1`; only vLLM listens there.
