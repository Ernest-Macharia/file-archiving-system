"""
main.py
=======
FastAPI service — reads archive run data from PostgreSQL.
Start with:  uvicorn main:app --reload --port 8000

Endpoints
---------
GET /              Dashboard (HTML)
GET /runs          All runs summary
GET /runs/{id}     Single run + file events
GET /runs/{id}/files  File events, filterable by ?status=
GET /stats         Aggregate statistics
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# DB connection helper
# ---------------------------------------------------------------------------

DB_CONFIG = dict(
    host    =os.environ.get("DB_HOST",     "localhost"),
    port    =int(os.environ.get("DB_PORT", 5432)),
    dbname  =os.environ.get("DB_NAME",     "archivedb"),
    user    =os.environ.get("DB_USER",     "archiveuser"),
    password=os.environ.get("DB_PASSWORD", "archivepass"),
)


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def query(sql: str, params=None) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params=None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nothing to warm up — DB connections are per-request
    yield

app = FastAPI(
    title="Archive Files API",
    description="REST API for the file archiving system — Dew CIS Solutions",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------

@app.get("/runs", summary="List all archiving runs")
def list_runs():
    rows = query("""
        SELECT
            id, group_name, started_at, finished_at,
            duration_sec, total_moved, total_skipped,
            total_errors, status, archive_root
        FROM archive_runs
        ORDER BY started_at DESC
    """)
    return rows


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}", summary="Single run with all file events")
def get_run(run_id: int):
    run = query_one("""
        SELECT
            id, group_name, started_at, finished_at,
            duration_sec, total_moved, total_skipped,
            total_errors, status, archive_root
        FROM archive_runs WHERE id = %s
    """, (run_id,))

    if run is None:
        raise HTTPException(status_code=404,
                            detail=f"Run {run_id} not found.")

    events = query("""
        SELECT id, username, source, destination, status, reason, occurred_at
        FROM archive_events
        WHERE run_id = %s
        ORDER BY occurred_at
    """, (run_id,))

    run["files"] = events
    return run


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/files
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}/files", summary="File events for a run, filterable by status")
def get_run_files(
    run_id: int,
    status: Optional[str] = Query(
        None,
        description="Filter by status: moved | skipped | error",
        pattern="^(moved|skipped|error)$",
    ),
):
    # Verify run exists
    run = query_one("SELECT id FROM archive_runs WHERE id = %s", (run_id,))
    if run is None:
        raise HTTPException(status_code=404,
                            detail=f"Run {run_id} not found.")

    if status:
        rows = query("""
            SELECT id, username, source, destination, status, reason, occurred_at
            FROM archive_events
            WHERE run_id = %s AND status = %s
            ORDER BY occurred_at
        """, (run_id, status))
    else:
        rows = query("""
            SELECT id, username, source, destination, status, reason, occurred_at
            FROM archive_events
            WHERE run_id = %s
            ORDER BY occurred_at
        """, (run_id,))

    return rows


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------

@app.get("/stats", summary="Aggregate statistics across all runs")
def get_stats():
    totals = query_one("""
        SELECT
            COUNT(*)                  AS total_runs,
            COALESCE(SUM(total_moved),   0) AS total_files_archived,
            COALESCE(SUM(total_skipped), 0) AS total_skipped,
            COALESCE(SUM(total_errors),  0) AS total_errors
        FROM archive_runs
    """)

    recent = query_one("""
        SELECT group_name AS most_recent_group
        FROM archive_runs
        ORDER BY started_at DESC
        LIMIT 1
    """)

    busiest = query_one("""
        SELECT group_name AS busiest_group
        FROM archive_runs
        GROUP BY group_name
        ORDER BY SUM(total_moved) DESC
        LIMIT 1
    """)

    return {
        **totals,
        "most_recent_group": recent["most_recent_group"] if recent else None,
        "busiest_group":     busiest["busiest_group"]    if busiest else None,
    }


# ---------------------------------------------------------------------------
# GET /  — Dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Archive Dashboard — Dew CIS</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f4f6f9; color: #1a1a2e; }

  header {
    background: #1a1a2e; color: #fff; padding: 18px 32px;
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 1.2rem; font-weight: 600; }
  #refresh-indicator { font-size: 0.8rem; opacity: 0.65; }

  .stats-bar {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 16px; padding: 24px 32px;
  }
  .stat-card {
    background: #fff; border-radius: 10px; padding: 20px 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
  }
  .stat-card .label { font-size: 0.75rem; color: #777; text-transform: uppercase; letter-spacing: .05em; }
  .stat-card .value { font-size: 2rem; font-weight: 700; margin-top: 4px; }
  .stat-card.runs   .value { color: #4361ee; }
  .stat-card.moved  .value { color: #2ec4b6; }
  .stat-card.skip   .value { color: #f77f00; }
  .stat-card.err    .value { color: #e63946; }

  .section { padding: 0 32px 32px; }
  .section h2 { font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: #444; }

  table { width: 100%; border-collapse: collapse; background: #fff;
          border-radius: 10px; overflow: hidden;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  thead { background: #1a1a2e; color: #fff; }
  th, td { padding: 12px 16px; text-align: left; font-size: 0.875rem; }
  tbody tr { border-bottom: 1px solid #f0f0f0; cursor: pointer; transition: background .1s; }
  tbody tr:hover { background: #f0f4ff; }
  tbody tr:last-child { border-bottom: none; }

  .badge {
    display: inline-block; padding: 2px 10px; border-radius: 99px;
    font-size: 0.75rem; font-weight: 600;
  }
  .badge.completed  { background: #d1fae5; color: #065f46; }
  .badge.completed_with_errors { background: #fef3c7; color: #92400e; }
  .badge.running    { background: #dbeafe; color: #1e40af; }
  .badge.failed     { background: #fee2e2; color: #991b1b; }
  .badge.moved      { background: #d1fae5; color: #065f46; }
  .badge.skipped    { background: #fef3c7; color: #92400e; }
  .badge.error      { background: #fee2e2; color: #991b1b; }

  /* Detail panel */
  #detail-panel {
    display: none; position: fixed; top: 0; right: 0;
    width: 600px; height: 100vh; background: #fff;
    box-shadow: -4px 0 24px rgba(0,0,0,.15);
    overflow-y: auto; z-index: 100;
    padding: 24px;
  }
  #detail-panel.open { display: block; }
  #detail-panel h3 { font-size: 1rem; margin-bottom: 4px; }
  #detail-panel .meta { font-size: 0.8rem; color: #777; margin-bottom: 16px; }
  #detail-close {
    position: absolute; top: 16px; right: 20px;
    background: none; border: none; font-size: 1.4rem; cursor: pointer; color: #555;
  }
  #detail-table { font-size: 0.8rem; }
  #detail-table td { padding: 8px 10px; word-break: break-all; }

  .overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,.25); z-index: 99;
  }
  .overlay.open { display: block; }
</style>
</head>
<body>

<header>
  <h1>Archive Dashboard — Dew CIS Solutions</h1>
  <span id="refresh-indicator">Refreshes every 10 s</span>
</header>

<div class="stats-bar">
  <div class="stat-card runs">
    <div class="label">Total runs</div>
    <div class="value" id="s-runs">—</div>
  </div>
  <div class="stat-card moved">
    <div class="label">Files archived</div>
    <div class="value" id="s-moved">—</div>
  </div>
  <div class="stat-card skip">
    <div class="label">Skipped</div>
    <div class="value" id="s-skipped">—</div>
  </div>
  <div class="stat-card err">
    <div class="label">Errors</div>
    <div class="value" id="s-errors">—</div>
  </div>
</div>

<div class="section">
  <h2>Archiving runs</h2>
  <table id="runs-table">
    <thead>
      <tr>
        <th>#</th><th>Group</th><th>Started</th>
        <th>Duration</th><th>Moved</th><th>Skipped</th>
        <th>Errors</th><th>Status</th>
      </tr>
    </thead>
    <tbody id="runs-body">
      <tr><td colspan="8" style="text-align:center;color:#aaa;padding:32px">Loading…</td></tr>
    </tbody>
  </table>
</div>

<div class="overlay" id="overlay" onclick="closeDetail()"></div>

<div id="detail-panel">
  <button id="detail-close" onclick="closeDetail()">✕</button>
  <h3 id="detail-title">Run detail</h3>
  <div class="meta" id="detail-meta"></div>
  <table id="detail-table">
    <thead>
      <tr>
        <th>User</th><th>File</th><th>Destination</th>
        <th>Status</th><th>Reason</th>
      </tr>
    </thead>
    <tbody id="detail-body">
      <tr><td colspan="5" style="text-align:center;color:#aaa;padding:16px">Select a run</td></tr>
    </tbody>
  </table>
</div>

<script>
const fmt = {
  date: d => d ? new Date(d).toLocaleString() : '—',
  dur:  s => s != null ? s.toFixed(2) + ' s' : '—',
  badge: status => `<span class="badge ${status}">${status}</span>`,
};

async function loadStats() {
  const r = await fetch('/stats');
  const d = await r.json();
  document.getElementById('s-runs').textContent    = d.total_runs ?? 0;
  document.getElementById('s-moved').textContent   = d.total_files_archived ?? 0;
  document.getElementById('s-skipped').textContent = d.total_skipped ?? 0;
  document.getElementById('s-errors').textContent  = d.total_errors ?? 0;
}

async function loadRuns() {
  const r = await fetch('/runs');
  const runs = await r.json();
  const body = document.getElementById('runs-body');
  if (!runs.length) {
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#aaa;padding:32px">No runs yet. Execute archive_files.py to get started.</td></tr>';
    return;
  }
  body.innerHTML = runs.map(run => `
    <tr onclick="openDetail(${run.id})">
      <td>${run.id}</td>
      <td><strong>${run.group_name}</strong></td>
      <td>${fmt.date(run.started_at)}</td>
      <td>${fmt.dur(run.duration_sec)}</td>
      <td>${run.total_moved}</td>
      <td>${run.total_skipped}</td>
      <td>${run.total_errors}</td>
      <td>${fmt.badge(run.status)}</td>
    </tr>
  `).join('');
}

async function openDetail(runId) {
  document.getElementById('detail-panel').classList.add('open');
  document.getElementById('overlay').classList.add('open');
  document.getElementById('detail-body').innerHTML =
    '<tr><td colspan="5" style="text-align:center;color:#aaa;padding:16px">Loading…</td></tr>';

  const r = await fetch(`/runs/${runId}`);
  const run = await r.json();

  document.getElementById('detail-title').textContent =
    `Run #${run.id} — ${run.group_name}`;
  document.getElementById('detail-meta').textContent =
    `${fmt.date(run.started_at)} · ${fmt.dur(run.duration_sec)} · ` +
    `${run.total_moved} moved · ${run.total_skipped} skipped · ${run.total_errors} errors`;

  const body = document.getElementById('detail-body');
  if (!run.files.length) {
    body.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#aaa">No file events.</td></tr>';
    return;
  }
  body.innerHTML = run.files.map(f => `
    <tr>
      <td>${f.username}</td>
      <td style="font-family:monospace">${f.source.split('/').pop()}</td>
      <td style="font-family:monospace;font-size:0.75rem">${f.destination ?? '—'}</td>
      <td>${fmt.badge(f.status)}</td>
      <td style="color:#777">${f.reason ?? ''}</td>
    </tr>
  `).join('');
}

function closeDetail() {
  document.getElementById('detail-panel').classList.remove('open');
  document.getElementById('overlay').classList.remove('open');
}

async function refresh() {
  await Promise.all([loadStats(), loadRuns()]);
  document.getElementById('refresh-indicator').textContent =
    `Last updated: ${new Date().toLocaleTimeString()} · refreshes every 10 s`;
}

refresh();
setInterval(refresh, 10_000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return DASHBOARD_HTML
