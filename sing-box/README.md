# Generate sing-box configs with multiple inbounds and users.

1. Generate certificates and keys:

```sh
export TLS_SERVER_NAME=mozilla.org # for example
export ECH_DOMAIN=google.com # for example, can be different from TLS_SERVER_NAME

docker pull ghcr.io/sagernet/sing-box:v1.12.14

mkdir -p certs && openssl ecparam -genkey -name prime256v1 -out certs/private.key && \
  openssl req -new -x509 -days 36500 -key certs/private.key -out certs/certificate.crt \
    -subj "/CN=${TLS_SERVER_NAME}" \
    -addext "subjectAltName=DNS:${TLS_SERVER_NAME}"

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

2. Check config.yaml, users.yaml and modify them as needed.

- `users` add your users.
- `tls_server_name` should be same as `TLS_SERVER_NAME` above.
- `obfs_password` set your obfs password.

3. Copy sample.env to .env and modify as needed (probably you only need to set the following):

- APP_HS_HOST={your headscale domain, if you use headscale}
- APP_HS_API_KEY={your headscale api key, if you use headscale}

* 3a. If you use headscale, make sure to check [this](https://headscale.net/0.27.1/setup/install/container/) out

4. Then run the generator script:

```python
python3 generator.py --start-port 1080
```

5. Compose up!

```sh
docker compose up -d # or docker compose --profile with-headscale up -d
```
