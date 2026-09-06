#!/usr/bin/env bash

# Setup uv and install dependencies
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv venv --python python3.12 .venv
source .venv/bin/activate
uv pip install typer
###

# Setup configuration files
mv sample.api.env api.env
mv sample.users.json users.json
###

# Download the latest release of sing-box and generate the configuration file
python cli.py download --force
python cli.py generate --port 9999
###

# Move the sing-box binary, libcronet.so, and systemd service file to the appropriate locations
sudo mv sing-box /usr/local/bin/sing-box
sudo mv libcronet.so /usr/local/lib/libcronet.so
sudo mv sing-box.service /etc/systemd/system/sing-box.service
###

# Reload systemd, enable the sing-box service
sudo systemctl daemon-reload
sudo systemctl enable sing-box.service
###

# Register users from users.json with SSM API
python cli.py register
###

# Setup Caddy
docker network create caddy-net
docker compose -f caddy-docker-compose.yaml up -d
###

# Start the sing-box service
sudo systemctl start sing-box.service
# Start the API server
docker compose up -d
###

# Miscellaneous: Check the status of the sing-box service and view its logs
sudo systemctl status sing-box.service
sudo journalctl -u sing-box.service -f
###

# Miscellaneous: Check the logs of the API server
docker compose logs -f api
###