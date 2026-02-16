#!/usr/bin/env bash

SKIP_INIT=${SKIP_INIT:-"false"}

check_file() {
    prefix="/sing-box/certs/"
    local file="$prefix$1"
    if [ ! -f "$file" ]; then
        echo "Configuration file '$file' not found"
        return 1
    fi
    return 0
}

verify_configs() {
    local missing=0

    check_file "certificate.crt" || missing=1
    check_file "private.key" || missing=1
    check_file "ech.key" || missing=1
    check_file "ech.config" || missing=1

    return $missing
}

main() {
  for dir in certs configs public cache; do
    if [ ! -d "/sing-box/$dir" ]; then
      echo "Directory /sing-box/$dir is missing, exiting."
      exit 1
    fi
  done

  # Seed bind-mounted directories with skeleton files on first run
  for dir in configs public cache; do
    if [ -d "/sing-box-skel/$dir" ] && [ -z "$(ls -A "/sing-box/$dir" 2>/dev/null)" ]; then
      echo "Seeding /sing-box/$dir from /sing-box-skel/$dir ..."
      cp -a "/sing-box-skel/$dir/." "/sing-box/$dir/"
    fi
  done

  if [ ! verify_configs ]; then
    echo "Configuration files are missing."
    exit 1
  fi

  # Initialize only if SKIP_INIT is false
  if [ "$SKIP_INIT" == "false" ]; then
    echo "Initializing sing-box configuration ..."
    python3 ./main.py
  fi
}

# Check all files exist
# `configs`, `public`, `cache` skeleton files are copied at Docker build time
# `certs` will be mounted at Docker runtime, check docker-compose.yml and Readme
main



# Letting docker-compose handle subsequence CMD instruction like python ....py ... or fastapi ...
# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"
