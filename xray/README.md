Xray
===
[Xray](https://github.com/XTLS/Xray-core) is a powerful proxy tool that can be used to bypass network restrictions.

This is just my personal Xray setup to bypass Myanmar's fucking network restrictions.

1. Download and check the config file.
2. Read every comments in it and modify as needed.
```bash
mkdir -p xray && cd xray
curl -o config.jsonc https://raw.githubusercontent.com/minlaxz/nekohasekai/main/xray/vless-tls-tcp-reality/config.jsonc
```

1. inbounds[0].port should be same as docker publishing port.
2. xray expects config.json not config.jsonc (check at Dockerfile CMD) but we can mount jsonc as json
```bash
docker run -d -p 10444:10444 --name xray --restart=always -v $(pwd)/config.jsonc:/etc/xray/config.json ghcr.io/minlaxz/nekohasekai:xray
```
