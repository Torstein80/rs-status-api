#!/usr/bin/env python3
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

BOATS_URL = "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats"
AIS_URL = "https://ais.rs.no/aktive_pos.json"

DEFAULT_RS = os.getenv("RS_ID", "").strip()
DEFAULT_NAME = os.getenv("RS_NAME", "").strip()
DEFAULT_MMSI = os.getenv("MMSI", "").strip()

LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "120"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
USER_AGENT = os.getenv("USER_AGENT", "rs-status-api/2.2")

_cache_lock = threading.Lock()
_cache = {
    "boats": [],
    "ais": [],
    "ts": 0.0,
    "error": None,
}


class BadRequestError(RuntimeError):
    pass


class NotFoundError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_str(value) -> str:
    if value is None or value == {}:
        return ""
    return str(value).strip()


def first_text(*values) -> str:
    for value in values:
        text = clean_str(value)
        if text:
            return text
    return ""


def to_float(value):
    text = clean_str(value)
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def to_bool_flag(value: str) -> bool:
    return clean_str(value).casefold() in {"1", "true", "yes", "on"}


def normalize_status(raw: str) -> str:
    s = clean_str(raw).casefold()
    if "sar" in s:
        return "Kun SAR oppdrag"
    if "uad" in s:
        return "UAD"
    if "operativ" in s:
        return "Operativ"
    if re.search(r"\b(?:30|60)\s*min\s+beredskap\b", s) or "beredskap" in s:
        return "Beredskap"
    return clean_str(raw)


def fetch_json(url: str):
    resp = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json()


def refresh_feeds():
    boats_payload = fetch_json(BOATS_URL)
    boats = boats_payload.get("rescueboats", []) if isinstance(boats_payload, dict) else []
    if not isinstance(boats, list):
        boats = []

    ais_error = None
    try:
        ais_payload = fetch_json(AIS_URL)
        ais = ais_payload if isinstance(ais_payload, list) else []
    except Exception as exc:
        ais = []
        ais_error = f"AIS fetch failed: {exc}"

    with _cache_lock:
        _cache["boats"] = boats
        _cache["ais"] = ais
        _cache["ts"] = time.time()
        _cache["error"] = ais_error

    return boats, ais, False, ais_error


def get_feeds():
    with _cache_lock:
        age = time.time() - _cache["ts"]
        if _cache["boats"] and age < CACHE_SECONDS:
            return _cache["boats"], _cache["ais"], False, _cache["error"]

    try:
        return refresh_feeds()
    except Exception as exc:
        with _cache_lock:
            if _cache["boats"]:
                return _cache["boats"], _cache["ais"], True, str(exc)
        raise RuntimeError(f"Upstream fetch failed: {exc}") from exc


def ais_index_by_mmsi(ais_rows: list[dict]) -> dict[str, dict]:
    index = {}
    for row in ais_rows:
        mmsi = clean_str(row.get("MMSI"))
        if mmsi:
            index[mmsi] = row
    return index


def rs_sort_key(boat: dict):
    rs = clean_str(boat.get("rs"))
    try:
        return (0, int(rs))
    except ValueError:
        return (1, rs, clean_str(boat.get("name")))


def parse_selector(query: dict[str, list[str]]) -> dict:
    query_mmsi = clean_str(query.get("mmsi", [""])[0])
    query_rs = clean_str(query.get("rs", [""])[0])
    query_name = clean_str(query.get("name", [""])[0])

    if query_mmsi:
        return {
            "mmsi": query_mmsi,
            "rs": "",
            "name": "",
            "selected_by": "query",
            "matched_on": "mmsi",
        }
    if query_rs:
        return {
            "mmsi": "",
            "rs": query_rs,
            "name": "",
            "selected_by": "query",
            "matched_on": "rs",
        }
    if query_name:
        return {
            "mmsi": "",
            "rs": "",
            "name": query_name,
            "selected_by": "query",
            "matched_on": "name",
        }

    if DEFAULT_MMSI:
        return {
            "mmsi": DEFAULT_MMSI,
            "rs": "",
            "name": "",
            "selected_by": "env",
            "matched_on": "mmsi",
        }
    if DEFAULT_RS:
        return {
            "mmsi": "",
            "rs": DEFAULT_RS,
            "name": "",
            "selected_by": "env",
            "matched_on": "rs",
        }
    if DEFAULT_NAME:
        return {
            "mmsi": "",
            "rs": "",
            "name": DEFAULT_NAME,
            "selected_by": "env",
            "matched_on": "name",
        }

    raise BadRequestError(
        "No vessel selector configured. Set one of MMSI, RS_ID or RS_NAME in the container, "
        "or pass ?mmsi=, ?rs= or ?name= to /status."
    )


def find_boat(boats: list[dict], selector: dict) -> dict:
    target_mmsi = clean_str(selector.get("mmsi"))
    target_rs = clean_str(selector.get("rs"))
    target_name = clean_str(selector.get("name"))

    if target_mmsi:
        for boat in boats:
            if clean_str(boat.get("mmsi")) == target_mmsi:
                return boat
        raise NotFoundError(f"Could not find MMSI {target_mmsi} in API response")

    if target_rs:
        for boat in boats:
            if clean_str(boat.get("rs")) == target_rs:
                return boat
        raise NotFoundError(f"Could not find RS {target_rs} in API response")

    if target_name:
        needle = target_name.casefold()
        for boat in boats:
            if needle in clean_str(boat.get("name")).casefold():
                return boat
        raise NotFoundError(f'Could not find vessel name matching "{target_name}" in API response')

    raise BadRequestError(
        "No vessel selector configured. Set one of MMSI, RS_ID or RS_NAME, "
        "or pass ?mmsi=, ?rs= or ?name=."
    )


def build_status_payload(selector: dict) -> tuple[dict, int]:
    boats, ais_rows, stale, feed_error = get_feeds()
    boat = find_boat(boats, selector)
    ais_map = ais_index_by_mmsi(ais_rows)
    boat_mmsi = clean_str(boat.get("mmsi"))
    ais = ais_map.get(boat_mmsi, {})

    station = boat.get("Station", {}) or {}
    coords = boat.get("koordinater", {}) or {}
    ext = boat.get("extendedState", {}) or {}

    raw_status = first_text(
        ext.get("StatusText"),
        boat.get("state_description"),
        "",
    )

    decimal_latitude = first_text(
        ais.get("Decimal_Latitude"),
        coords.get("Decimal_Latitude"),
    )
    decimal_longitude = first_text(
        ais.get("Decimal_Longitude"),
        coords.get("Decimal_Longitude"),
    )

    position_source = "ais" if ais else "boats"

    payload = {
        "ok": True,
        "selector": {
            "mmsi": clean_str(selector.get("mmsi")) or None,
            "rs": clean_str(selector.get("rs")) or None,
            "name": clean_str(selector.get("name")) or None,
            "selected_by": selector.get("selected_by"),
            "matched_on": selector.get("matched_on"),
        },
        "rs": clean_str(boat.get("rs")),
        "name": clean_str(boat.get("name")),
        "mmsi": boat_mmsi or None,
        "callsign": clean_str(boat.get("callsign")) or None,
        "class": clean_str(boat.get("class-txt") or boat.get("class")) or None,
        "vessel_type": clean_str(boat.get("vessel-type-txt") or boat.get("vessel-type")) or None,
        "raw_status": raw_status,
        "status": normalize_status(raw_status),
        "status_id": ext.get("StatusId"),
        "status_color": clean_str(ext.get("ColorCode")) or None,
        "status_reason": first_text(ext.get("StatusAarsak"), boat.get("aarsak")) or None,
        "status_note": first_text(ext.get("StatusMerknad"), boat.get("merknad")) or None,
        "state": clean_str(boat.get("state")) or None,
        "state_description": clean_str(boat.get("state_description")) or None,
        "expected_back": first_text(boat.get("forventet_tilbake")) or None,
        "station": clean_str(station.get("name")) or None,
        "station_code": clean_str(station.get("code")) or None,
        "station_region": clean_str(station.get("region")) or None,
        "station_type": clean_str(station.get("type")) or None,
        "timestamp": first_text(ais.get("Time_stamp"), coords.get("Timestamp")) or None,
        "position_source": position_source,
        "latitude": first_text(ais.get("Latitude"), coords.get("Latitude")) or None,
        "longitude": first_text(ais.get("Longitude"), coords.get("Longitude")) or None,
        "decimal_latitude": to_float(decimal_latitude),
        "decimal_longitude": to_float(decimal_longitude),
        "image_url": clean_str(boat.get("imageUrl")) or None,
        "boats_source": BOATS_URL,
        "ais_source": AIS_URL,
        "served_at": now_iso(),
        "stale": stale,
        "upstream_error": feed_error,
        "ais": {
            "available_now": bool(ais),
            "ship_name": clean_str(ais.get("Ship_name")) or None,
            "destination": clean_str(ais.get("Destination")) or None,
            "time_stamp": clean_str(ais.get("Time_stamp")) or None,
            "sog_knots": to_float(ais.get("SOG")),
            "cog_degrees": to_float(ais.get("COG")),
            "latitude": clean_str(ais.get("Latitude")) or None,
            "longitude": clean_str(ais.get("Longitude")) or None,
            "decimal_latitude": to_float(ais.get("Decimal_Latitude")),
            "decimal_longitude": to_float(ais.get("Decimal_Longitude")),
        },
    }

    return payload, 200


def build_vessels_payload(query: dict[str, list[str]]) -> tuple[dict, int]:
    boats, ais_rows, stale, feed_error = get_feeds()
    ais_map = ais_index_by_mmsi(ais_rows)

    only_with_mmsi = to_bool_flag(query.get("only_with_mmsi", [""])[0])
    only_with_ais = to_bool_flag(query.get("only_with_ais", [""])[0])

    vessels = []
    for boat in sorted(boats, key=rs_sort_key):
        mmsi = clean_str(boat.get("mmsi"))
        ext = boat.get("extendedState", {}) or {}
        station = boat.get("Station", {}) or {}
        ais_present = mmsi in ais_map

        if only_with_mmsi and not mmsi:
            continue
        if only_with_ais and not ais_present:
            continue

        vessels.append(
            {
                "rs": clean_str(boat.get("rs")) or None,
                "name": clean_str(boat.get("name")) or None,
                "mmsi": mmsi or None,
                "callsign": clean_str(boat.get("callsign")) or None,
                "station": clean_str(station.get("name")) or None,
                "station_region": clean_str(station.get("region")) or None,
                "state": clean_str(boat.get("state")) or None,
                "state_description": clean_str(boat.get("state_description")) or None,
                "status_text": clean_str(ext.get("StatusText")) or None,
                "status_id": ext.get("StatusId"),
                "status_color": clean_str(ext.get("ColorCode")) or None,
                "ais_available_now": ais_present,
            }
        )

    payload = {
        "ok": True,
        "count": len(vessels),
        "served_at": now_iso(),
        "stale": stale,
        "upstream_error": feed_error,
        "selector_defaults": {
            "mmsi": DEFAULT_MMSI or None,
            "rs": DEFAULT_RS or None,
            "name": DEFAULT_NAME or None,
        },
        "sources": {
            "boats": BOATS_URL,
            "ais": AIS_URL,
        },
        "vessels": vessels,
    }
    return payload, 200


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

        try:
            if path == "/healthz":
                self._send_json(
                    {
                        "ok": True,
                        "served_at": now_iso(),
                        "selector_defaults": {
                            "mmsi": DEFAULT_MMSI or None,
                            "rs": DEFAULT_RS or None,
                            "name": DEFAULT_NAME or None,
                        },
                    },
                    200,
                )
                return

            if path == "/status":
                selector = parse_selector(query)
                payload, status = build_status_payload(selector)
                self._send_json(payload, status)
                return

            if path == "/vessels":
                payload, status = build_vessels_payload(query)
                self._send_json(payload, status)
                return

            self._send_json(
                {
                    "ok": False,
                    "error": "Not found",
                    "available_endpoints": [
                        "/healthz",
                        "/status",
                        "/status?mmsi=257227000",
                        "/status?rs=127",
                        "/status?name=Anne-Lise",
                        "/vessels",
                        "/vessels?only_with_mmsi=1",
                        "/vessels?only_with_ais=1",
                    ],
                },
                404,
            )
        except BadRequestError as exc:
            self._send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "served_at": now_iso(),
                },
                400,
            )
        except NotFoundError as exc:
            self._send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "served_at": now_iso(),
                },
                404,
            )
        except Exception as exc:
            self._send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "served_at": now_iso(),
                },
                503,
            )

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"Serving on http://{LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()
