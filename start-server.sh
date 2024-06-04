docker run -d \
--name xray \
-p 1443:1443 \
--restart=unless-stopped \
-v $(pwd)/config.json:/etc/xray/config.json \
teddysun/xray
