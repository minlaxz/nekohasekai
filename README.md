Configuration examples for sing-box
===

We first need three things:
1. Docker and compose extension
2. TCP Brutal Multiplexing (for TCP proxies)
3. BBR congestion control (for TUIC proxy)

### 1. Install Docker and compose extension

```sh
wget -qO- get.docker.com | bash
```

### 2. TCP Brutal Multiplexing for TCP proxies

```sh
bash <(curl -fsSL https://tcp.hy2.sh/)
```


### 3. BBR congestion control for TUIC proxy
```sh
echo net.core.default_qdisc=fq | sudo tee -a /etc/sysctl.conf
echo net.ipv4.tcp_congestion_control=bbr | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 4. What are these directories?
- [rules](/rules/) - my [rules](https://github.com/minlaxz/nekohasekai/tree/route-rules) for adblocking and proxy routing rules
- [api](/api/) - dynamic config generator for sing-box clients
- [nekohasekai](/nekohasekai/) - sing-box server side configs
- [examples](/examples/) - example configurations for other protocols


### 5. nekohasekai
- [nekohasekai](https://github.com/nekohasekai)