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
> (not recommended as brutal bandwidth is flat and may be detected by some ISPs DPI)

```sh
bash <(curl -fsSL https://tcp.hy2.sh/)
```


### 3. BBR congestion control for TUIC proxy
```sh
echo net.core.default_qdisc=fq | sudo tee -a /etc/sysctl.conf
echo net.ipv4.tcp_congestion_control=bbr | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 4. Swap memory (optional, but recommended for low RAM VPS)
```sh
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 5. What are these directories?
- [rules](/rules/) - OONI probe for adblocking and proxy routing, check this [branch](https://github.com/minlaxz/nekohasekai/tree/route-rules) for more details
- [api](/api/) - dynamic config generator for sing-box clients
- [sing-box](/sing-box/) - sing-box server side configs


### 6. repo name
- [nekohasekai](https://github.com/nekohasekai)


### 7. What to do next?
- start from [sing-box](/sing-box/) directory