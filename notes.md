### SHADOWTLS SNI must be matched
- see at server.inbounds[1].handshake.server and client.outbounds[3].tls.server_name

### Others
[tunnelvision](https://sing-box.sagernet.org/manual/misc/tunnelvision/)
- enable includeAllNetworks under Settings - Packet Tunnel
- change TUN stack to `gvisor` see client.inbounds[0].stack
