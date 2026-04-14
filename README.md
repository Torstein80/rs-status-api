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

- `MMSI=257895900`
- `RS_ID=127`
- `RS_NAME=Anne-Lise`

You only need one of them.

### 3. Test it

Open these URLs in a browser or test them with `curl`:

```bash
curl http://YOUR-CONTAINER-IP:8080/healthz
curl http://YOUR-CONTAINER-IP:8080/vessels
curl http://YOUR-CONTAINER-IP:8080/status
curl "http://YOUR-CONTAINER-IP:8080/status?mmsi=257895900"
```

If you did not set a default vessel, `/status` will return an error until you either:

- set `MMSI`, `RS_ID`, or `RS_NAME` in Portainer, or
- use a query parameter such as `?mmsi=257895900`

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

- `GET /status?mmsi=257895900` returns that vessel for that request only
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
      "name": "RS 127 \"Anne-Lise\"",
      "mmsi": "257895900",
      "station": "Lillesand",
      "ais_available_now": true
    }
  ]
}
```

### `/status`

Returns one selected vessel.

Useful calls:

- `/status`
- `/status?mmsi=257895900`
- `/status?rs=127`
- `/status?name=Anne-Lise`

Possible results:

- `200` when a vessel was found
- `400` when no selector was provided
- `404` when a selector was provided but no vessel matched

Example response:

```json
{
  "ok": true,
  "selector": {
    "mmsi": "257895900",
    "rs": null,
    "name": null,
    "selected_by": "query",
    "matched_on": "mmsi"
  },
  "rs": "127",
  "name": "RS 127 \"Anne-Lise\"",
  "mmsi": "257895900",
  "callsign": "LF3933",
  "class": "Simrad-klassen",
  "vessel_type": "Sjøredningskorps",
  "raw_status": "60 min beredskap",
  "status": "Beredskap",
  "status_id": 1,
  "status_color": "#FF9933",
  "status_reason": "Ingen årsak",
  "status_note": null,
  "state": "1",
  "state_description": "Beredskap",
  "expected_back": null,
  "station": "Lillesand",
  "station_code": "72",
  "station_region": "Sørlandet",
  "station_type": "RSRK",
  "timestamp": "2026-04-14T21:30:30Z",
  "position_source": "ais",
  "latitude": "58° 14.84550",
  "longitude": "8° 22.71222",
  "decimal_latitude": 58.247425,
  "decimal_longitude": 8.378537,
  "image_url": "https://www.redningsselskapet.no/content/uploads/2019/02/RS127.jpg",
  "boats_source": "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats",
  "ais_source": "https://ais.rs.no/aktive_pos.json",
  "served_at": "2026-04-14T21:45:04.481220+00:00",
  "stale": false,
  "upstream_error": null,
  "ais": {
    "available_now": true,
    "ship_name": "RS127 ANNE-LISE",
    "destination": "N/A",
    "time_stamp": "2026-04-14T21:30:30Z",
    "sog_knots": 0,
    "cog_degrees": 95,
    "latitude": "58° 14.84550",
    "longitude": "8° 22.71222",
    "decimal_latitude": 58.247425,
    "decimal_longitude": 8.378537
  }
}
```

## Home Assistant

### Recommended setup

The easiest way to expose **all data** from `/status` to Home Assistant is to create one REST sensor and store the full response as attributes.

That gives you:

- sensor state = normalized vessel status
- all top-level fields from `/status` as sensor attributes
- `selector` and `ais` included as nested attributes

Paste this into `configuration.yaml`:

```yaml
sensor:
  - platform: rest
    name: "RS Vessel Status"
    unique_id: rs_vessel_status
    resource: "http://YOUR-CONTAINER-IP:8080/status"
    scan_interval: 300
    timeout: 30
    value_template: "{{ value_json.status }}"
    json_attributes:
      - ok
      - selector
      - rs
      - name
      - mmsi
      - callsign
      - class
      - vessel_type
      - raw_status
      - status
      - status_id
      - status_color
      - status_reason
      - status_note
      - state
      - state_description
      - expected_back
      - station
      - station_code
      - station_region
      - station_type
      - timestamp
      - position_source
      - latitude
      - longitude
      - decimal_latitude
      - decimal_longitude
      - image_url
      - boats_source
      - ais_source
      - served_at
      - stale
      - upstream_error
      - ais
```

If you do **not** want a default vessel in the container, point Home Assistant directly at one vessel instead:

```yaml
sensor:
  - platform: rest
    name: "RS Vessel Status"
    unique_id: rs_vessel_status
    resource: "http://YOUR-CONTAINER-IP:8080/status?mmsi=257895900"
    scan_interval: 300
    timeout: 30
    value_template: "{{ value_json.status }}"
    json_attributes:
      - ok
      - selector
      - rs
      - name
      - mmsi
      - callsign
      - class
      - vessel_type
      - raw_status
      - status
      - status_id
      - status_color
      - status_reason
      - status_note
      - state
      - state_description
      - expected_back
      - station
      - station_code
      - station_region
      - station_type
      - timestamp
      - position_source
      - latitude
      - longitude
      - decimal_latitude
      - decimal_longitude
      - image_url
      - boats_source
      - ais_source
      - served_at
      - stale
      - upstream_error
      - ais
```

### What you get in Home Assistant

After adding the sensor above, these values are available as attributes on `sensor.rs_vessel_status`:

- `rs`
- `name`
- `mmsi`
- `callsign`
- `class`
- `vessel_type`
- `raw_status`
- `status`
- `status_id`
- `status_color`
- `status_reason`
- `status_note`
- `state`
- `state_description`
- `expected_back`
- `station`
- `station_code`
- `station_region`
- `station_type`
- `timestamp`
- `position_source`
- `latitude`
- `longitude`
- `decimal_latitude`
- `decimal_longitude`
- `image_url`
- `boats_source`
- `ais_source`
- `served_at`
- `stale`
- `upstream_error`
- `selector`
- `ais`

That means all the data from the JSON response is available in Home Assistant from one sensor.

### Optional: create separate Home Assistant sensors for common fields

If you want some values as their own entities, add template sensors like this:

```yaml
template:
  - sensor:
      - name: "RS Vessel Station"
        unique_id: rs_vessel_station
        state: "{{ state_attr('sensor.rs_vessel_status', 'station') }}"

      - name: "RS Vessel MMSI"
        unique_id: rs_vessel_mmsi
        state: "{{ state_attr('sensor.rs_vessel_status', 'mmsi') }}"

      - name: "RS Vessel Latitude"
        unique_id: rs_vessel_latitude
        state: "{{ state_attr('sensor.rs_vessel_status', 'decimal_latitude') }}"

      - name: "RS Vessel Longitude"
        unique_id: rs_vessel_longitude
        state: "{{ state_attr('sensor.rs_vessel_status', 'decimal_longitude') }}"

      - name: "RS Vessel AIS SOG"
        unique_id: rs_vessel_ais_sog
        unit_of_measurement: "kn"
        state: >
          {% set ais = state_attr('sensor.rs_vessel_status', 'ais') %}
          {{ ais.sog_knots if ais is mapping else none }}

      - name: "RS Vessel AIS COG"
        unique_id: rs_vessel_ais_cog
        unit_of_measurement: "°"
        state: >
          {% set ais = state_attr('sensor.rs_vessel_status', 'ais') %}
          {{ ais.cog_degrees if ais is mapping else none }}

      - name: "RS Vessel Data Stale"
        unique_id: rs_vessel_data_stale
        state: "{{ state_attr('sensor.rs_vessel_status', 'stale') }}"
```

### Optional: picture card example

If you want to show the vessel image on a dashboard, use the `image_url` attribute:

```yaml
type: picture
image: "[[[ return states['sensor.rs_vessel_status'].attributes.image_url; ]]]"
```

## Notes

- The app caches upstream data in memory for `CACHE_SECONDS`
- `/healthz` does not trigger a refresh
- If the boat feed fails but cached data exists, cached data is returned with `stale: true`
- If AIS fails, boat status can still be returned
- If you want to find a vessel MMSI first, use `/vessels?only_with_mmsi=1`
