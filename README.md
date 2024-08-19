A working configurations for sing-box (with docker)
===

> This is not automated script or something, but for those who would like to setup by hand.

### Anyway, install Docker first!

```sh
wget -qO- get.docker.com | bash

# Just add USER to docker group. :)

sudo groupadd docker || true
sudo usermod -aG docker $USER
newgrp docker

# Optional
docker network create proxy-net
```

### TCP Brutal Multiplexing for TCP proxies

```sh
bash <(curl -fsSL https://tcp.hy2.sh/)
```


### BBR congestion control for TUIC proxy
```sh
sudo nano /etc/sysctl.conf

net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr

sudo sysctl -p
```

- [sing-box examples](/sing-box/)
- [fscarmen-sing-box examples](/fscarmen-sb/)


<!-- ### My example setup -->
<!-- ```sh -->
<!-- git clone --single-branch --branch release https://github.com/minlaxz/nekohasekai.git -->
<!-- cd nekohasekai/reverse-proxy && ./setup.sh && cd ../.. -->
<!-- mv .env.sample .env -->
<!-- ``` -->
<!-- bash <(curl -fsSL https://tcp.hy2.sh/) -->
<!-- bash <(wget -qO- https://raw.githubusercontent.com/GFW4Fun/S-UI-PRO/master/s-ui-pro.sh) -install yes -->
