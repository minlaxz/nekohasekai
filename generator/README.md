Download sing-box binary from GitHub releases

```sh
VERSION=1.12.14  # Replace with the desired version
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    TARGETARCH=amd64
elif [ "$ARCH" = "aarch64" ]; then
    TARGETARCH=arm64
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi
curl -LJ "https://github.com/SagerNet/sing-box/releases/download/v${VERSION}/sing-box-${VERSION}-linux-${ARCH}.tar.gz" -o /tmp/sing-box.tar.gz

tar -xz -C ./ -f /tmp/sing-box.tar.gz --strip-components=1 && rm /tmp/sing-box.tar.gz
```

First think about two domain names for TLS handshake with TLS1.3 support and for ECH. I will use

- `mozilla.org` for TLS handshake server name and
- `google.com` for ECH domain since those are not blocked here, in Myanmar.

```sh
export TLS_SERVER_NAME=mozilla.org
export ECH_DOMAIN=google.com
```

Then generate self-signed certificate and private key:

```sh
mkdir -p certs && \
openssl ecparam -genkey -name prime256v1 -out data/certs/private.key && \
openssl req -new -x509 -days 36500 -key data/certs/private.key -out data/certs/certificate.crt \
-subj "/CN=${TLS_SERVER_NAME}" \
-addext "subjectAltName=DNS:${TLS_SERVER_NAME}"
```

Generate Reality keypair:

```sh
REALITY_KEYPAIR=$(./sing-box generate reality-keypair)
AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}
printf '%s\n' "$REALITY_PRIVATE" > data/certs/reality_private.key
printf '%s\n' "$REALITY_PUBLIC" > data/certs/reality_public.key
```

Generate ECH keypair:

```sh
ECH_KEYPAIR=$(./sing-box generate ech-keypair ${ECH_DOMAIN})
AUTO_ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
AUTO_ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
ECH_PRIVATE=${CUSTOM_ECH_PRIVATE:-$AUTO_ECH_PRIVATE}
ECH_PUBLIC=${CUSTOM_ECH_PUBLIC:-$AUTO_ECH_PUBLIC}
printf '%s\n' "$ECH_PRIVATE" > data/certs/ech.key
printf '%s\n' "$ECH_PUBLIC" > data/certs/ech.config
```

Add users to `users.yaml`

- A user must have a unique name, password, and UUID.
- It's recommended to use a strong password and a randomly generated UUID.
- Generate UUID (just in case you don't have one):

```sh
UUID=$(uuidgen)
echo "Generated UUID: $UUID"
```

Install dependencies:

```sh
python3 -m pip install -r requirements.txt
```

Run generator:

```sh
python3 app.py \
    --start-port 8820 \
    --tls-server-name $TLS_SERVER_NAME \
    --obfs_password "your_obfs_password"
```

Check out [app.py](app.py) for more options and details.

Run sing-box with the generated configuration:

```sh
./sing-box run -c config.jsonc
```

Run Tests:

```sh
pytest -vv
```
