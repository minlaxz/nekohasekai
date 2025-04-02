FROM alpine/openssl:latest AS openssl

RUN openssl ecparam -genkey -name prime256v1 -out /private.key && \
    openssl req -new -x509 -days 36500 -key /private.key -out /cert.pem -subj "/CN=mozilla.org"

FROM alpine:latest AS dist
ARG TARGETARCH
ENV ARCH=$TARGETARCH

WORKDIR /sing-box

COPY --from=openssl /private.key /sing-box/cert/private.key
COPY --from=openssl /cert.pem /sing-box/cert/cert.pem
COPY docker-init.sh /sing-box/init.sh

RUN set -ex &&\
  apk add --no-cache supervisor nginx bash &&\
  mkdir -p /sing-box/conf /sing-box/subscribe /sing-box/logs &&\
  chmod +x /sing-box/init.sh &&\
  rm -rf /var/cache/apk/*

CMD [ "./init.sh" ]