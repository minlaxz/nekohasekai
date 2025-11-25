#!/usr/bin/env bash
set -e

PORT=${START_PORT:-1080}
END_PORT=$((PORT + 10))
USERS_FILE="/sing-box/cache/users.json"

perform_cleanup() {
    echo "Running cleanup..."
    curl -sSL -X GET \
        "http://localhost:${END_PORT}/ssm/server/v1/users" \
        -H "Content-Type: application/json" \
        -o "$USERS_FILE" || echo "Failed to save users!"
    echo "Saved users to $USERS_FILE"
}

shutdown_handler() {
    echo "Container is stopping... shutting down sing-box..."

    kill "$pid" 2>/dev/null || true

    # Wait for sing-box to stop
    wait "$pid" 2>/dev/null || true

    echo "sing-box stopped. Now running cleanup..."
    perform_cleanup

    exit 0
}

trap shutdown_handler SIGTERM

wait_for_singbox() {
    echo "Waiting for sing-box API to become ready..."
    for i in {1..10}; do
        if curl -s "http://localhost:${END_PORT}/ssm/server/v1/users" >/dev/null; then
            echo "sing-box API is ready."
            return 0
        fi
        echo "Not ready yet... ($i)"
        sleep 1
    done
    echo "ERROR: sing-box API did not become ready in time."
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
    fi
}


python3 ./generator.py --start-port "$PORT" --shadowsocks --verbose
/sing-box/sing-box run -C /sing-box/conf &
pid=$!

# Wait for API
wait_for_singbox

# Restore users
restore_users

# Run normally
wait "$pid"

# Normal exit cleanup
perform_cleanup
