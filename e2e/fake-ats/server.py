"""Test-only fake ATS server (stdlib). NOT part of the product.

Emulates the three public read-only JSON endpoints RecruitRadar's adapters call, with synthetic data,
plus a control endpoint so end-to-end tests can mutate a board or force an error:

    GET  /v1/boards/{token}/jobs                      Greenhouse
    GET  /v0/postings/{site}?mode=json&skip=&limit=   Lever
    GET  /posting-api/job-board/{name}                Ashby
    POST /__control/{provider}/{token}                {"jobs": [...], "mode": "ok|404|401|429|500|malformed|slow"}
    GET  /__health

The control endpoints exist only here. Run: python e2e/fake-ats/server.py --port 8788
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

BOARDS: dict[tuple[str, str], dict[str, Any]] = {}
LOCK = threading.Lock()
REQUEST_LOG: list[dict[str, str]] = []


def _board(provider: str, token: str) -> dict[str, Any] | None:
    return BOARDS.get((provider, token))


def _json(handler: BaseHTTPRequestHandler, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
    raw = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(raw)


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeATS/1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet
        return

    # -- control ------------------------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        match = re.fullmatch(r"/__control/(greenhouse|lever|ashby)/([A-Za-z0-9_.-]+)", path)
        if not match:
            _json(self, 404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        with LOCK:
            board = BOARDS.setdefault((match[1], match[2]), {"jobs": [], "mode": "ok"})
            if "jobs" in payload:
                board["jobs"] = payload["jobs"]
            if "mode" in payload:
                board["mode"] = payload["mode"]
        _json(self, 200, {"ok": True, "jobs": len(board["jobs"]), "mode": board["mode"]})

    # -- public endpoints ---------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        with LOCK:
            REQUEST_LOG.append({"method": "GET", "path": self.path, "ua": self.headers.get("User-Agent", "")})
        if url.path == "/__health":
            _json(self, 200, {"ok": True})
            return
        if url.path == "/__requests":
            _json(self, 200, REQUEST_LOG)
            return

        provider = token = None
        for name, pattern in (
            ("greenhouse", r"/v1/boards/([A-Za-z0-9_.-]+)/jobs"),
            ("lever", r"/v0/postings/([A-Za-z0-9_.-]+)"),
            ("ashby", r"/posting-api/job-board/([A-Za-z0-9_.-]+)"),
        ):
            match = re.fullmatch(pattern, url.path)
            if match:
                provider, token = name, match[1]
                break
        if provider is None or token is None:
            _json(self, 404, {"error": "unknown route"})
            return

        with LOCK:
            board = _board(provider, token)
            snapshot = None if board is None else {"jobs": list(board["jobs"]), "mode": board["mode"]}
        if snapshot is None:
            _json(self, 404, {"error": "board not found"})
            return

        mode = snapshot["mode"]
        if mode == "404":
            _json(self, 404, {"error": "not found"})
            return
        if mode == "401":
            _json(self, 401, {"error": "unauthorized"})
            return
        if mode == "429":
            _json(self, 429, {"error": "slow down"}, {"Retry-After": "7"})
            return
        if mode == "500":
            _json(self, 500, {"error": "boom"})
            return
        if mode == "slow":
            time.sleep(20)
        if mode == "malformed":
            raw = b"<html>not json at all"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        jobs = snapshot["jobs"]
        if provider == "greenhouse":
            _json(self, 200, {"jobs": jobs, "meta": {"total": len(jobs)}})
        elif provider == "ashby":
            _json(self, 200, {"apiVersion": "1", "jobs": jobs})
        else:  # lever: bare array with skip/limit pagination
            skip = int(query.get("skip", ["0"])[0])
            limit = int(query.get("limit", ["100"])[0])
            _json(self, 200, jobs[skip : skip + limit])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fake ATS listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
