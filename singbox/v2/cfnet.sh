docker run \
    --network host \
    -d \
    --name cfnet \
    cloudflare/cloudflared:latest \
    tunnel --no-autoupdate run --token <YOUR_TOKEN>