# Dew CIS Solutions — Python Developer Technical Assignment

---

## Project structure

```
dewcis/
├── part1/
│   ├── docker-compose.yml        # postgres + pgadmin + testenv
│   ├── setup.sh                  # auto-runs inside testenv container
│   ├── archive_files.py          # Part 1 — archiver CLI script
│   ├── main.py                   # Part 1 — FastAPI service + dashboard
│   ├── test_archive_files.py     # Part 1 — pytest test suite
│   └── debian-pkg/
│       ├── DEBIAN/control
│       └── usr/local/bin/archive-files
└── part2/
    ├── docker-compose.yml        # openldap + phpldapadmin
    ├── ldap-seed.ldif            # LDAP directory data
    └── ldap_query.py             # Part 2 — LDAP query script
```

---

## PART 1 — File Archiving System

### Section 1A — Database schema design

Two tables:

**`archive_runs`** — one row per script invocation
| Column | Type | Purpose |
|---|---|---|
| id | SERIAL PK | Unique run identifier |
| group_name | TEXT | Which Linux group was processed |
| started_at | TIMESTAMPTZ | Run start time |
| finished_at | TIMESTAMPTZ | Run end time (NULL while running) |
| duration_sec | NUMERIC | Wall-clock seconds |
| total_moved | INT | Files successfully moved |
| total_skipped | INT | Files/users skipped |
| total_errors | INT | Failures |
| status | TEXT | running / completed / completed_with_errors / failed |
| archive_root | TEXT | Destination root used |

**`archive_events`** — one row per file action (written as it happens, not in a batch)
| Column | Type | Purpose |
|---|---|---|
| id | SERIAL PK | |
| run_id | INT FK | Links to archive_runs |
| username | TEXT | Which user this file belongs to |
| source | TEXT | Full path of original file |
| destination | TEXT | Full path at archive location |
| status | TEXT | moved / skipped / error |
| reason | TEXT | Human-readable reason (for skips/errors) |
| occurred_at | TIMESTAMPTZ | Exact time of this event |

**Why this design?**
- Partial results are visible mid-run because each event is committed immediately
- Two runs of the same group produce two distinct `archive_runs` rows — easily distinguished
- The `status` column on `archive_runs` shows `running` until completion — interrupted runs are visible
- All required API queries are answered without subqueries or application-side joins

### Section 1B — API endpoint mapping

| Endpoint | SQL concept |
|---|---|
| `GET /runs` | `SELECT ... FROM archive_runs ORDER BY started_at DESC` |
| `GET /runs/{id}` | `SELECT` run + `JOIN` events on `run_id` |
| `GET /runs/{id}/files?status=moved` | `SELECT ... WHERE run_id=? AND status=?` |
| `GET /stats` | `SUM / COUNT / GROUP BY` on `archive_runs` |

### Section 1C — Robustness cases

| Scenario | Handling |
|---|---|
| Group does not exist | `grp.getgrnam()` raises `KeyError` → caught → log error → exit 1 |
| Group has no members | `gr_mem` is empty list → log info "nothing to do" → exit 0 |
| Home dir does not exist | Detected with `Path.exists()` → write `skipped` event → continue to next user |
| File permission denied | `PermissionError` caught per file → write `error` event → continue to next file |
| File already at destination | `dest.exists()` check before `shutil.move` → write `skipped` event |
| DB connection fails | `psycopg2.OperationalError` caught after `get_db_conn()` → log error → exit 1 |

---

## Verification guide — Part 1

### Step 1 — Start all services

```bash
cd part1
docker compose up -d
docker compose ps
```

Expected: all three services (`postgres`, `pgadmin`, `testenv`) show `healthy` or `running`.

### Step 2 — Run the archiver for the first time

```bash
docker compose exec testenv python3 /workspace/archive_files.py --group developers --db-host postgres
```

Expected output:
```
2025-01-01 12:00:00  INFO     archive_files.py  group='developers'  dry_run=False
2025-01-01 12:00:00  INFO     Group 'developers' (gid 1001) has 2 member(s): alice, bob
2025-01-01 12:00:00  INFO     Run #1 started for group 'developers'.
2025-01-01 12:00:00  INFO     [alice] Moved /home/alice/docs/q1-summary.txt → /archive/...
...
2025-01-01 12:00:01  INFO     Run #1 completed — moved: 16 | skipped: 0 | errors: 0 | 0.85s
```

### Step 3 — Verify data in the database

Open pgAdmin at http://localhost:5050 and log in with `admin@dewcis.com / adminpass`.
Add server: host=`postgres`, port=5432, db=`archivedb`, user=`archiveuser`, pass=`archivepass`.

Run this SQL in the query tool:

```sql
-- Confirm run was recorded
SELECT id, group_name, status, total_moved, total_skipped, total_errors, duration_sec
FROM archive_runs;

-- Confirm file events were written
SELECT username, source, destination, status, occurred_at
FROM archive_events
WHERE run_id = 1
ORDER BY occurred_at;

-- Confirm events were written progressively (not all at the same microsecond)
SELECT MIN(occurred_at), MAX(occurred_at), COUNT(*)
FROM archive_events WHERE run_id = 1;
```

### Step 4 — Start the FastAPI service

```bash
docker compose exec -d testenv bash -c \
  "pip install fastapi uvicorn --quiet && \
   uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir /workspace"
```

Or run it on your host machine (if Python is available):
```bash
pip install fastapi uvicorn psycopg2-binary
uvicorn main:app --reload --port 8000
```

Test with curl:
```bash
curl http://localhost:8000/runs | python3 -m json.tool
```

Expected JSON:
```json
[
  {
    "id": 1,
    "group_name": "developers",
    "status": "completed",
    "total_moved": 16,
    "total_skipped": 0,
    "total_errors": 0,
    "duration_sec": "0.850"
  }
]
```

Additional curl examples:
```bash
# Stats
curl http://localhost:8000/stats | python3 -m json.tool

# Single run with all file events
curl http://localhost:8000/runs/1 | python3 -m json.tool

# Filter by status
curl "http://localhost:8000/runs/1/files?status=moved" | python3 -m json.tool

# 404 for missing run
curl -i http://localhost:8000/runs/99999
# → HTTP 404  {"detail": "Run 99999 not found."}

# Auto docs
open http://localhost:8000/docs
```

![alt text](<Screenshot from 2026-04-08 16-26-25.png>)
![alt text](<Screenshot from 2026-04-08 16-27-28.png>)

### Step 5 — Open the dashboard

Navigate to: **http://localhost:8000/**

You will see:
- Summary bar: 1 run, 16 files archived, 0 skipped, 0 errors
- Runs table with one row for the `developers` run
- Click the row → side panel opens with all 16 file events

### Step 6 — Run the archiver a second time (same group)

While the dashboard is open in your browser:

```bash
docker compose exec testenv python3 /workspace/archive_files.py --group developers --db-host postgres
```

Within 10 seconds the dashboard auto-refreshes and a **second row** appears for `developers`.
The moved count will be 0 and skipped will be 16 — all files already exist at destination.

Run a different group to confirm separate run records:
```bash
docker compose exec testenv python3 /workspace/archive_files.py --group ops --db-host postgres
```

```bash
# Confirm two separate run records exist
curl http://localhost:8000/runs | python3 -m json.tool
# → array with 3 entries: developers (run 1), developers (run 2), ops (run 3)
```

### Step 7 — Build and install the Debian package

```bash
# 1. Build the .deb inside the testenv container
docker compose exec testenv dpkg-deb --build /workspace/debian-pkg /workspace/archive-files_1.0_all.deb

# 2. Install it
docker compose exec testenv dpkg -i /workspace/archive-files_1.0_all.deb

# 3. Verify it is available from PATH
docker compose exec testenv which archive-files
docker compose exec testenv archive-files --group developers --dry-run
```

Expected:
```
/usr/local/bin/archive-files
2025-01-01 12:05:00  INFO     archive_files.py  group='developers'  dry_run=True
...
```

---

## Testing — Part 1

### Run the automated tests

```bash
docker compose exec testenv bash -c "pip install pytest --break-system-packages -q && pytest /workspace/test_archive_files.py -v"
```

### Test scenarios covered

| Scenario | Test | Expected |
|---|---|---|
| Happy path — developers | `test_files_moved` | 16 events written, files at destination |
| Second run — same group | `test_already_archived_files_skipped` | skipped count increments |
| Second run — different timestamp | `test_second_run_different_timestamp_succeeds` | two archive dirs exist |
| Group not found | `test_group_not_found_exits_1` | exit code 1, no traceback |
| Empty group | `test_empty_group_exits_0` | exit code 0, no crash |
| Home dir missing | `test_missing_home_counted_as_skipped` | skipped=1, no crash |
| Empty home dir | `test_empty_home_counted_as_skipped` | skipped=1, no crash |
| Permission denied on file | `test_permission_error_counted_as_error` | error=1, run continues |
| DB connection fails | `test_db_connection_failure_exits_1` | exit code 1, clear message |
| API — missing run_id | `GET /runs/99999` | HTTP 404 JSON response |
| Events written per-file | `test_events_written_per_file` | ≥3 DB commits for 3 files |
| Dashboard auto-refresh | Open browser, run archiver | new row appears within 10 s |

---

## PART 2 — LDAP Query

### Setup

```bash
cd part2
docker compose up -d
# Wait 10 seconds for OpenLDAP to initialise
sleep 10
pip install ldap3
```

### Design notes

The script performs a **two-step lookup**:

1. **Group lookup** — search `ou=groups` with filter `(&(objectClass=posixGroup)(cn=<group>))` to get the `memberUid` list and `gidNumber`. The LDAP filter is applied server-side — we do not fetch all groups and filter in Python.

2. **Member lookup** — for each `memberUid`, search `ou=users` with filter `(&(objectClass=posixAccount)(uid=<uid>))` to retrieve `cn` and `homeDirectory`.

Attributes requested: groups → `cn, gidNumber, memberUid`; users → `uid, cn, homeDirectory`.

Group not found: the script prints a clear error to stderr and exits with code 1. No traceback.

### Running the script

```bash
# All four groups
python3 ldap_query.py developers
python3 ldap_query.py ops
python3 ldap_query.py finance
python3 ldap_query.py hr

# Non-existent group
python3 ldap_query.py phantom
echo "Exit code: $?"

# Single-member group
python3 ldap_query.py hr
```

### Expected output

```
$ python3 ldap_query.py developers
Group: developers (gidNumber: 2001)
Members:
  alice | Alice Mwangi | /home/alice
  bob   | Bob Otieno   | /home/bob

$ python3 ldap_query.py ops
Group: ops (gidNumber: 2002)
Members:
  carol | Carol Njeri  | /home/carol
  david | David Kamau  | /home/david

$ python3 ldap_query.py finance
Group: finance (gidNumber: 2003)
Members:
  eve   | Eve Wanjiku  | /home/eve
  frank | Frank Mutua  | /home/frank

$ python3 ldap_query.py hr
Group: hr (gidNumber: 2004)
Members:
  grace | Grace Achieng | /home/grace

$ python3 ldap_query.py phantom
Error: group 'phantom' not found in directory.

$ echo "Exit code: $?"
Exit code: 1
```

---
