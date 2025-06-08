"""WebSocket client to log failed outbounds.
This script connects to a WebSocket server, listens for log messages,
and extracts information about failed outbound connections.
It logs the domain and associated IP addresses to a file, and
rotating the log file every 10 minutes.
Returns:
    None
"""

import asyncio
import websockets
import json
import re
from collections import defaultdict
from datetime import datetime
import os
from typing import DefaultDict, Dict, Any
import websockets.asyncio.connection

LOG_DIR = "logs"
ROTATE_INTERVAL_MINUTES = 10

os.makedirs(LOG_DIR, exist_ok=True)

# Connection data
connections: DefaultDict[str, Dict[str, Any]] = defaultdict(
    lambda: {"domain": None, "ips": set()}
)


def get_current_log_file():
    now = datetime.now()
    minute = (now.minute // ROTATE_INTERVAL_MINUTES) * ROTATE_INTERVAL_MINUTES
    ts = now.replace(minute=minute, second=0, microsecond=0)
    filename = f"{LOG_DIR}/failed-{ts.strftime('%Y%m%d-%H%M')}.txt"
    return filename


# Regex patterns
id_pattern = re.compile(r"\[(\d+)")
domain_pattern = re.compile(r"domain: ([\w\.-]+)")
ip_pattern = re.compile(r"lookup succeed for .*: (\d+\.\d+\.\d+\.\d+)")
fail_pattern = re.compile(r"open outbound connection.*timeout")


async def ping_keepalive(
    ws: websockets.asyncio.connection.Connection,
    interval: int = 20,
):
    while True:
        try:
            await asyncio.sleep(interval)
            await ws.ping()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Ping error] {e}")
            break


async def main():
    uri = "ws://localhost:6969/logs?level=debug"
    async with websockets.connect(uri, ping_interval=None) as ws:
        # Start ping task
        keepalive = asyncio.create_task(ping_keepalive(ws))

        try:
            async for message in ws:
                try:
                    log = json.loads(message)
                    payload = log.get("payload", "")
                except json.JSONDecodeError:
                    continue

                # Extract connection ID
                id_match = id_pattern.search(payload)
                if not id_match:
                    continue
                conn_id = id_match.group(1)

                # Domain
                if domain_match := domain_pattern.search(payload):
                    connections[conn_id]["domain"] = domain_match.group(1)

                # IP
                if ip_match := ip_pattern.search(payload):
                    connections[conn_id]["ips"].add(ip_match.group(1))

                # Timeout error
                if fail_pattern.search(payload):
                    conn_data = connections.get(conn_id)
                    if conn_data and conn_data["domain"] and conn_data["ips"]:
                        domain = conn_data["domain"]
                        ip_str = ", ".join(conn_data["ips"])
                        line = f"domain: {domain}, ip addresses: [{ip_str}]"
                        log_file = get_current_log_file()
                        with open(log_file, "a") as f:
                            f.write(line + "\n")

                        print(line)  # Also print to terminal
                    else:
                        print(
                            f"[WARN] Timeout occurred but no data for conn_id {conn_id}"
                        )
                    connections.pop(conn_id, None)

        finally:
            keepalive.cancel()


try:
    print("Started WebSocket client.")
    asyncio.run(main())
except KeyboardInterrupt:
    print("Exiting...")
except Exception as e:
    print(f"An error occurred: {e}")
