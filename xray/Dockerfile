# Dockerfile for xray based alpine
# Reference URL:
# https://github.com/XTLS/Xray-core
# https://github.com/v2fly/v2ray-core
# https://github.com/v2fly/geoip
# https://github.com/v2fly/domain-list-community

FROM alpine/openssl:latest AS openssl

RUN openssl ecparam -genkey -name prime256v1 -out /private.key && \
openssl req -new -x509 -days 36500 -key /private.key -out /cert.pem -subj "/CN=mozilla.org"

FROM alpine:latest AS dist
LABEL maintainer="Min Latt<minminlaxz@gmail.com>"

ARG TARGETARCH
ENV ARCH=$TARGETARCH

WORKDIR /xray

COPY --from=openssl /private.key /xray/cert/private.key
COPY --from=openssl /cert.pem /xray/cert/cert.pem
COPY docker-init.sh init.sh

RUN set -ex &&\
	apk add --no-cache tzdata ca-certificates &&\
	mkdir -p /var/log/xray /usr/share/xray &&\
	chmod +x init.sh
	# wget -O /usr/share/xray/geosite.dat https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat &&\
	# wget -O /usr/share/xray/geoip.dat https://github.com/v2fly/geoip/releases/latest/download/geoip.dat

VOLUME /etc/xray
ENV TZ=Asia/Yangon
CMD [ "./init.sh" ]
