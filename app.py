#!/usr/bin/env python3
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

URL = "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats"

DEFAULT_VESSEL_MMSI = str(os.getenv("VESSEL_MMSI") or os.getenv("MMSI") or "").strip() or None
DEFAULT_RS_ID = str(os.getenv("RS_ID") or "").strip() or None
DEFAULT_RS_NAME = str(os.getenv("RS_NAME") or "").strip() or None
LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "120"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "20"))

_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()
_cache_data: dict[str, Any] | None = None
_cache_ts = 0.0
_last_error: str | None = None
_last_success_ts = 0.0

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": "rs-boat-status-exporter/2.1",
        "Accept": "application/json",
    }
)

STATUS_GROUP_RULES = [
    (r"\bsar\b", "sar_only"),
    (r"\buad\b", "uad"),
    (r"\bpå\s+oppdrag\b|\boppdrag\b", "mission"),
    (r"\b30\s*min\b", "standby_30"),
    (r"\b60\s*min\b", "standby_60"),
    (r"\bberedskap\b", "standby"),
    (r"\bledig\b|\boperativ\b", "available"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        return None if not value else value
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def as_string(value: Any) -> str | None:
    value = clean_scalar(value)
    if value is None:
        return None
    return str(value)


def as_float(value: Any) -> float | None:
    value = clean_scalar(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def classify_status(state_description: str | None, status_text: str | None) -> str:
    text = " ".join(part for part in (state_description, status_text) if part).casefold()
    for pattern, label in STATUS_GROUP_RULES:
        if re.search(pattern, text):
            return label
    return "unknown"


def normalize_boat(boat: dict[str, Any]) -> dict[str, Any]:
    station = boat.get("Station") or {}
    extended_state = boat.get("extendedState") or {}
    coords = boat.get("koordinater") or {}

    state_description = as_string(boat.get("state_description"))
    status_text = as_string(extended_state.get("StatusText"))

    return {
        "vessel": {
            "rs": as_string(boat.get("rs")),
            "name": as_string(boat.get("name")),
            "other_name": as_string(boat.get("other_name")),
            "callsign": as_string(boat.get("callsign")),
            "mmsi": as_string(boat.get("mmsi")),
            "home_port": as_string(boat.get("port")),
            "class_code": as_string(boat.get("class")),
            "class_name": as_string(boat.get("class-txt")),
            "vessel_type_code": as_string(boat.get("vessel-type")),
            "vessel_type_name": as_string(boat.get("vessel-type-txt")),
            "image_url": as_string(boat.get("imageUrl")),
        },
        "status": {
            "state_code": as_string(boat.get("state")),
            "state_description": state_description,
            "status_id": clean_scalar(extended_state.get("StatusId")),
            "status_text": status_text,
            "status_group": classify_status(state_description, status_text),
            "status_reason": as_string(extended_state.get("StatusAarsak")) or as_string(boat.get("aarsak")),
            "status_note": as_string(extended_state.get("StatusMerknad")) or as_string(boat.get("merknad")),
            "expected_return": as_string(boat.get("forventet_tilbake")),
            "color_code": as_string(extended_state.get("ColorCode")),
            "underliggende_status": clean_scalar(extended_state.get("UnderliggendeStatus")),
            "location_text": as_string(boat.get("Lokasjon")),
        },
        "position": {
            "timestamp": as_string(coords.get("Timestamp")),
            "latitude_text": as_string(coords.get("Latitude")),
            "longitude_text": as_string(coords.get("Longitude")),
            "latitude": as_float(coords.get("Decimal_Latitude")),
            "longitude": as_float(coords.get("Decimal_Longitude")),
        },
        "station": {
            "code": as_string(station.get("code")),
            "name": as_string(station.get("name")),
            "type": as_string(station.get("type")),
            "region": as_string(station.get("region")),
            "phone": as_string(station.get("phone")),
            "address": as_string(station.get("address")),
            "zipcode": as_string(station.get("zipcode")),
            "ziplocation": as_string(station.get("ziplocation")),
            "latitude": as_float(station.get("latitude")),
            "longitude": as_float(station.get("longitude")),
        },
        "contact": {
            "contact_number": as_string(boat.get("contactNumber")),
            "mobile": as_string(boat.get("mobile")),
            "email": as_string(boat.get("email")),
        },
        "profile": {
            "buildingyard_year": as_string(boat.get("buildingyard_year")),
            "construction": as_string(boat.get("construction")),
            "finance": as_string(boat.get("finance")),
            "construction_material": as_string(boat.get("construction_material")),
            "dnv_class": as_string(boat.get("dnv_class")),
            "speed": as_string(boat.get("speed")),
            "range": as_string(boat.get("range")),
            "gross": as_string(boat.get("gross")),
            "net": as_string(boat.get("net")),
            "length": as_string(boat.get("length")),
            "beam": as_string(boat.get("beam")),
            "draft": as_string(boat.get("draft")),
            "bunker_oil": as_string(boat.get("bunker_oil")),
            "ballast_water": as_string(boat.get("ballast_water")),
            "fresh_water": as_string(boat.get("fresh_water")),
            "bollard_pull_maximum": as_string(boat.get("bollard_pull_maximum")),
            "main_engine": as_string(boat.get("main_engine")),
            "aux_engine": as_string(boat.get("aux_engine")),
            "gear": as_string(boat.get("gear")),
            "controllable_pitch_propellers": as_string(boat.get("controllable_pitch_propellers")),
            "bowthruster": as_string(boat.get("bowthruster")),
            "waterjet": as_string(boat.get("waterjet")),
            "deck_machinery": as_string(boat.get("deck_machinery")),
            "salvage_equipment": as_string(boat.get("salvage_equipment")),
            "diving_equipment": as_string(boat.get("diving_equipment")),
            "navigation_equipment": as_string(boat.get("navigation_equipment")),
            "communication_equipment": as_string(boat.get("communication_equipment")),
            "rescue_accommodation": as_string(boat.get("rescue_accommodation")),
            "crew": as_string(boat.get("crew")),
        },
    }


def fetch_fleet() -> dict[str, Any]:
    response = _session.get(URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    boats = data.get("rescueboats")
    if not isinstance(boats, list):
        raise RuntimeError("Upstream payload did not contain a rescueboats list")

    normalized_boats = [normalize_boat(boat) for boat in boats]
    return {
        "boats": normalized_boats,
        "boat_count": len(normalized_boats),
        "source": URL,
        "fetched_at": now_iso(),
    }


def get_fleet() -> tuple[dict[str, Any] | None, bool, int, str | None]:
    global _cache_data, _cache_ts, _last_error, _last_success_ts

    with _cache_lock:
        age = time.time() - _cache_ts
        if _cache_data is not None and age < CACHE_SECONDS:
            return _cache_data, False, 200, None

    with _refresh_lock:
        with _cache_lock:
            age = time.time() - _cache_ts
            if _cache_data is not None and age < CACHE_SECONDS:
                return _cache_data, False, 200, None

        try:
            fresh = fetch_fleet()
            with _cache_lock:
                _cache_data = fresh
                _cache_ts = time.time()
                _last_success_ts = _cache_ts
                _last_error = None
            return fresh, False, 200, None
        except Exception as exc:
            error_message = str(exc)
            with _cache_lock:
                _last_error = error_message
                if _cache_data is not None:
                    return _cache_data, True, 200, error_message
            return None, True, 503, error_message


def pick_first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def resolve_selector(params: dict[str, list[str]]) -> dict[str, str | None]:
    return {
        "mmsi": pick_first(params, "mmsi") or DEFAULT_VESSEL_MMSI,
        "rs": pick_first(params, "rs") or DEFAULT_RS_ID,
        "name": pick_first(params, "name") or DEFAULT_RS_NAME,
    }


def find_boat(
    boats: list[dict[str, Any]],
    mmsi: str | None = None,
    rs: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    if mmsi:
        for boat in boats:
            if boat["vessel"]["mmsi"] == mmsi:
                return boat

    if rs:
        for boat in boats:
            if boat["vessel"]["rs"] == rs:
                return boat

    if name:
        wanted = name.casefold()
        for boat in boats:
            current = boat["vessel"]["name"]
            if current and current.casefold() == wanted:
                return boat

    raise LookupError(
        "Could not find vessel for the provided selector. "
        "Use mmsi, rs, or exact name."
    )


def build_summary(boat: dict[str, Any]) -> dict[str, Any]:
    return {
        "rs": boat["vessel"]["rs"],
        "name": boat["vessel"]["name"],
        "mmsi": boat["vessel"]["mmsi"],
        "callsign": boat["vessel"]["callsign"],
        "station": boat["station"]["name"],
        "timestamp": boat["position"]["timestamp"],
        "state_description": boat["status"]["state_description"],
        "status_text": boat["status"]["status_text"],
        "status_group": boat["status"]["status_group"],
        "expected_return": boat["status"]["expected_return"],
        "location_text": boat["status"]["location_text"],
    }


def build_status_response(
    boat: dict[str, Any],
    *,
    selector: dict[str, str | None],
    fetched_at: str,
    stale: bool,
    error: str | None,
) -> dict[str, Any]:
    payload = {
        "ok": True,
        "selector": selector,
        **build_summary(boat),
        "boat": boat,
        "source": URL,
        "fetched_at": fetched_at,
        "served_at": now_iso(),
        "stale": stale,
    }
    if error:
        payload["error"] = error
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "RSBoatExporter/2.1"

    def _send_json(self, payload: dict[str, Any], status: int = 200):
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
        params = parse_qs(parsed.query)

        if path == "/":
            self._send_json(
                {
                    "ok": True,
                    "service": "rs-status-api",
                    "version": "2.1",
                    "endpoints": {
                        "status": "/status?mmsi=257246500",
                        "boats": "/boats",
                        "healthz": "/healthz",
                    },
                    "defaults": {
                        "mmsi": DEFAULT_VESSEL_MMSI,
                        "rs": DEFAULT_RS_ID,
                        "name": DEFAULT_RS_NAME,
                    },
                    "served_at": now_iso(),
                },
                200,
            )
            return

        if path == "/status":
            fleet, stale, status, error = get_fleet()
            if fleet is None:
                self._send_json(
                    {
                        "ok": False,
                        "error": error or "Failed to fetch upstream data",
                        "served_at": now_iso(),
                        "stale": True,
                    },
                    status,
                )
                return

            selector = resolve_selector(params)
            if not any(selector.values()):
                self._send_json(
                    {
                        "ok": False,
                        "error": "Missing vessel selector. Provide ?mmsi=..., ?rs=..., or ?name=...",
                        "examples": [
                            "/status?mmsi=257246500",
                            "/status?rs=103",
                            "/status?name=RS 103 \"Dagfinn Paust\"",
                        ],
                        "served_at": now_iso(),
                    },
                    400,
                )
                return

            try:
                boat = find_boat(
                    fleet["boats"],
                    mmsi=selector["mmsi"],
                    rs=selector["rs"],
                    name=selector["name"],
                )
            except LookupError as exc:
                self._send_json(
                    {
                        "ok": False,
                        "error": str(exc),
                        "selector": selector,
                        "served_at": now_iso(),
                        "stale": stale,
                    },
                    404,
                )
                return

            payload = build_status_response(
                boat,
                selector=selector,
                fetched_at=fleet["fetched_at"],
                stale=stale,
                error=error,
            )
            self._send_json(payload, status)
            return

        if path == "/boats":
            fleet, stale, status, error = get_fleet()
            if fleet is None:
                self._send_json(
                    {
                        "ok": False,
                        "error": error or "Failed to fetch upstream data",
                        "served_at": now_iso(),
                        "stale": True,
                    },
                    status,
                )
                return

            payload = {
                "ok": True,
                "boat_count": fleet["boat_count"],
                "boats": fleet["boats"],
                "source": URL,
                "fetched_at": fleet["fetched_at"],
                "served_at": now_iso(),
                "stale": stale,
            }
            if error:
                payload["error"] = error
            self._send_json(payload, status)
            return

        if path == "/healthz":
            with _cache_lock:
                cache_age_seconds = None
                if _cache_data is not None:
                    cache_age_seconds = round(max(0.0, time.time() - _cache_ts), 3)

                payload = {
                    "ok": True,
                    "served_at": now_iso(),
                    "cache": {
                        "has_data": _cache_data is not None,
                        "age_seconds": cache_age_seconds,
                        "ttl_seconds": CACHE_SECONDS,
                        "last_success_at": datetime.fromtimestamp(_last_success_ts, timezone.utc).isoformat()
                        if _last_success_ts
                        else None,
                        "last_error": _last_error,
                    },
                    "defaults": {
                        "mmsi": DEFAULT_VESSEL_MMSI,
                        "rs": DEFAULT_RS_ID,
                        "name": DEFAULT_RS_NAME,
                    },
                    "source": URL,
                }
            self._send_json(payload, 200)
            return

        self._send_json({"ok": False, "error": "Not found"}, 404)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"Serving on http://{LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()





# #!/usr/bin/env python3
# import json
# import os
# import re
# import threading
# import time
# from datetime import datetime, timezone
# from http.server import BaseHTTPRequestHandler, HTTPServer
# from urllib.parse import urlparse

# import requests

# URL = "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats"

# RS_ID = os.getenv("RS_ID", "127")
# RS_NAME = os.getenv("RS_NAME", "Anne-Lise")
# LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
# LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))
# CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "120"))
# REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

# _cache_lock = threading.Lock()
# _cache_data = None
# _cache_ts = 0.0
# _last_error = None


# def now_iso() -> str:
#     return datetime.now(timezone.utc).isoformat()


# def normalize_status(raw: str) -> str:
#     s = raw.casefold()
#     if "sar" in s:
#         return "Kun SAR oppdrag"
#     if "uad" in s:
#         return "UAD"
#     if "operativ" in s:
#         return "Operativ"
#     if re.search(r"\b(?:30|60)\s*min\s+beredskap\b", s) or "beredskap" in s:
#         return "Beredskap"
#     return raw.strip()


# def find_boat(data: dict, rs: str, name: str) -> dict:
#     boats = data.get("rescueboats", [])
#     for boat in boats:
#         boat_rs = str(boat.get("rs", "")).strip()
#         boat_name = str(boat.get("name", ""))
#         if boat_rs == rs:
#             return boat
#         if name.casefold() in boat_name.casefold():
#             return boat
#     raise RuntimeError(f"Could not find RS {rs} / {name} in API response")


# def fetch_status() -> dict:
#     resp = requests.get(URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
#     resp.raise_for_status()
#     data = resp.json()

#     boat = find_boat(data, RS_ID, RS_NAME)

#     raw_status = (
#         boat.get("extendedState", {}).get("StatusText")
#         or boat.get("state_description")
#         or ""
#     )

#     return {
#         "ok": True,
#         "rs": boat.get("rs"),
#         "name": boat.get("name"),
#         "raw_status": raw_status,
#         "status": normalize_status(raw_status),
#         "station": boat.get("Station", {}).get("name"),
#         "timestamp": boat.get("koordinater", {}).get("Timestamp"),
#         "source": URL,
#         "served_at": now_iso(),
#         "stale": False,
#     }


# def get_status() -> tuple[dict, int]:
#     global _cache_data, _cache_ts, _last_error

#     with _cache_lock:
#         age = time.time() - _cache_ts
#         if _cache_data is not None and age < CACHE_SECONDS:
#             data = dict(_cache_data)
#             data["served_at"] = now_iso()
#             return data, 200

#     try:
#         fresh = fetch_status()
#         with _cache_lock:
#             _cache_data = fresh
#             _cache_ts = time.time()
#             _last_error = None
#         return fresh, 200
#     except Exception as exc:
#         with _cache_lock:
#             _last_error = str(exc)
#             if _cache_data is not None:
#                 stale = dict(_cache_data)
#                 stale["stale"] = True
#                 stale["error"] = str(exc)
#                 stale["served_at"] = now_iso()
#                 return stale, 200

#         return {
#             "ok": False,
#             "error": str(exc),
#             "served_at": now_iso(),
#             "stale": True,
#         }, 503


# class Handler(BaseHTTPRequestHandler):
#     def _send_json(self, payload: dict, status: int = 200):
#         body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
#         self.send_response(status)
#         self.send_header("Content-Type", "application/json; charset=utf-8")
#         self.send_header("Content-Length", str(len(body)))
#         self.send_header("Cache-Control", "no-store")
#         self.end_headers()
#         self.wfile.write(body)

#     def do_GET(self):
#         path = urlparse(self.path).path

#         if path == "/status":
#             payload, status = get_status()
#             self._send_json(payload, status)
#             return

#         if path == "/healthz":
#             self._send_json({"ok": True, "served_at": now_iso()}, 200)
#             return

#         self._send_json({"ok": False, "error": "Not found"}, 404)

#     def log_message(self, format, *args):
#         return


# if __name__ == "__main__":
#     server = HTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
#     print(f"Serving on http://{LISTEN_HOST}:{LISTEN_PORT}")
#     server.serve_forever()
