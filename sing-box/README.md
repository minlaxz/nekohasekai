First think about two domain names for TLS handshake with TLS1.3 support and ECH.

I will use `mozilla.org` as an example for TLS handshake server name and `google.com` for ECH domain since those are not blocked here.

```sh
export TLS_SERVER_NAME=mozilla.org
export ECH_DOMAIN=google.com
```

Generate certificate and key:

```sh
mkdir -p certs && \
openssl ecparam -genkey -name prime256v1 -out certs/private.key && \
openssl req -new -x509 -days 36500 -key certs/private.key -out certs/certificate.crt \
-subj "/CN=${TLS_SERVER_NAME}" \
-addext "subjectAltName=DNS:${TLS_SERVER_NAME}"
```

Generate Reality keypair:

```sh
REALITY_KEYPAIR=$(docker run --rm ghcr.io/sagernet/sing-box:v1.12.14 generate reality-keypair)
AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}
printf '%s\n' "$REALITY_PRIVATE" > certs/reality_private.key
printf '%s\n' "$REALITY_PUBLIC" > certs/reality_public.key
```

Generate ECH keypair:

```sh
ECH_KEYPAIR=$(docker run --rm ghcr.io/sagernet/sing-box:v1.12.14 generate ech-keypair ${ECH_DOMAIN})
AUTO_ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
AUTO_ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
ECH_PRIVATE=${CUSTOM_ECH_PRIVATE:-$AUTO_ECH_PRIVATE}
ECH_PUBLIC=${CUSTOM_ECH_PUBLIC:-$AUTO_ECH_PUBLIC}
printf '%s\n' "$ECH_PRIVATE" > certs/ech.key
printf '%s\n' "$ECH_PUBLIC" > certs/ech.config
```

Add users to users.yaml

- A user must have a unique name, password, and UUID.
- It's recommended to use a strong password and a randomly generated UUID.

Compose up!

```sh
docker compose up -d
```
