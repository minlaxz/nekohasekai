#!/usr/bin/env bash

SKIP_INIT=${SKIP_INIT:-"false"}

# Check all files exist
# `configs`, `public`, `cache` skeleton files are copied at Docker build time
# `certs` will be mounted at Docker runtime, check docker-compose.yml and Readme
for dir in certs configs public cache; do
  if [ ! -d "/sing-box/$dir" ]; then
    echo "Directory /sing-box/$dir is missing, exiting."
    exit 1
  fi
done

# Initialize only if SKIP_INIT is false
if [ "$SKIP_INIT" == "false" ]; then
  echo "Initializing sing-box configuration ..."
  python3 ./main.py
fi

# Letting docker-compose handle subsequence CMD instruction like python ....py ... or fastapi ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"