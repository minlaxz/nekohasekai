FROM alpine:latest
ARG TARGETARCH
ENV ARCH=$TARGETARCH

WORKDIR /sing-box

RUN apk update && apk add --no-cache bash jq curl

# Download and extract latest sing-box release
RUN ONLINE_VERSION=$(curl -s https://api.github.com/repos/SagerNet/sing-box/releases/latest | jq -r .tag_name) && \
    curl -L "https://github.com/SagerNet/sing-box/releases/download/${ONLINE_VERSION}/sing-box-${ONLINE_VERSION}-linux-${ARCH}.tar.gz" \
      -o /sing-box.tar.gz && \
    tar xz -C /sing-box -f /sing-box.tar.gz --strip-components=1 && \
    rm -rf /sing-box.tar.gz /var/cache/apk/*

COPY init.sh .
RUN chmod +x /sing-box/init.sh
CMD ["./init.sh"]
