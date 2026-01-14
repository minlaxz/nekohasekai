# Configuration Collection for sing-box

Configurations and tooling for [**sing-box**](https://github.com/SagerNet/sing-box), the universal proxy platform.

---

## Repository Overview

This repository provides guides to help bypass Myanmar Internet Restrictions using sing-box configurations on both the client and server side.

### Directory Structure

- **[`rules/`](./rules/)**  
  Scripts for collecting and generating routing rules from OONI data.  
  For more details, see the [`route-rules` branch](https://github.com/minlaxz/nekohasekai/tree/route-rules).

- **[`api/`](./api/)**  
  Client-side configuration generator exposed as an API.

- **[`sing-box/`](./sing-box/)**  
  Server-side sing-box configuration generator.

### Credits

The repository name **nekohasekai** comes from the author of **Project S**.  
Please consider supporting the original project and its maintainers ❤️

---

## Prerequisites

This setup is designed with Docker in mind. Before getting started, ensure your
system meets the following requirements:

1. **Docker** with the Compose plugin installed
2. **TCP Brutal Multiplexing** (for TCP-based proxies)
3. **BBR congestion control** (recommended for TUIC)
4. **Swap memory** (optional, but strongly recommended for low-RAM VPS)

---

## 1. Install Docker and Docker Compose

```sh
wget -qO- https://get.docker.com | bash
sudo usermod -aG docker $USER # Let's just add your user to the docker group
newgrp docker # Apply the new group membership without logging out
docker pull ghcr.io/sagernet/sing-box:v1.12.14
```

## 2. Enable TCP Brutal Multiplexing (TCP Proxies)

> ⚠️ Not recommended in most cases, as Brutal mode can result in overly flat
> bandwidth behavior for TCP connections.

```sh
bash <(curl -fsSL https://tcp.hy2.sh/)
```

## 3. Enable BBR Congestion Control (UDP-based proxies such as TUIC)

BBR significantly improves performance for UDP-based protocols such as TUIC.

```sh
echo net.core.default_qdisc=fq | sudo tee -a /etc/sysctl.conf
echo net.ipv4.tcp_congestion_control=bbr | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## 4. Configure Swap Memory (Example for a 512 MB RAM VPS)

Recommended for low-memory servers to avoid out-of-memory (OOM) issues.

```sh
fallocate -l 1G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## Next step

Start with the [sing-box/](./sing-box/README.md) directory to generate and deploy server-side configurations.

> There will be a lot of terms like ECH, TUIC, Brutal, etc.  
> If you are unfamiliar with these, please do research on each of them