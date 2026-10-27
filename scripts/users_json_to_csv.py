"""Turn a retired users.json (ADR 0006) into a User import CSV on stdout.

    python3 scripts/users_json_to_csv.py users.json > users.csv

Standard library only, no checks: User import validates every row and reports what is wrong.
"""

import csv
import json
import sys

# Same columns as User export (api/app/routes/ssm.py CSV_FIELDS).
FIELDS = ["name", "password", "admin", "expires_at", "disabled", "ts_auth_key", "warp_key", "warp_ipv6"]


def cell(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


with open(sys.argv[1], encoding="utf-8") as f:
    users = json.load(f)["users"]
w = csv.writer(sys.stdout, lineterminator="\n")
w.writerow(FIELDS)
for u in users:
    w.writerow([cell(u.get(k, False if k in ("admin", "disabled") else None)) for k in FIELDS])
