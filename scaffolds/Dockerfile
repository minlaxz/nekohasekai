FROM ghcr.io/sagernet/sing-box:latest

RUN apk add --no-cache jq

WORKDIR /sing-box

# Kept outside /sing-box so the volume mount never hides them (#14).
COPY cache /defaults/cache
COPY server /defaults/server
COPY client /defaults/client

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
