List of tested proxy protols

- VLESS, Trojan, ShadowTLS
- Hysteria2, TUIC, Naive


#### TCP-based proxy protocol

| Agreement |
| :--- |
| [**Trojan**](Trojan) |
| [**VLESS**](VLESS) |
| [**ShadowTLS**](ShwdowTLS) |


#### UDP-based proxy protocol

| Agreement |
| :--- |
| [**Hysteria2**](Hysteria2) |
| [**TUIC**](TUIC) |
| [**Naive**](NAIVE) |


### Generate SSC (self signed certificate)
```sh
./generate-certificate.sh
```

### For TUIC
```sh
sudo nano /etc/sysctl.conf

net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr

sudo sysctl -p
```

