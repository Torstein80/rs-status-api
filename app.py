#!/usr/bin/env python3
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import requests

URL = "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats"

RS_ID = os.getenv("RS_ID", "127")
RS_NAME = os.getenv("RS_NAME", "Anne-Lise")
LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "120"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

_cache_lock = threading.Lock()
_cache_data = None
_cache_ts = 0.0
_last_error = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(raw: str) -> str:
    s = raw.casefold()
    if "sar" in s:
        return "Kun SAR oppdrag"
    if "uad" in s:
        return "UAD"
    if "operativ" in s:
        return "Operativ"
    if re.search(r"\b(?:30|60)\s*min\s+beredskap\b", s) or "beredskap" in s:
        return "Beredskap"
    return raw.strip()


def find_boat(data: dict, rs: str, name: str) -> dict:
    boats = data.get("rescueboats", [])
    for boat in boats:
        boat_rs = str(boat.get("rs", "")).strip()
        boat_name = str(boat.get("name", ""))
        if boat_rs == rs:
            return boat
        if name.casefold() in boat_name.casefold():
            return boat
    raise RuntimeError(f"Could not find RS {rs} / {name} in API response")


def fetch_status() -> dict:
    resp = requests.get(URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    data = resp.json()

    boat = find_boat(data, RS_ID, RS_NAME)

    raw_status = (
        boat.get("extendedState", {}).get("StatusText")
        or boat.get("state_description")
        or ""
    )

    return {
        "ok": True,
        "rs": boat.get("rs"),
        "name": boat.get("name"),
        "raw_status": raw_status,
        "status": normalize_status(raw_status),
        "station": boat.get("Station", {}).get("name"),
        "timestamp": boat.get("koordinater", {}).get("Timestamp"),
        "source": URL,
        "served_at": now_iso(),
        "stale": False,
    }


def get_status() -> tuple[dict, int]:
    global _cache_data, _cache_ts, _last_error

    with _cache_lock:
        age = time.time() - _cache_ts
        if _cache_data is not None and age < CACHE_SECONDS:
            data = dict(_cache_data)
            data["served_at"] = now_iso()
            return data, 200

    try:
        fresh = fetch_status()
        with _cache_lock:
            _cache_data = fresh
            _cache_ts = time.time()
            _last_error = None
        return fresh, 200
    except Exception as exc:
        with _cache_lock:
            _last_error = str(exc)
            if _cache_data is not None:
                stale = dict(_cache_data)
                stale["stale"] = True
                stale["error"] = str(exc)
                stale["served_at"] = now_iso()
                return stale, 200

        return {
            "ok": False,
            "error": str(exc),
            "served_at": now_iso(),
            "stale": True,
        }, 503


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/status":
            payload, status = get_status()
            self._send_json(payload, status)
            return

        if path == "/healthz":
            self._send_json({"ok": True, "served_at": now_iso()}, 200)
            return

        self._send_json({"ok": False, "error": "Not found"}, 404)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"Serving on http://{LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()
