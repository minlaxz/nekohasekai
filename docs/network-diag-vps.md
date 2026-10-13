# Network diagnostics: per-user access on the VPS

Index: [network-diag.md](network-diag.md).

For "user X can still connect" or "user X cannot connect". First question:
which host does the client's profile point at? The same username exists on
more than one VPS, and a test on one host says nothing about the other.

## Is the user in ssm-api on this VPS

```sh
docker compose exec sing-box wget -qO- http://127.0.0.1:8888/server/v1/users | grep <name>
```

Empty = removed (Expired, or deleted). `/c` for that user answers 400
`User verification failed or quota exceeded.` from the same cause.

## Does the API still issue a profile for that user, per host

```sh
curl -s -o /dev/null -w '%{http_code}\n' 'https://<vps-a>/c?j=<name>&k=<psk>'
curl -s -o /dev/null -w '%{http_code}\n' 'https://<vps-b>/c?j=<name>&k=<psk>'
```

`k` is case-sensitive base64. 200 on one host and 400 on the other means
the client is simply on the other host.

## Which users and source IPs sing-box accepted since a time

Needs server log level `debug` or `info`; every accepted inbound connection
is tagged `[<name>]`.

```sh
docker compose logs sing-box --since 2026-10-05T17:58:00Z \
  | grep -o '\[[A-Za-z0-9_-]*\] inbound connection to' | sort | uniq -c
docker compose logs sing-box --since 2026-10-05T17:58:00Z \
  | grep -o 'inbound connection from [0-9.]*' | sort | uniq -c
```

Zero lines for a user who is "still connected" means the traffic is not
arriving here: other host, or `direct` on the client.

## Which host the client is really using

On the client, with the VPN on, open `https://ifconfig.me`. Compare with
`dig +short <vps-a>` and `dig +short <vps-b>`.
