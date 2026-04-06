#!/usr/bin/env python3
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

URL = "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats"

RS_ID = os.getenv("RS_ID", "127").strip()
RS_NAME = os.getenv("RS_NAME", "Anne-Lise").strip()
VESSEL_MMSI = os.getenv("VESSEL_MMSI", "").strip()
LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "120"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
STATUS_HISTORY_FILE = (
    os.getenv("STATUS_HISTORY_FILE", "/data/status_text_history.json").strip()
    or "/data/status_text_history.json"
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

_cache_lock = threading.Lock()
_cache_data = None
_cache_ts = 0.0
_last_error = None
_last_success_at = None

_history_lock = threading.Lock()
_status_history = None


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
    if re.search(r"\b(?:30|60)\s*min\s+beredskap\b", s):
        return raw.strip()
    if "beredskap" in s:
        return "Beredskap"
    return raw.strip()


def clean_string(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict) and not value:
        return None
    text = str(value).strip()
    return text or None


def parse_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _default_history() -> dict:
    return {
        "status_texts": [],
        "first_seen": {},
        "last_seen": {},
        "counts": {},
    }


def load_history() -> dict:
    global _status_history
    with _history_lock:
        if _status_history is not None:
            return _status_history

        try:
            with open(STATUS_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("history file is not a JSON object")
        except FileNotFoundError:
            data = _default_history()
        except Exception:
            data = _default_history()

        history = _default_history()
        history["status_texts"] = [str(x) for x in data.get("status_texts", []) if str(x).strip()]
        history["first_seen"] = {
            str(k): str(v) for k, v in (data.get("first_seen", {}) or {}).items() if str(k).strip()
        }
        history["last_seen"] = {
            str(k): str(v) for k, v in (data.get("last_seen", {}) or {}).items() if str(k).strip()
        }

        counts = {}
        for k, v in (data.get("counts", {}) or {}).items():
            key = str(k).strip()
            if not key:
                continue
            counts[key] = max(0, parse_int(v, 0))
        history["counts"] = counts

        deduped = []
        seen = set()
        for text in history["status_texts"]:
            if text not in seen:
                seen.add(text)
                deduped.append(text)
        history["status_texts"] = deduped

        _status_history = history
        return _status_history


def save_history(history: dict) -> None:
    ensure_parent_dir(STATUS_HISTORY_FILE)
    temp_path = f"{STATUS_HISTORY_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(temp_path, STATUS_HISTORY_FILE)


def update_status_history_from_boats(boats: list[dict]) -> None:
    timestamp = now_iso()
    history = load_history()

    with _history_lock:
        changed = False
        for boat in boats:
            text = clean_string((boat.get("extendedState") or {}).get("StatusText"))
            if not text:
                continue

            if text not in history["status_texts"]:
                history["status_texts"].append(text)
                history["first_seen"][text] = timestamp

            history["last_seen"][text] = timestamp
            history["counts"][text] = parse_int(history["counts"].get(text), 0) + 1
            changed = True

        if changed:
            save_history(history)


def get_status_history_payload(stale: bool = False) -> dict:
    history = load_history()
    with _history_lock:
        status_texts = list(history["status_texts"])
        first_seen = dict(history["first_seen"])
        last_seen = dict(history["last_seen"])
        counts = dict(history["counts"])

    items = [
        {
            "status_text": text,
            "first_seen": first_seen.get(text),
            "last_seen": last_seen.get(text),
            "seen_count": counts.get(text, 0),
        }
        for text in status_texts
    ]
    return {
        "ok": True,
        "count": len(items),
        "status_texts": status_texts,
        "items": items,
        "served_at": now_iso(),
        "stale": stale,
        "source": URL,
        "history_file": STATUS_HISTORY_FILE,
    }


def fetch_fleet() -> dict:
    resp = SESSION.get(URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected upstream response type")
    boats = data.get("rescueboats", [])
    if not isinstance(boats, list):
        raise RuntimeError("Unexpected upstream rescueboats payload")

    update_status_history_from_boats(boats)
    return data


def find_boat(data: dict, mmsi: str | None = None, rs: str | None = None, name: str | None = None) -> dict:
    boats = data.get("rescueboats", [])

    wanted_mmsi = clean_string(mmsi)
    wanted_rs = clean_string(rs)
    wanted_name = clean_string(name)

    if wanted_mmsi:
        for boat in boats:
            if clean_string(boat.get("mmsi")) == wanted_mmsi:
                return boat

    if wanted_rs:
        for boat in boats:
            if clean_string(boat.get("rs")) == wanted_rs:
                return boat

    if wanted_name:
        wanted_name_cf = wanted_name.casefold()
        for boat in boats:
            boat_name = clean_string(boat.get("name"))
            if boat_name and boat_name.casefold() == wanted_name_cf:
                return boat

    msg = "Could not find vessel in API response"
    details = []
    if wanted_mmsi:
        details.append(f"MMSI {wanted_mmsi}")
    if wanted_rs:
        details.append(f"RS {wanted_rs}")
    if wanted_name:
        details.append(f"name {wanted_name}")
    if details:
        msg = f"{msg}: {' / '.join(details)}"
    raise RuntimeError(msg)


def boat_payload(boat: dict, stale: bool = False) -> dict:
    extended_state = boat.get("extendedState") or {}
    station = boat.get("Station") or {}
    coords = boat.get("koordinater") or {}

    status_text = clean_string(extended_state.get("StatusText"))
    state_description = clean_string(boat.get("state_description"))
    raw_status = status_text or state_description or ""

    return {
        "ok": True,
        "rs": clean_string(boat.get("rs")),
        "name": clean_string(boat.get("name")),
        "mmsi": clean_string(boat.get("mmsi")),
        "raw_status": raw_status,
        "status": normalize_status(raw_status),
        "status_text": status_text,
        "state_description": state_description,
        "station": clean_string(station.get("name")),
        "timestamp": clean_string(coords.get("Timestamp")),
        "source": URL,
        "served_at": now_iso(),
        "stale": stale,
    }


def get_fleet_data() -> tuple[dict, bool]:
    global _cache_data, _cache_ts, _last_error, _last_success_at

    with _cache_lock:
        age = time.time() - _cache_ts
        if _cache_data is not None and age < CACHE_SECONDS:
            return _cache_data, False

    try:
        fresh = fetch_fleet()
        with _cache_lock:
            _cache_data = fresh
            _cache_ts = time.time()
            _last_error = None
            _last_success_at = now_iso()
        return fresh, False
    except Exception as exc:
        with _cache_lock:
            _last_error = str(exc)
            if _cache_data is not None:
                return _cache_data, True

        raise RuntimeError(str(exc)) from exc


def get_status(query: dict[str, list[str]]) -> tuple[dict, int]:
    wanted_mmsi = clean_string((query.get("mmsi") or [None])[0]) or VESSEL_MMSI or None
    wanted_rs = clean_string((query.get("rs") or [None])[0]) or RS_ID or None
    wanted_name = clean_string((query.get("name") or [None])[0]) or RS_NAME or None

    try:
        data, stale = get_fleet_data()
        boat = find_boat(data, mmsi=wanted_mmsi, rs=wanted_rs, name=wanted_name)
        payload = boat_payload(boat, stale=stale)
        return payload, 200
    except Exception as exc:
        stale_history = bool(_cache_data)
        return {
            "ok": False,
            "error": str(exc),
            "served_at": now_iso(),
            "stale": True,
            "selection": {
                "mmsi": wanted_mmsi,
                "rs": wanted_rs,
                "name": wanted_name,
            },
            "status_text_history": get_status_history_payload(stale=stale_history),
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
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/status":
            payload, status = get_status(query)
            self._send_json(payload, status)
            return

        if path == "/status-texts":
            try:
                _, stale = get_fleet_data()
            except Exception:
                stale = True
            self._send_json(get_status_history_payload(stale=stale), 200)
            return

        if path == "/healthz":
            with _cache_lock:
                cache_age_seconds = max(0, int(time.time() - _cache_ts)) if _cache_ts else None
                cache_populated = _cache_data is not None
                last_success_at = _last_success_at
                last_error = _last_error

            status_history_count = get_status_history_payload()["count"]
            payload = {
                "ok": True,
                "served_at": now_iso(),
                "cache_age_seconds": cache_age_seconds,
                "cache_populated": cache_populated,
                "last_success_at": last_success_at,
                "last_error": last_error,
                "default_selection": {
                    "mmsi": VESSEL_MMSI or None,
                    "rs": RS_ID or None,
                    "name": RS_NAME or None,
                },
                "status_text_history_count": status_history_count,
                "history_file": STATUS_HISTORY_FILE,
            }
            self._send_json(payload, 200)
            return

        self._send_json({"ok": False, "error": "Not found"}, 404)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    ensure_parent_dir(STATUS_HISTORY_FILE)
    load_history()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"Serving on http://{LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()
