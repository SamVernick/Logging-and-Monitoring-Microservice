"""
Logging & Monitoring Microservice
----------------------------------
A minimal Flask + SQLite service that:
  - Accepts log entries from any HTTP-capable service
  - Stores them with timestamp, source, level, and message
  - Supports filtering/searching logs
  - Exposes a /health endpoint that alerts on error thresholds

Run:  python server.py
Port: 5050 (configurable via PORT env var)
"""

import os
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify, g

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "logs.db")
PORT    = int(os.environ.get("PORT", 5050))

# Alert threshold: if this many ERROR/CRITICAL logs arrive within
# ALERT_WINDOW_SECONDS the /health endpoint returns status CRITICAL.
ALERT_THRESHOLD       = int(os.environ.get("ALERT_THRESHOLD", 5))
ALERT_WINDOW_SECONDS  = int(os.environ.get("ALERT_WINDOW_SECONDS", 60))

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Return a per-request SQLite connection stored on Flask's g object."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the logs table if it does not already exist."""
    with app.app_context():
        db = get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                source    TEXT    NOT NULL,
                level     TEXT    NOT NULL,
                message   TEXT    NOT NULL
            )
        """)
        db.commit()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/logs", methods=["POST"])
def ingest_log():
    """
    Accept a log entry from any service.

    Expected JSON body:
        {
            "source":  "service-name",   (required)
            "message": "what happened",  (required)
            "level":   "INFO"            (optional, default INFO)
        }

    Returns the stored log entry with its assigned id and timestamp.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    source  = data.get("source", "").strip()
    message = data.get("message", "").strip()
    level   = data.get("level", "INFO").upper().strip()

    if not source:
        return jsonify({"error": "'source' is required"}), 400
    if not message:
        return jsonify({"error": "'message' is required"}), 400
    if level not in VALID_LEVELS:
        return jsonify({"error": f"'level' must be one of {sorted(VALID_LEVELS)}"}), 400

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    db = get_db()
    cur = db.execute(
        "INSERT INTO logs (timestamp, source, level, message) VALUES (?, ?, ?, ?)",
        (timestamp, source, level, message),
    )
    db.commit()

    return jsonify({
        "id":        cur.lastrowid,
        "timestamp": timestamp,
        "source":    source,
        "level":     level,
        "message":   message,
    }), 201


@app.route("/logs", methods=["GET"])
def query_logs():
    """
    Return stored log entries with optional filters.

    Query parameters (all optional):
        source  – exact match on source service name
        level   – exact match on level (INFO, ERROR, …)
        search  – substring match on message (case-insensitive)
        since   – ISO-8601 datetime; return only logs at or after this time
        limit   – max number of results (default 200, max 1000)

    Results are ordered newest-first.
    """
    source  = request.args.get("source", "").strip()
    level   = request.args.get("level",  "").strip().upper()
    search  = request.args.get("search", "").strip()
    since   = request.args.get("since",  "").strip()
    try:
        limit = min(int(request.args.get("limit", 200)), 1000)
    except ValueError:
        return jsonify({"error": "'limit' must be an integer"}), 400

    sql    = "SELECT * FROM logs WHERE 1=1"
    params = []

    if source:
        sql += " AND source = ?"
        params.append(source)
    if level:
        if level not in VALID_LEVELS:
            return jsonify({"error": f"'level' must be one of {sorted(VALID_LEVELS)}"}), 400
        sql += " AND level = ?"
        params.append(level)
    if search:
        sql += " AND message LIKE ?"
        params.append(f"%{search}%")
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)

    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = get_db().execute(sql, params).fetchall()
    return jsonify([dict(row) for row in rows]), 200


@app.route("/health", methods=["GET"])
def health():
    """
    Return system health status.

    Counts ERROR + CRITICAL logs in the last ALERT_WINDOW_SECONDS seconds.
    If the count >= ALERT_THRESHOLD the status is CRITICAL, otherwise OK.

    Response:
        {
            "status":       "OK" | "CRITICAL",
            "error_count":  <int>,
            "threshold":    <int>,
            "window_sec":   <int>,
            "alert":        false | { "message": "..." }
        }
    """
    window_start = datetime.now(timezone.utc)
    # Build an ISO-8601 string ALERT_WINDOW_SECONDS in the past
    from datetime import timedelta
    cutoff = (window_start - timedelta(seconds=ALERT_WINDOW_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    row = get_db().execute(
        "SELECT COUNT(*) as cnt FROM logs WHERE level IN ('ERROR','CRITICAL') AND timestamp >= ?",
        (cutoff,),
    ).fetchone()
    error_count = row["cnt"]

    if error_count >= ALERT_THRESHOLD:
        status = "CRITICAL"
        alert  = {"message": f"{error_count} error(s) in the last {ALERT_WINDOW_SECONDS}s — threshold is {ALERT_THRESHOLD}"}
    else:
        status = "OK"
        alert  = False

    return jsonify({
        "status":      status,
        "error_count": error_count,
        "threshold":   ALERT_THRESHOLD,
        "window_sec":  ALERT_WINDOW_SECONDS,
        "alert":       alert,
    }), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print(f"Logging microservice running on http://localhost:{PORT}")
    app.run(port=PORT, debug=False)
