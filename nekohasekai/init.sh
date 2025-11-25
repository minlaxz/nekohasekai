#!/usr/bin/env bash
set -e

PORT=${START_PORT:-1080}
END_PORT=$((PORT + 10))
USERS_FILE="/sing-box/cache/users.json"

wait_for_singbox() {
    echo "Waiting for sing-box API to become ready..."

    for i in {1..10}; do
        if curl -s "http://localhost:${END_PORT}/ssm/server/v1/users" >/dev/null; then
            echo "sing-box API is ready."
            return 0
        fi
        echo "sing-box not ready yet... (attempt $i)"
        sleep 1
    done

    echo "ERROR: sing-box API did not become ready in time."
    return 1
}

restore_users() {
    if [[ -f "$USERS_FILE" ]]; then
        echo "Found existing users.json — restoring users..."

        users=$(jq -c '.users // .[] // .' "$USERS_FILE" 2>/dev/null || echo "")

        if [[ -z "$users" ]]; then
            echo "users.json is empty or invalid"
            return
        fi

        echo "$users" | jq -c '.[]?' | while read -r user; do
            echo "Registering user: $user"
            curl -sSL -X POST "http://localhost:${END_PORT}/ssm/server/v1/users" \
                -H "Content-Type: application/json" \
                -d "$user" >/dev/null || \
                echo "Failed to register: $user"
        done
    else
        echo "No existing users.json found."
    fi
}

cleanup() {
    echo "Container is stopping... running cleanup."
    curl -sSL -X GET \
        "http://localhost:${END_PORT}/ssm/server/v1/users" \
        -H "Content-Type: application/json" \
        -o "$USERS_FILE"
    echo "Saved users to $USERS_FILE"
}

trap cleanup SIGTERM

python3 ./generator.py --start-port "$PORT" --shadowsocks --verbose
/sing-box/sing-box run -C /sing-box/conf &
pid=$!
wait_for_singbox
restore_users
wait "$pid"
# cleanup on normal exit
cleanup
