# RS Status API

Small Docker image that exposes Redningsselskapet vessel data over HTTP.

It is made for Home Assistant, but any system that can read JSON over HTTP can use it.

## What it does

The container gives you three HTTP endpoints:

- `/status` – returns status for one selected vessel
- `/vessels` – returns a list of available RS vessels, including MMSI when available
- `/healthz` – simple health check

The app can also add AIS data to `/status` when AIS data is available.

## Quick start

### 1. Deploy in Portainer

Use this stack:

```yaml
services:
  rs-status-api:
    image: ghcr.io/torstein80/rs-status-api:latest
    container_name: rs-status-api
    restart: unless-stopped
    environment:
      MMSI: "${MMSI:-}"
      RS_ID: "${RS_ID:-}"
      RS_NAME: "${RS_NAME:-}"
      LISTEN_HOST: 0.0.0.0
      LISTEN_PORT: 8080
      CACHE_SECONDS: 120
      REQUEST_TIMEOUT: 20
      TZ: Europe/Oslo
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

### 2. Choose a vessel

You can choose the default vessel in Portainer by setting **one** of these environment variables:

- `MMSI`
- `RS_ID`
- `RS_NAME`

Examples:

- `MMSI=257227000`
- `RS_ID=127`
- `RS_NAME=Anne-Lise`

You only need one of them.

### 3. Test it

Open these URLs in a browser or test them with `curl`:

```bash
curl http://YOUR-CONTAINER-IP:8080/healthz
curl http://YOUR-CONTAINER-IP:8080/vessels
curl http://YOUR-CONTAINER-IP:8080/status
```

If you did not set a default vessel, `/status` will return an error until you either:

- set `MMSI`, `RS_ID`, or `RS_NAME` in Portainer, or
- use a query parameter such as `?mmsi=257227000`

## How vessel selection works

There is **no built-in default vessel** in the image.

The app picks a vessel in this order:

1. `?mmsi=` in the request
2. `?rs=` in the request
3. `?name=` in the request
4. `MMSI` environment variable
5. `RS_ID` environment variable
6. `RS_NAME` environment variable

This means:

- query parameters override the Portainer settings
- query parameters only apply to that one request
- query parameters do **not** permanently change the container

Example:

- `GET /status?mmsi=257227000` returns that vessel for that request only
- the next plain `GET /status` goes back to the environment variables

## Endpoints

### `/healthz`

Shows that the container is running.

This endpoint does **not** fetch vessel data.

Example response:

```json
{
  "ok": true,
  "served_at": "2026-04-14T12:00:00+00:00",
  "defaults": {
    "mmsi": null,
    "rs": null,
    "name": null
  }
}
```

### `/vessels`

Returns the list of available RS vessels.

Useful calls:

- `/vessels`
- `/vessels?only_with_mmsi=1`
- `/vessels?only_with_ais=1`

Use this endpoint when you want to find the MMSI for a vessel.

Example response shape:

```json
{
  "ok": true,
  "count": 2,
  "vessels": [
    {
      "rs": "127",
      "name": "Anne-Lise",
      "mmsi": "257227000",
      "station": "Some station",
      "ais_available_now": true
    }
  ]
}
```

### `/status`

Returns one selected vessel.

Useful calls:

- `/status`
- `/status?mmsi=257227000`
- `/status?rs=127`
- `/status?name=Anne-Lise`

Possible results:

- `200` when a vessel was found
- `400` when no selector was provided
- `404` when a selector was provided but no vessel matched

Typical fields in the response:

- `status`
- `raw_status`
- `status_id`
- `status_color`
- `station`
- `timestamp`
- `mmsi`
- `selector`
- `stale`
- `upstream_error`
- `ais.sog_knots`
- `ais.cog_degrees`

## Home Assistant and Node-RED examples

Ready-to-use examples are included in this repository.

Files:

- [examples/home-assistant/rest-sensor.yaml](examples/home-assistant/rest-sensor.yaml)
- [examples/node-red/rs-status-flow.json](examples/node-red/rs-status-flow.json)
- [examples/node-red/README.md](examples/node-red/README.md)

### Home Assistant

Use the example in:

```text
examples/home-assistant/rest-sensor.yaml
```

It creates `sensor.rs_vessel_status`, stores the main vessel status as the entity state, and exposes the rest of the vessel data as attributes.

### Node-RED

Import the example flow from:

```text
examples/node-red/rs-status-flow.json
```

This example flow shows how to:

- poll `sensor.rs_vessel_status`
- inspect RS vessel fields in debug nodes
- send mobile notifications only when vessel or `raw_status` changes
- control Philips Hue scenes based on `raw_status`

Import steps:

1. Open Node-RED
2. Open the menu in the top right
3. Choose **Import**
4. Paste or upload `examples/node-red/rs-status-flow.json`
5. Select your Home Assistant server in the imported nodes
6. Update the mobile notify service if needed
7. Update the scene entity IDs if needed
8. Deploy

## Notes

- The app caches upstream data in memory for `CACHE_SECONDS`
- `/healthz` does not trigger a refresh
- If the boat feed fails but cached data exists, cached data is returned with `stale: true`
- If AIS fails, boat status can still be returned
