echo "Generating a self-signed certificate for 'google.com'..."
# read -p "Enter the domain name: " DOMAIN

# https://gist.github.com/taoyuan/39d9bc24bafc8cc45663683eae36eb1a

# openssl genrsa -out cert.key 2048
# openssl req -new -key cert.key -out cert.csr
# openssl x509 -req -days 3650 -in cert.csr -signkey cert.key -out cert.crt

# SSC
# openssl req -new -newkey rsa:4096 -days 36500 -nodes -x509 \
#     -subj "/C=GB/ST=London/L=London/O=Global Security/OU=R&D Department/CN=$DOMAIN" \
#     -keyout $DOMAIN.key.pem -out $DOMAIN.cert.pem

openssl req -new -newkey rsa:4096 -days 36500 -nodes -x509 \
    -subj "/C=GB/ST=London/L=London/O=Global Security/OU=R&D Department/CN=google.com" \
    -keyout certs/google.com.key.pem -out certs/google.com.cert.pem


# # https://www.baeldung.com/openssl-self-signed-cert
# # Private key
# openssl genrsa -des3 -out domain.key 2048
# # Certificate Signing Request
# openssl req -key domain.key -new -out domain.csr

# # Single command to generate private key and CSR
# openssl req -newkey rsa:2048 -keyout domain.key -out domain.csr

# # Creating a Self-Signed Certificate
# openssl x509 -signkey domain.key -in domain.csr -req -days 36500 -out domain.crt
echo "Certificate generated."
