# Generate sing-box configs with multiple inbounds and users.

1. Generate certificates and keys:

```sh
export SERVER_NAME="c.svr-0.yourdomain.tld" # for example
export ECH_DOMAIN="google.com" # for example
docker pull ghcr.io/sagernet/sing-box:v1.12.14

mkdir -p certs && openssl ecparam -genkey -name prime256v1 -out certs/private.key && \
  openssl req -new -x509 -days 36500 -key certs/private.key -out certs/certificate.crt \
    -subj "/CN=${SERVER_NAME}" \
    -addext "subjectAltName=DNS:${SERVER_NAME}"

REALITY_KEYPAIR=$(docker run --rm ghcr.io/sagernet/sing-box:v1.12.14 generate reality-keypair)
  AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
  AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
  REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
  REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}
  printf '%s\n' "$REALITY_PRIVATE" > certs/reality_private.key
  printf '%s\n' "$REALITY_PUBLIC" > certs/reality_public.key

ECH_KEYPAIR=$(docker run --rm ghcr.io/sagernet/sing-box:v1.12.14 generate ech-keypair ${ECH_DOMAIN})
  AUTO_ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
  AUTO_ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
  ECH_PRIVATE=${CUSTOM_ECH_PRIVATE:-$AUTO_ECH_PRIVATE}
  ECH_PUBLIC=${CUSTOM_ECH_PUBLIC:-$AUTO_ECH_PUBLIC}
  printf '%s\n' "$ECH_PRIVATE" > certs/ech.key
  printf '%s\n' "$ECH_PUBLIC" > certs/ech.config
```

2. Then run the generator script:

```python
python generator.py --start-port 1080 --shadowsocks --trojan --hysteria2
```

3. Copy sample.env to .env and modify as needed (probably you only need to set the following):

- APP_CONFIG_HOST={should be same as `SERVER_NAME` above}

4. Check config.yaml and modify as needed.

- users add your users.
- tls.server_name should be same as `SERVER_NAME` above.
- inbounds[hysteria2].obfs.password set your obfs password.

5. Compose up!

```sh
docker compose up -d
```
