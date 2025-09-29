A working configurations for sing-box (with docker)
===

> This is not automated script or something, but for those who would like to setup by hand.

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
- [rules](/rules/) - my rules for adblocking and routing, you can use as reference
- [scripts](/scripts/) - useful scripts for misc tasks
- [singbox](/singbox/) - sing-box configuration files and separated README
- [xray](/xray/) - xray configuration files (for vless proxy), _deprecated_


### 5. nekohasekai
- [nekohasekai](https://github.com/nekohasekai)