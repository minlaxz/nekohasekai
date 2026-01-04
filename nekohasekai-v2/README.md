Generate sing-box configs with multiple inbounds and users.
===

Prepare the certificates and keys:

```sh
export SERVER_NAME="c.svr-0.yourdomain.tld" # for example
export ECH_DOMAIN="google.com" # for example

mkdir -p certs
openssl ecparam -genkey -name prime256v1 -out certs/private.key && \
  openssl req -new -x509 -days 36500 \
    -key certs/private.key \
    -out certs/certificate.crt \
    -subj "/CN=${SERVER_NAME}" \
    -addext "subjectAltName=DNS:${SERVER_NAME}"

# REALITY_KEYPAIR=$(sing-box generate reality-keypair)
#   AUTO_REALITY_PRIVATE=$(awk '/PrivateKey/{print $NF}' <<< "$REALITY_KEYPAIR")
#   AUTO_REALITY_PUBLIC=$(awk '/PublicKey/{print $NF}' <<< "$REALITY_KEYPAIR")
#   REALITY_PRIVATE=${CUSTOM_REALITY_PRIVATE:-$AUTO_REALITY_PRIVATE}
#   REALITY_PUBLIC=${CUSTOM_REALITY_PUBLIC:-$AUTO_REALITY_PUBLIC}
#   printf '%s\n' "$REALITY_PRIVATE" > certs/reality_private.key
#   printf '%s\n' "$REALITY_PUBLIC" > certs/reality_public.key

ECH_KEYPAIR=$(sing-box generate ech-keypair ${ECH_DOMAIN})
  AUTO_ECH_PUBLIC=$(sed -n '/-----BEGIN ECH CONFIGS-----/,/-----END ECH CONFIGS-----/p' <<< "$ECH_KEYPAIR")
  AUTO_ECH_PRIVATE=$(sed -n '/-----BEGIN ECH KEYS-----/,/-----END ECH KEYS-----/p' <<< "$ECH_KEYPAIR")
  ECH_PRIVATE=${CUSTOM_ECH_PRIVATE:-$AUTO_ECH_PRIVATE}
  ECH_PUBLIC=${CUSTOM_ECH_PUBLIC:-$AUTO_ECH_PUBLIC}
  printf '%s\n' "$ECH_PRIVATE" > certs/ech.key
  printf '%s\n' "$ECH_PUBLIC" > certs/ech.config
```

Then run the generator script:

```python
python generator.py --start-port 1080 --shadowsocks --trojan --hysteria2
```
