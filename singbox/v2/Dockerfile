FROM alpine:latest
ARG TARGETARCH
ENV ARCH=$TARGETARCH

WORKDIR /sing-box

RUN apk update && apk add --no-cache bash jq curl &&\
  mkdir -p /sing-box/conf &&\
  chmod +x /sing-box/init.sh &&

ARG SINGBOX_VERSION
RUN ONLINE_VERSION=$(curl https://api.github.com/repos/SagerNet/sing-box/releases/latest | jq .tag_name)
ENV SINGBOX_VERSION=${ONLINE_VERSION//\"/}
RUN curl https://github.com/SagerNet/sing-box/releases/sing-box-${SINGBOX_VERSION}-linux-${ARCH}.tar.gz -o /sing-box.tar.gz
RUN tar xz -C /sing-box -f /sing-box.tar.gz --strip-components=1
RUN rm -rf /sing-box.tar.gz /var/cache/apk/*

COPY init.sh .
CMD [ "./init.sh" ]
