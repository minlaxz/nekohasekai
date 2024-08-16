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
docker network create proxy-net
```


[sing-box configuration examples](/sing-box/)


### TCP Brutal Multiplexing

```sh
bash <(curl -fsSL https://tcp.hy2.sh/)
```


### BBR congestion control
```sh
sudo nano /etc/sysctl.conf

net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr

sudo sysctl -p
```

### My example setup

```sh
git clone --single-branch --branch release https://github.com/minlaxz/nekohasekai.git
cd nekohasekai/reverse-proxy && ./setup.sh && cd ../..
mv .env.sample .env
```


<!-- bash <(curl -fsSL https://tcp.hy2.sh/) -->
<!-- bash <(wget -qO- https://raw.githubusercontent.com/GFW4Fun/S-UI-PRO/master/s-ui-pro.sh) -install yes -->
