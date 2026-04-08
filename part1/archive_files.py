"""
archive_files.py
================
Archive home-directory files for every member of a Linux group.
All events are persisted to PostgreSQL in real time.
"""

import argparse
import grp
import logging
import os
import pwd
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("archive_files")


# Database

DDL = """
CREATE TABLE IF NOT EXISTS archive_runs (
    id            SERIAL PRIMARY KEY,
    group_name    TEXT        NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    duration_sec  NUMERIC(10,3),
    total_moved   INT         NOT NULL DEFAULT 0,
    total_skipped INT         NOT NULL DEFAULT 0,
    total_errors  INT         NOT NULL DEFAULT 0,
    status        TEXT        NOT NULL DEFAULT 'running',   -- running | completed | failed
    archive_root  TEXT        NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_events (
    id          SERIAL PRIMARY KEY,
    run_id      INT         NOT NULL REFERENCES archive_runs(id) ON DELETE CASCADE,
    username    TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    destination TEXT,
    status      TEXT        NOT NULL,   -- moved | skipped | error
    reason      TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_run_id ON archive_events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_status  ON archive_events(status);
"""


def get_db_conn(args):
    return psycopg2.connect(
        host=args.db_host,
        port=args.db_port,
        dbname=args.db_name,
        user=args.db_user,
        password=args.db_password,
    )


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    log.debug("Schema verified / created.")


def create_run(conn, group_name: str, archive_root: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO archive_runs (group_name, archive_root, status)
            VALUES (%s, %s, 'running')
            RETURNING id
            """,
            (group_name, archive_root),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    log.info("Run #%d started for group '%s'.", run_id, group_name)
    return run_id


def write_event(conn, run_id: int, username: str, source: str,
                destination: str | None, status: str, reason: str | None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO archive_events
                (run_id, username, source, destination, status, reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (run_id, username, source, destination, status, reason),
        )
    conn.commit()


def finish_run(conn, run_id: int, moved: int, skipped: int, errors: int,
               duration: float, status: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE archive_runs
            SET finished_at  = NOW(),
                duration_sec = %s,
                total_moved  = %s,
                total_skipped= %s,
                total_errors = %s,
                status       = %s
            WHERE id = %s
            """,
            (round(duration, 3), moved, skipped, errors, status, run_id),
        )
    conn.commit()


# Archiving logic

def resolve_group(group_name: str):
    """Return grp.struct_group or None."""
    try:
        return grp.getgrnam(group_name)
    except KeyError:
        return None


def resolve_home(username: str) -> Path | None:
    """Return the user's home directory from the passwd database, or None."""
    try:
        return Path(pwd.getpwnam(username).pw_dir)
    except KeyError:
        return None


def archive_user_files(
    conn,
    run_id: int,
    username: str,
    home_dir: Path,
    archive_root: Path,
    timestamp: str,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Move every item in home_dir → archive_root/username/timestamp/.
    Returns (moved, skipped, errors)."""
    moved = skipped = errors = 0
    dest_base = archive_root / username / timestamp

    if not home_dir.exists():
        log.warning("[%s] Home directory missing: %s", username, home_dir)
        write_event(conn, run_id, username, str(home_dir), None,
                    "skipped", "home directory does not exist")
        return 0, 1, 0

    items = list(home_dir.rglob("*"))
    # Only move regular files (not the directories themselves)
    files = [p for p in items if p.is_file()]

    if not files:
        log.info("[%s] No files found in %s.", username, home_dir)
        write_event(conn, run_id, username, str(home_dir), None,
                    "skipped", "no files in home directory")
        return 0, 1, 0

    for src in files:
        # Compute relative path inside home, preserve structure
        rel = src.relative_to(home_dir)
        dest = dest_base / rel
        dest_str = str(dest)

        # Already archived — skip
        if dest.exists():
            log.info("[%s] Already archived, skipping: %s", username, src.name)
            write_event(conn, run_id, username, str(src), dest_str,
                        "skipped", "file already exists at destination")
            skipped += 1
            continue

        try:
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
            log.info("[%s] %s %s → %s",
                     username, "DRY-RUN would move" if dry_run else "Moved",
                     src, dest)
            write_event(conn, run_id, username, str(src), dest_str,
                        "moved", "dry-run" if dry_run else None)
            moved += 1
        except PermissionError as exc:
            log.error("[%s] Permission denied: %s — %s", username, src, exc)
            write_event(conn, run_id, username, str(src), dest_str,
                        "error", f"permission denied: {exc}")
            errors += 1
        except OSError as exc:
            log.error("[%s] OS error moving %s: %s", username, src, exc)
            write_event(conn, run_id, username, str(src), dest_str,
                        "error", str(exc))
            errors += 1

    return moved, skipped, errors


# Argument parsing

def parse_args():
    p = argparse.ArgumentParser(
        description="Archive home-folder files for Linux group members.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--group", required=True, help="Linux group name.")
    p.add_argument("--archive-root",
                   default=os.environ.get("ARCHIVE_ROOT", "/archive"),
                   help="Root archive directory.")
    p.add_argument("--db-host",     default=os.environ.get("DB_HOST", "localhost"))
    p.add_argument("--db-port",     default=int(os.environ.get("DB_PORT", 5432)), type=int)
    p.add_argument("--db-name",     default=os.environ.get("DB_NAME", "archivedb"))
    p.add_argument("--db-user",     default=os.environ.get("DB_USER", "archiveuser"))
    p.add_argument("--db-password", default=os.environ.get("DB_PASSWORD", "archivepass"))
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would happen without moving any files.")
    return p.parse_args()


# Main

def main() -> int:
    args = parse_args()
    archive_root = Path(args.archive_root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    log.info("=" * 60)
    log.info("archive_files.py  group='%s'  dry_run=%s", args.group, args.dry_run)
    log.info("Archive root: %s", archive_root)
    log.info("=" * 60)

    # Resolve group
    grp_entry = resolve_group(args.group)
    if grp_entry is None:
        log.error("Group '%s' not found on this system.", args.group)
        return 1

    members = grp_entry.gr_mem
    log.info("Group '%s' (gid %d) has %d member(s): %s",
             args.group, grp_entry.gr_gid, len(members), ", ".join(members))

    if not members:
        log.info("Group has no members. Nothing to do.")
        return 0

    # Connect to DB
    try:
        conn = get_db_conn(args)
    except psycopg2.OperationalError as exc:
        log.error("Cannot connect to database: %s", exc)
        return 1

    ensure_schema(conn)
    run_id = create_run(conn, args.group, str(archive_root))

    start_time = time.monotonic()
    total_moved = total_skipped = total_errors = 0
    final_status = "completed"

    try:
        for username in members:
            home_dir = resolve_home(username)
            if home_dir is None:
                log.warning("[%s] No passwd entry — skipping.", username)
                write_event(conn, run_id, username, f"/home/{username}",
                            None, "skipped", "user not in passwd database")
                total_skipped += 1
                continue

            m, s, e = archive_user_files(
                conn, run_id, username, home_dir,
                archive_root, timestamp, args.dry_run,
            )
            total_moved   += m
            total_skipped += s
            total_errors  += e

    except Exception as exc:
        log.exception("Unexpected error during archiving: %s", exc)
        final_status = "failed"
    finally:
        duration = time.monotonic() - start_time
        if total_errors > 0 and final_status == "completed":
            final_status = "completed_with_errors"
        finish_run(conn, run_id, total_moved, total_skipped,
                   total_errors, duration, final_status)
        conn.close()

    log.info("-" * 60)
    log.info("Run #%d %s — moved: %d | skipped: %d | errors: %d | %.2fs",
             run_id, final_status, total_moved, total_skipped,
             total_errors, duration)
    log.info("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
