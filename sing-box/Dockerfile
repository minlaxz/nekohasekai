FROM python:3.12-slim AS singbox

ARG TARGETARCH
ARG START_PORT

# Pin sing-box version for reproducible builds and supply-chain security
# Update this version and the checksums below when upgrading
ARG SING_BOX_VERSION=1.12.22

# SHA256 checksums for sing-box binaries
# To update: download the binary and run: sha256sum sing-box-{VERSION}-linux-{ARCH}.tar.gz
# amd64: https://github.com/SagerNet/sing-box/releases/download/v1.12.22/sing-box-1.12.22-linux-amd64.tar.gz
# arm64: https://github.com/SagerNet/sing-box/releases/download/v1.12.22/sing-box-1.12.22-linux-arm64.tar.gz
ARG CHECKSUM_AMD64=50a70a1b71064a7d8ef63737fbef2aa36c991d8dc1c54598b9513c2a15e25e9f
ARG CHECKSUM_ARM64=95a9c143e6488584868fc5c03d809c88519c6af0d4ca4cb1fa8a49cc397ae992

ENV ARCH=$TARGETARCH

WORKDIR /sing-box

# Copy all skeleton files
COPY . .

RUN apt-get update && apt-get install --no-install-recommends -y curl jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip wheel setuptools cryptography pyyaml python-dotenv

RUN DOWNLOAD_URL="https://github.com/SagerNet/sing-box/releases/download/v${SING_BOX_VERSION}/sing-box-${SING_BOX_VERSION}-linux-${ARCH}.tar.gz" && \
    curl -LJ "${DOWNLOAD_URL}" -o /sing-box.tar.gz && \
    # Verify checksum based on architecture \
    if [ "$ARCH" = "amd64" ]; then \
        EXPECTED_CHECKSUM="${CHECKSUM_AMD64}"; \
    elif [ "$ARCH" = "arm64" ]; then \
        EXPECTED_CHECKSUM="${CHECKSUM_ARM64}"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    ACTUAL_CHECKSUM=$(sha256sum /sing-box.tar.gz | cut -d' ' -f1) && \
    if [ "$ACTUAL_CHECKSUM" != "$EXPECTED_CHECKSUM" ]; then \
        echo "Checksum verification failed!" && \
        echo "Expected: $EXPECTED_CHECKSUM" && \
        echo "Actual: $ACTUAL_CHECKSUM" && \
        exit 1; \
    fi && \
    echo "Checksum verification passed: $ACTUAL_CHECKSUM" && \
    tar xz -C /sing-box -f /sing-box.tar.gz --strip-components=1 && \
    rm -rf /sing-box.tar.gz /var/cache/apk/* && \
    chmod +x /sing-box/init.sh && \
    mkdir -p /sing-box-skel && \
    cp -a /sing-box/configs /sing-box/public /sing-box/cache /sing-box-skel/

# Generate configs at container runtime
ENTRYPOINT ["./init.sh"]
