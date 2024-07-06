#!/bin/sh

./generate-certificate.sh

# https://docs.docker.com/engine/reference/builder/#understand-how-cmd-and-entrypoint-interact
exec "$@"
