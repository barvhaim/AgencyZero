#!/usr/bin/env python3
"""
Export one Langfuse session to a single JSON file: every trace in it (in
order), every observation inside each trace (LLM calls, tool calls, spans)
with input/output, usage, model, metadata, tags and release.

Written for self-hosted Langfuse v4, which only serves the Observations API v2
(GET /api/public/v2/observations); the old /sessions and /traces endpoints
return 404 there.

Usage:
    python export_session.py [SESSION_ID]     # no ID = the most recent session

Environment:
    LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY   project API keys (from .env)
    LANGFUSE_HOST   default http://langfuse-web:3000 (inside the compose network)
    OUT_DIR         default /out
    DAYS            how far back to search, default 30

Run it from the project root (PowerShell) with a throwaway Python container on
the lab network, so nothing has to be installed on Windows:

    docker run --rm --network agencyzero_lab --env-file .env `
      -v "${PWD}\\scripts:/scripts:ro" -v "${PWD}\\data\\exports:/out" `
      python:3.12-slim python /scripts/export_session.py [SESSION_ID]

The file lands in data\\exports\\ (gitignored with the rest of data/).
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HOST = os.environ.get("LANGFUSE_HOST", "http://langfuse-web:3000").rstrip("/")
OUT_DIR = os.environ.get("OUT_DIR", "/out")
DAYS = int(os.environ.get("DAYS", "30"))
FIELDS = "core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context"

try:
    _PK = os.environ["LANGFUSE_PUBLIC_KEY"]
    _SK = os.environ["LANGFUSE_SECRET_KEY"]
except KeyError as missing:
    sys.exit(f"Missing environment variable {missing}. Pass --env-file .env")

_AUTH = "Basic " + base64.b64encode(f"{_PK}:{_SK}".encode()).decode()

NOW = datetime.now(timezone.utc)
WINDOW = {
    "fromStartTime": (NOW - timedelta(days=DAYS)).isoformat().replace("+00:00", "Z"),
    "toStartTime": (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
}


def get(path: str, params: dict) -> dict:
    """GET a Langfuse public API path and return the parsed JSON."""
    url = HOST + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": _AUTH})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")[:600]
        sys.exit(f"Langfuse API error {err.code} on {path}: {body}")
    except urllib.error.URLError as err:
        sys.exit(f"Cannot reach Langfuse at {HOST}: {err.reason}")


def observations(**filters) -> list[dict]:
    """All observation rows matching the filters, following cursors."""
    rows, cursor = [], None
    while True:
        params = {**WINDOW, **filters, "fields": FIELDS, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = get("/api/public/v2/observations", params)
        rows.extend(page.get("data") or [])
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor:
            return rows


def latest_session_id() -> str:
    page = get("/api/public/v2/observations",
               {**WINDOW, "fields": "core,basic", "limit": 200})
    for row in page.get("data") or []:  # newest first
        if row.get("sessionId"):
            return row["sessionId"]
    sys.exit(f"No observations with a session in the last {DAYS} days.")


def parse_io(value):
    """v2 returns input/output as raw strings; decode JSON when possible."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else latest_session_id()
    print(f"Exporting session {session_id} (last {DAYS} days) ...")

    rows = observations(sessionId=session_id)
    if not rows:
        sys.exit("No observations found for that session in the time window.")

    by_trace = defaultdict(list)
    for row in rows:
        for key in ("input", "output"):
            if key in row:
                row[key] = parse_io(row[key])
        by_trace[row["traceId"]].append(row)

    traces = []
    for trace_id, obs in by_trace.items():
        obs.sort(key=lambda o: o.get("startTime") or "")
        root = next((o for o in obs if not o.get("parentObservationId")), obs[0])
        traces.append({
            "traceId": trace_id,
            "name": root.get("traceName") or root.get("name"),
            "startTime": root.get("startTime"),
            "tags": root.get("tags"),
            "release": root.get("release"),
            "environment": root.get("environment"),
            "input": root.get("input"),
            "output": root.get("output"),
            "observation_count": len(obs),
            "observations": obs,
        })
    traces.sort(key=lambda t: t.get("startTime") or "")
    for i, t in enumerate(traces, 1):
        print(f"  trace {i}/{len(traces)}: {t['observation_count']} observation(s)")

    export = {
        "exported_at": NOW.isoformat(),
        "langfuse_host": HOST,
        "session_id": session_id,
        "trace_count": len(traces),
        "observation_count": len(rows),
        "traces": traces,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:80]
    stamp = NOW.strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(OUT_DIR, f"session-{safe_id}-{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(export, fh, ensure_ascii=False, indent=2)
    print(f"Done: {len(traces)} trace(s), {len(rows)} observation(s) -> {os.path.basename(path)}")


if __name__ == "__main__":
    main()
