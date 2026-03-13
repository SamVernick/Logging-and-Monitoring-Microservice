# Logging & Monitoring Microservice

A minimal HTTP microservice for collecting, storing, and querying logs from
multiple services. Built with Python + Flask + SQLite — no external database
required.

---

## Requirements

- Python 3.9+
- pip

---

## Installation & Running

```bash
# 1. Copy the github repo
git clone https://github.com/SamVernick/Logging-and-Monitoring-Microservice.git

# 2. Install the single dependency
pip install -r requirements.txt

# 2. Start the server (runs on port 5050 by default)
python server.py
```

The server prints:

```
Logging microservice running on http://localhost:5050
```

`logs.db` is created automatically in the same directory on first run.

### Environment variables (all optional)

| Variable               | Default  | Description                                           |
|------------------------|----------|-------------------------------------------------------|
| `PORT`                 | `5050`   | Port the server listens on                            |
| `ALERT_THRESHOLD`      | `5`      | Number of ERROR/CRITICAL logs to trigger an alert     |
| `ALERT_WINDOW_SECONDS` | `60`     | Time window (seconds) used for alert counting         |


## API Reference

All endpoints accept and return `application/json`.

---

### POST `/logs` — Submit a log entry

Send a log from any service.

**Request body**

| Field     | Type   | Required | Description                                          |
|-----------|--------|----------|------------------------------------------------------|
| `source`  | string | Yes      | Name of the service sending the log                  |
| `message` | string | Yes      | Human-readable description of the event              |
| `level`   | string | No       | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` (default: `INFO`) |


**JavaScript (fetch)**

```js
await fetch("http://localhost:5050/logs", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ source: "job-queue", level: "INFO", message: "One-Time Job Added To Queue" })
});
```

**Python (requests)**

```python
import requests
requests.post("http://localhost:5050/logs", json={
    "source": "job-queue", "level": "CRITICAL", "message": "Job Execution Failed"
})
```

**Success response — 201 Created**

```json
{
  "id": 42,
  "timestamp": "2026-03-12T10:30:00Z",
  "source": "job-queue",
  "level": "ERROR",
  "message": "Timer Recursion Failed"
}
```

**Error responses**

| Status | Reason                          |
|--------|---------------------------------|
| `400`  | Missing `source` or `message`, or invalid `level` |

---

### GET `/logs` — Query stored logs

Retrieve log entries with optional filters. Results are ordered newest-first.

**Query parameters (all optional)**

| Parameter | Type    | Description                                              |
|-----------|---------|----------------------------------------------------------|
| `source`  | string  | Exact match on source service name                       |
| `level`   | string  | Exact match on level (`INFO`, `ERROR`, …)                |
| `search`  | string  | Case-insensitive substring match on `message`            |
| `since`   | string  | ISO-8601 datetime; return only logs at or after this time |
| `limit`   | integer | Max results to return (default `200`, max `1000`)        |

ISO-8601 datetime is used as:
1. It is language agnostic and standardized on multiple systems
2. It includes timezone info
3. It is readable in API responses and logs
4. It is lexigraphically sortable (used for searches)


**JavaScript (fetch)**

```js
const res  = await fetch("http://localhost:5050/logs?level=ERROR&limit=50");
const logs = await res.json();
```

**Success response — 200 OK**

```json
[
  {
    "id": 42,
    "timestamp": "2026-03-12T10:30:00Z",
    "source": "job-queue",
    "level": "ERROR",
    "message": "Failed to List Jobs"
  }
]
```

---

### GET `/health` — System health & alerts

Returns current system health. Counts `ERROR` and `CRITICAL` logs in the
configured time window. If that count reaches `ALERT_THRESHOLD`, the status
flips to `CRITICAL` and `alert` contains a human-readable message.


**JavaScript (fetch)**

```js
const res    = await fetch("http://localhost:5050/health");
const health = await res.json();
if (health.status === "CRITICAL") {
  console.error("ALERT:", health.alert.message);
}
```

**Response — 200 OK (healthy)**

```json
{
  "status":      "OK",
  "error_count": 2,
  "threshold":   5,
  "window_sec":  60,
  "alert":       false
}
```

**Response — 200 OK (alert active)**

```json
{
  "status":      "CRITICAL",
  "error_count": 7,
  "threshold":   5,
  "window_sec":  60,
  "alert": {
    "message": "7 error(s) in the last 60s — threshold is 5"
  }
}
```

---

## Running the tests

The test script requires the server to be running. Open two terminals:

**Terminal 1 — start the server**

```bash
source venv/bin/activate
python server.py
```

**Terminal 2 — run tests**

```bash
source venv/bin/activate
pip install requests        # one-time if not already installed
python test_service.py
```

Expected output:

```
Running tests against http://localhost:5050

  PASS  POST /logs — minimal fields (source + message)
  PASS  POST /logs — explicit ERROR level
  PASS  POST /logs — invalid level returns 400
  PASS  POST /logs — missing 'source' returns 400
  PASS  POST /logs — missing 'message' returns 400
  PASS  POST /logs — no JSON body returns 400
  PASS  GET  /logs — returns a list
  PASS  GET  /logs?source= — filters by source
  PASS  GET  /logs?level=CRITICAL — filters by level
  PASS  GET  /logs?search= — case-insensitive message search
  PASS  GET  /logs?since=future — returns empty list
  PASS  GET  /logs?limit=1 — respects limit
  PASS  GET  /logs?level=NOPE — invalid level returns 400
  PASS  GET  /health — returns all required fields
  PASS  GET  /health — flips CRITICAL after error threshold
  PASS  GET  /logs — all entries have required fields
  PASS  GET  /logs - all entries have teh required fields

  Sample logs (up to 3):
[
  {
    "id": 50,
    "level": "ERROR",
    "message": "critical failure #4",
    "source": "alert-test-svc",
    "timestamp": "2026-03-13T07:30:41Z"
  },
  {
    "id": 49,
    "level": "ERROR",
    "message": "critical failure #3",
    "source": "alert-test-svc",
    "timestamp": "2026-03-13T07:30:41Z"
  },
  {
    "id": 48,
    "level": "ERROR",
    "message": "critical failure #2",
    "source": "alert-test-svc",
    "timestamp": "2026-03-13T07:30:41Z"
  }
]
  PASS  GET  /logs — print sample log entries

==================================================
  17/17 tests passed
==================================================
```


---

## Integration checklist for other services

1. Start the microservice: `python server.py`
2. Send logs via `POST http://localhost:5050/logs`
3. Check system health via `GET http://localhost:5050/health`
4. If deploying on a different host, replace `localhost:5050` with the actual
   host/port (recommend importing from .env file). Change the port via the 
   `PORT` environment variable.
