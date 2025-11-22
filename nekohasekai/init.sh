#!/usr/bin/env bash

PORT=${START_PORT:-1080}
python3 ./generator.py --start-port ${START_PORT:-1080} --shadowsocks --verbose
/sing-box/sing-box run -C /sing-box/conf
