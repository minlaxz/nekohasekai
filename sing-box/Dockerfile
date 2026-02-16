FROM python:3.12-slim AS singbox

ARG TARGETARCH
ARG START_PORT

ENV ARCH=$TARGETARCH

WORKDIR /sing-box

# Copy all skeleton files
COPY . .

RUN apt-get update && apt-get install --no-install-recommends -y curl jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip wheel setuptools cryptography pyyaml python-dotenv

RUN ONLINE_VERSION=$(curl -s https://api.github.com/repos/SagerNet/sing-box/releases/latest | jq -r .name) && \
    curl -LJ "https://github.com/SagerNet/sing-box/releases/download/v${ONLINE_VERSION}/sing-box-${ONLINE_VERSION}-linux-${ARCH}.tar.gz" \
    -o /sing-box.tar.gz && \
    tar xz -C /sing-box -f /sing-box.tar.gz --strip-components=1 && \
    rm -rf /sing-box.tar.gz /var/cache/apk/* && \
    chmod +x /sing-box/init.sh

# Generate configs at container runtime
ENTRYPOINT ["./init.sh"]
