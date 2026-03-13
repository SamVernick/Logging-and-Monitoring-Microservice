"""
test_service.py — Integration tests for the Logging & Monitoring Microservice
------------------------------------------------------------------------------
Prerequisites:
    pip install requests
    python server.py   (running in a separate terminal)

Run:
    python test_service.py

Each test prints PASS or FAIL with a short description.
The final line prints a summary: X/Y tests passed.
"""

import sys
import time
import json
import requests

BASE = "http://localhost:5050"


# ---------------------------------------------------------------------------
# Tiny test harness
# ---------------------------------------------------------------------------

_results = []


def run(description, fn):
    """Run fn(), record PASS/FAIL, print result."""
    try:
        fn()
        print(f"  PASS  {description}")
        _results.append(True)
    except AssertionError as exc:
        msg = str(exc) if str(exc) else "(assertion failed)"
        print(f"  FAIL  {description} — {msg}")
        _results.append(False)
    except Exception as exc:
        print(f"  FAIL  {description} — unexpected error: {exc}")
        _results.append(False)


def summary():
    passed = sum(_results)
    total  = len(_results)
    print(f"\n{'='*50}")
    print(f"  {passed}/{total} tests passed")
    print(f"{'='*50}")
    sys.exit(0 if passed == total else 1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_post_log_minimal():
    """POST /logs with only required fields that echoes the entry, expect 201"""
    r = requests.post(f"{BASE}/logs", json={
            "source": "test-svc",
            "message": "hello",
        },
    )
    assert r.status_code == 201, f"expected 201, got {r.status_code}"
    body = r.json()
    assert body["source"]  == "test-svc"
    assert body["message"] == "hello"
    assert body["level"]   == "INFO"          # default level
    assert "timestamp" in body
    assert "id" in body



def test_post_log_with_level():
    """POST /logs with explicit level stores that level correctly, expect 201"""
    r = requests.post(f"{BASE}/logs", json={
        "source":  "auth-svc",
        "message": "login failed",
        "level":   "ERROR",
    })
    assert r.status_code == 201, f"expected 201, got {r.status_code}"
    assert r.json()["level"] == "ERROR"


def test_post_log_invalid_level():
    """POST /logs with an invalid level, expect 400"""
    r = requests.post(f"{BASE}/logs", json={
        "source":  "svc",
        "message": "msg",
        "level":   "VERBOSE",     # not a valid level
    })
    assert r.status_code == 400, f"expected 400, got {r.status_code}"
    assert "error" in r.json()


def test_post_log_missing_source():
    """POST /logs without 'source', expect 400"""
    r = requests.post(f"{BASE}/logs", json={
            "message": "orphan log",
        },
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}"


def test_post_log_missing_message():
    """POST /logs without 'message', expect 400"""
    r = requests.post(
        f"{BASE}/logs",
        json={
            "source": "svc",
        },
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}"


def test_post_log_no_body():
    """POST /logs with no JSON body returns 400."""
    r = requests.post(
        f"{BASE}/logs",
        data="not json",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}"


def test_get_logs_returns_list():
    """GET /logs returns a JSON array, expect 200"""
    r = requests.get(f"{BASE}/logs")
    assert r.status_code == 200, f"expected 200, got {r.status_code}"
    assert isinstance(r.json(), list)


def test_get_logs_filter_source():
    """GET /logs?source= filters by source correctly, expect 200"""
    unique_source = "unique-filter-svc-xyz"
    requests.post(
        f"{BASE}/logs",
        json={
            "source": unique_source,
            "message": "filter me",
        },
    )
    r = requests.get(f"{BASE}/logs", params={"source": unique_source})
    assert r.status_code == 200
    logs = r.json()
    assert len(logs) >= 1, "expected at least one log for unique source"
    assert all(entry["source"] == unique_source for entry in logs)


def test_get_logs_filter_level():
    """GET /logs?level=CRITICAL returns only CRITICAL entries, expect 200"""
    requests.post(
        f"{BASE}/logs",
        json={
            "source": "svc",
            "message": "crit!",
            "level": "CRITICAL",
        },
    )
    r = requests.get(f"{BASE}/logs", params={"level": "CRITICAL"})
    assert r.status_code == 200
    logs = r.json()
    assert len(logs) >= 1
    assert all(entry["level"] == "CRITICAL" for entry in logs)


def test_get_logs_filter_search():
    """GET /logs?search= does a case-insensitive substring match on message, expect 200"""
    requests.post(
        f"{BASE}/logs",
        json={
            "source": "svc",
            "message": "UniqueSearchString99",
        },
    )
    r = requests.get(f"{BASE}/logs", params={"search": "uniquesearchstring99"})
    assert r.status_code == 200
    logs = r.json()
    assert len(logs) >= 1
    assert all("uniquesearchstring99" in entry["message"].lower() for entry in logs)


def test_get_logs_filter_since():
    """GET /logs?since= filters out old entries, expect 200"""
    future = "2099-01-01T00:00:00Z"
    r = requests.get(f"{BASE}/logs", params={"since": future})
    assert r.status_code == 200
    assert r.json() == [], f"expected empty list for far-future 'since', got {r.json()}"


def test_get_logs_limit():
    """GET /logs?limit=1 returns at most 1 entry, exepct 200"""
    r = requests.get(f"{BASE}/logs", params={"limit": 1})
    assert r.status_code == 200
    assert len(r.json()) <= 1


def test_get_logs_invalid_level_filter():
    """GET /logs?level=NOPE, expect 400"""
    r = requests.get(f"{BASE}/logs", params={"level": "NOPE"})
    assert r.status_code == 400


def test_health_ok():
    """GET /health returns 'status' field, expect 200"""
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200, f"expected 200, got {r.status_code}"
    body = r.json()
    assert "status"      in body
    assert "error_count" in body
    assert "threshold"   in body
    assert "window_sec"  in body
    assert "alert"       in body
    assert body["status"] in ("OK", "CRITICAL")


def test_health_alert_triggered():
    """
    Sending >= ALERT_THRESHOLD ERROR logs flips /health to CRITICAL.

    This test reads the current threshold from /health, sends that many
    ERROR logs, then verifies the status flips.  It works regardless of
    what ALERT_THRESHOLD is set to on the server.
    """
    info = requests.get(f"{BASE}/health").json()
    threshold = info["threshold"]

    for i in range(threshold):
        requests.post(f"{BASE}/logs", json={
            "source":  "alert-test-svc",
            "message": f"critical failure #{i}",
            "level":   "ERROR",
        })

    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "CRITICAL", (
        f"expected CRITICAL after {threshold} errors, got {body['status']}"
    )
    assert body["alert"] is not False, "expected alert object, got False"


def test_log_contains_all_fields():
    """Every log returned by GET /logs has id, timestamp, source, level, message."""
    r = requests.get(f"{BASE}/logs", params={"limit": 5})
    assert r.status_code == 200
    for entry in r.json():
        for field in ("id", "timestamp", "source", "level", "message"):
            assert field in entry, f"missing field '{field}' in entry {entry}"


def test_print_sample_logs():
    """Print up to 3 log entries so you can see actual list output."""
    r = requests.get(f"{BASE}/logs", params={"limit": 3})
    assert r.status_code == 200, f"expected 200, got {r.status_code}"
    logs = r.json()
    assert isinstance(logs, list), "expected /logs response to be a list"

    print("\n  Sample logs (up to 3):")
    if not logs:
        print("  []")
    else:
        print(json.dumps(logs, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick connectivity check
    try:
        requests.get(f"{BASE}/health", timeout=3)
    except requests.ConnectionError:
        print(f"\nCould not connect to {BASE}")
        print("Make sure the server is running:  python server.py\n")
        sys.exit(1)

    print(f"\nRunning tests against {BASE}\n")

    run("POST /logs — minimal fields (source + message)",       test_post_log_minimal)
    run("POST /logs — explicit ERROR level",                    test_post_log_with_level)
    run("POST /logs — invalid level returns 400",               test_post_log_invalid_level)
    run("POST /logs — missing 'source' returns 400",            test_post_log_missing_source)
    run("POST /logs — missing 'message' returns 400",           test_post_log_missing_message)
    run("POST /logs — no JSON body returns 400",                test_post_log_no_body)
    run("GET  /logs — returns a list",                          test_get_logs_returns_list)
    run("GET  /logs?source= — filters by source",               test_get_logs_filter_source)
    run("GET  /logs?level=CRITICAL — filters by level",         test_get_logs_filter_level)
    run("GET  /logs?search= — case-insensitive message search", test_get_logs_filter_search)
    run("GET  /logs?since=future — returns empty list",         test_get_logs_filter_since)
    run("GET  /logs?limit=1 — respects limit",                  test_get_logs_limit)
    run("GET  /logs?level=NOPE — invalid level returns 400",    test_get_logs_invalid_level_filter)
    run("GET  /health — returns all required fields",           test_health_ok)
    run("GET  /health — flips CRITICAL after error threshold",  test_health_alert_triggered)
    run("GET  /logs — all entries have required fields",        test_log_contains_all_fields)
    run("GET  /logs — print sample log entries",                test_print_sample_logs)

    summary()
