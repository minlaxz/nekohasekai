FROM curlimages/curl:latest AS base
ARG TARGETARCH

ARG SINGBOX_VERSION=$(curl -s "https://api.github.com/repos/SagerNet/sing-box/releases" | awk -F '["v-]' '/tag_name/{print $5}' | sort -r | sed -n '1p')
ENV SINGBOX_VERSION=$SINGBOX_VERSION
RUN curl https://github.com/SagerNet/sing-box/releases/download/v$SINGBOX_VERSION/sing-box-$SINGBOX_VERSION-linux-$TARGETARCH.tar.gz -o /sing-box.tar.gz && tar xz -C / -f /sing-box.tar.gz --strip-components=1
RUN curl https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-${TARGETARCH} -o /jq

FROM alpine:latest AS top
ARG TARGETARCH
ENV ARCH=$TARGETARCH

WORKDIR /sing-box

COPY --from=base /sing-box ./sing-box
COPY --from=base /jq ./jq

COPY init.sh .

RUN set -ex &&\
  apk add --no-cache bash &&\
  mkdir -p /sing-box/conf &&\
  chmod +x /sing-box/init.sh &&\
  rm -rf /var/cache/apk/*

CMD [ "./init.sh" ]
