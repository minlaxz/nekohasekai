FROM ghcr.io/sagernet/sing-box:latest

RUN apk add --no-cache jq

WORKDIR /sing-box

COPY cache /sing-box/cache.default
COPY server /sing-box/server.default
COPY client /sing-box/client.default

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
