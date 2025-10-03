docker run -d \
  --network host \
  cloudflare/cloudflared:latest \
  --edge-ip-version 6 \
  --protocol http2 \
  tunnel --no-autoupdate run \
  --token <YOUR_TOKEN_HERE>
