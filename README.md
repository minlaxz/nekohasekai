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
```

### First, setup a Nginx Reverse Proxy (Auto SSL)

Go [here](/reverse-proxy/)


### Second, setup sing-box

Go [here](/sing-box/)


<!-- bash <(curl -fsSL https://tcp.hy2.sh/) -->
<!-- bash <(wget -qO- https://raw.githubusercontent.com/GFW4Fun/S-UI-PRO/master/s-ui-pro.sh) -install yes -->