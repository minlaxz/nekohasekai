# User records live in SQLite; CSV import replaces users.json

The Users file (`users.json`, bind-mounted into the API) was read and rewritten whole on every create, renew, disable, enable, and delete, with no lock and no atomic write. A request racing the minute reconcile could lose an update, and a crash mid-write could truncate the file. Last fetch could not be kept across restarts. More admin features are planned, and each one would make this worse. We moved User records into SQLite (`./data/` on the host, mounted at `/data`), accessed through SQLModel with Alembic migrations, so new columns need no hand-written SQL. The database is the only source of truth. Reconcile (ADR 0003) is unchanged except that it reads the database.

## Considered Options

- **Keep users.json as the source, with the database as a cache rebuilt on start.** Rejected: hand edits would keep working, but the write race stays.
- **Import users.json once at container start, then write a marker.** Rejected in favour of an explicit admin action. The "empty table means import" variant would quietly bring back deleted users after a wipe. The marker variant is hidden one-time code that has to stay in the startup path forever.
- **CSV import and export on the admin dashboard (chosen).** Import is add-only and all-or-nothing: any invalid row, or any name or PSK that already exists, rejects the whole file. A stdlib script (`scripts/users_json_to_csv.py`) converts an old `users.json`.

## Consequences

- A new or upgraded VPS starts with an empty store until the admin imports. Login still works because the Admin credential comes from env. ssm-api keeps serving existing users in the meantime, because reconcile leaves alone users with no User record. Until the import, `/c` serves profiles without Mesh, WARP, or Full mode.
- User export is a plain-text dump of every secret.
- Editing `users.json` by hand no longer does anything. The mount is removed.
