# Upgrade

```sh
docker compose pull && docker compose up -d
```

For deployments already using only ShadowTLS, that is the whole upgrade path. The image carries the configs: every start copies the client template (`route.json`, `dns.json`, `inbounds.json`, ...) from the image into the volume, so rule and DNS changes land without touching it. `client/outbounds.json`, `server/`, and `cache/` persist; outbounds the image adds (new tags) are appended to `outbounds.json` on start, existing entries stay as they are.

`git pull` on the server is only needed when `docker-compose.yaml` changes or `.env` gains a new variable.

## Moving from `users.json` to the user store

[ADR 0006](adr/0006-sqlite-user-store-csv-import.md): the API no longer reads `users.json`. Convert it once, then import it:

```sh
git pull                                   # new docker-compose.yaml: mounts ./data, drops users.json
python3 scripts/users_json_to_csv.py users.json > users.csv
docker compose pull && docker compose up -d
```

Open the stats page `https://<APP_HOST>/ssm/server/v1/users`, choose `users.csv` under Import users and submit. If any row is bad, nothing is added and the response lists each `row N: reason`. Fix those rows in `users.csv` and import again. Until the import, existing users keep connecting (ssm-api still holds them), but `/c` serves them no Mesh, WARP or Full mode. After a good import, delete `users.json` and `users.csv`: both hold every PSK in plain text.

## Retiring Hysteria2 from an existing deployment

Use the updated Compose file and rebuild the config volume once after pulling images that include the retirement:

```sh
git pull
docker compose pull
docker compose down -v
docker compose up -d
```

This resets generated configs, cached users, and traffic counters. The host's `.env` and `./data/` survive; the API restores every user in its store, but users held only in the old cache are lost. Keep the same ShadowTLS and Shadowsocks values in `.env`. Remove the unused `HYSTERIA2_*` values and close the old UDP port in the VPS firewall. Clients pinned to Hysteria2 must switch to ShadowTLS or refresh their profile. Without the volume rebuild, persistent server and client configs retain the old transport entries.

Hysteria2 was retired because the operator observed delayed or failed connections when first opening the VPN and lower stability than ShadowTLS. The cause is still unknown; follow-up is tracked in [issue #65](https://github.com/minlaxz/nekohasekai/issues/65). All Hysteria2 docs and research are retained, including the [previous deployment instructions](research/hysteria2-deployment-before-retirement.md), for a possible return later.

## Outbound naming cleanup

[Issue #67](https://github.com/minlaxz/nekohasekai/issues/67): set `APP_DEFAULT_DNS_DETOUR=shadowsocks-uot` in the existing `.env`, and change any profile URL using `dd=Proxy` to `dd=shadowsocks-uot`. The `Proxy` group is removed and `All` is now `All Outbounds`. Rebuild the config volume with the procedure above, then refresh cached client profiles. If deploying both the Hysteria2 retirement and naming cleanup together, rebuild once using images containing both changes. Init only appends outbound tags to existing volumes; without the rebuild, the old groups and Remote DNS Detour options remain.

## Changing ports, SNI or passwords

Ports, SNI, the Server PSK, and the ShadowTLS password are written once. To change them, remove the volume:

```sh
docker compose down && docker volume rm sing-box_sing-box-configs && docker compose up -d
```
