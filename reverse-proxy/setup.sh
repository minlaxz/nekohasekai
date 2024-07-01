#!/bin/sh
set -e

docker network inspect proxy-net > /dev/null 2>&1 || docker network create proxy-net
echo "Enter your default host for nginx proxy server (e.g. anything.example.com):"
read DEFAULT_HOST
yq w -i ./docker-compose.yml services.nginx-proxy.environment[1] "DEFAULT_HOST=$DEFAULT_HOST"
docker-compose -f ./docker-compose.yml up -d