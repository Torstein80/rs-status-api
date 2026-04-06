# RS status API for Home Assistant

This image exposes vessel status from the RS feed over a small HTTP API so it can be consumed by Home Assistant or other systems.

It is intended for users who already have:

- an LXC or VM running Docker
- Portainer installed
- network access from Home Assistant to the container

The API exposes:

- `/status` - current status for one selected vessel
- `/status-texts` - duplicate-free list of all unique live `StatusText` values this service has ever seen
- `/healthz` - health and cache information

---

## What this container does

The service fetches vessel data from the upstream RS API, normalizes the selected vessel status text, and returns JSON like this:

```json
{
  "ok": true,
  "rs": "127",
  "name": "Anne-Lise",
  "mmsi": "257123456",
  "raw_status": "Ledig, på basen/patrulje",
  "status": "Ledig, på basen/patrulje",
  "status_text": "Ledig, på basen/patrulje",
  "state_description": "Operativ",
  "station": "...",
  "timestamp": "...",
  "source": "...",
  "served_at": "...",
  "stale": false
}
```

The app does **not** poll continuously.
It fetches upstream data only when one of the HTTP endpoints is requested, and then caches the fleet for a short period.

The `/status-texts` endpoint builds a growing history of unique `extendedState.StatusText` values over time, without duplicates. The history is saved to disk so it can survive container restarts when `/data` is persisted.

---

## Docker image

Use this image:

```text
ghcr.io/torstein80/rs-status-api:latest
```

---

## Environment variables

The following environment variables are supported:

| Variable | Required | Default | Description |
|---|---:|---|---|
| `VESSEL_MMSI` | No | empty | Preferred vessel selector |
| `RS_ID` | No | `127` | Fallback rescue vessel ID |
| `RS_NAME` | No | `Anne-Lise` | Fallback vessel name |
| `STATUS_HISTORY_FILE` | No | `/data/status_text_history.json` | Where seen `StatusText` history is stored |
| `LISTEN_HOST` | No | `0.0.0.0` | Bind address inside the container |
| `LISTEN_PORT` | No | `8080` | HTTP port inside the container |
| `CACHE_SECONDS` | No | `120` | Cache lifetime before a new upstream fetch |
| `REQUEST_TIMEOUT` | No | `20` | Timeout in seconds for upstream requests |
| `TZ` | No | `Europe/Oslo` | Container time zone |

In normal use, you usually only need to set `VESSEL_MMSI`.

If `VESSEL_MMSI` is not set, the app falls back to `RS_ID`, then `RS_NAME`.

---

## Deploy with Portainer

### 1. Open Portainer

Open your Portainer instance in a browser and log in.

### 2. Create a new stack

In Portainer:

1. Go to **Stacks**
2. Click **Add stack**
3. Choose a name such as `rs-status-api`
4. Select **Web editor**

Paste this stack:

```yaml
services:
  rs-status-api:
    image: ghcr.io/torstein80/rs-status-api:latest
    container_name: rs-status-api
    restart: unless-stopped
    environment:
      VESSEL_MMSI: ${VESSEL_MMSI:-}
      RS_ID: ${RS_ID:-127}
      RS_NAME: ${RS_NAME:-Anne-Lise}
      STATUS_HISTORY_FILE: /data/status_text_history.json
      LISTEN_HOST: 0.0.0.0
      LISTEN_PORT: 8080
      CACHE_SECONDS: 120
      REQUEST_TIMEOUT: 20
      TZ: Europe/Oslo
    volumes:
      - rs-status-data:/data
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

volumes:
  rs-status-data:
```

### 3. Set environment variables in Portainer

Before deploying the stack, set these variables in the Portainer UI if you want a vessel other than the defaults.

Find the available rescue vessels and their MMSI values here:

```text
https://aistracker.rs.no/#/
```

Recommended:

```text
VESSEL_MMSI=257123456
```

Optional fallbacks:

```text
RS_ID=127
RS_NAME=Anne-Lise
```

You can keep the fallback defaults and deploy immediately, but MMSI is the preferred selector.

### 4. Deploy the stack

Click **Deploy the stack**.

Portainer will pull the image from GHCR and start the container.

---

## Network setup

This stack publishes the container on:

```text
8080/tcp
```

That means the API will be available at:

```text
http://YOUR_CONTAINER_IP:8080/status
http://YOUR_CONTAINER_IP:8080/status-texts
http://YOUR_CONTAINER_IP:8080/healthz
```

Example:

```text
http://192.168.1.50:8080/status
```

Make sure:

- the container host allows inbound traffic to port `8080`
- Home Assistant can reach the container IP
- no other service is already using port `8080`

If port `8080` is already in use, change the published port in the stack:

```yaml
ports:
  - "8090:8080"
```

Then use:

```text
http://YOUR_CONTAINER_IP:8090/status
```

---

## Verify the container is working

From another machine on the same network, run:

```bash
curl http://YOUR_CONTAINER_IP:8080/healthz
curl http://YOUR_CONTAINER_IP:8080/status
curl http://YOUR_CONTAINER_IP:8080/status-texts
```

Expected behavior:

- `/healthz` returns health and cache info
- `/status` returns one vessel in JSON
- `/status-texts` returns the accumulated, duplicate-free history of unique `StatusText` values observed by the service

---

## Choosing a vessel

The service selects the vessel in this order:

1. `?mmsi=` query parameter
2. `VESSEL_MMSI`
3. `?rs=` query parameter
4. `RS_ID`
5. `?name=` query parameter
6. `RS_NAME`

Examples:

```bash
curl "http://YOUR_CONTAINER_IP:8080/status?mmsi=257123456"
curl "http://YOUR_CONTAINER_IP:8080/status?rs=127"
curl "http://YOUR_CONTAINER_IP:8080/status?name=Anne-Lise"
```

---

## Add to Home Assistant

Use the REST integration in Home Assistant.

Example configuration:

```yaml
rest:
  - resource: "http://YOUR_CONTAINER_IP:8080/status"
    scan_interval: 300
    sensor:
      - name: "RS Vessel Status"
        unique_id: rs_vessel_status
        value_template: "{{ value_json.status }}"

      - name: "RS Vessel Status Text"
        unique_id: rs_vessel_status_text
        value_template: "{{ value_json.status_text }}"

      - name: "RS Vessel State Description"
        unique_id: rs_vessel_state_description
        value_template: "{{ value_json.state_description }}"

      - name: "RS Vessel Station"
        unique_id: rs_vessel_station
        value_template: "{{ value_json.station }}"

      - name: "RS Vessel Timestamp"
        unique_id: rs_vessel_timestamp
        value_template: "{{ value_json.timestamp }}"

      - name: "RS Vessel Data Stale"
        unique_id: rs_vessel_data_stale
        value_template: "{{ value_json.stale }}"
```

Replace `YOUR_CONTAINER_IP` with the IP address or hostname of the Docker host running the container.

---

## Why the `/status-texts` history matters

The live RS feed only shows the statuses that are present right now.

This service keeps a duplicate-free list of statuses it has seen over time, so if a status appears later, it will be added automatically and remembered.

Each entry includes:

- `status_text`
- `first_seen`
- `last_seen`
- `seen_count`

Example:

```json
{
  "ok": true,
  "count": 3,
  "status_texts": [
    "Ledig, på basen/patrulje",
    "30 min beredskap",
    "UAD"
  ],
  "items": [
    {
      "status_text": "Ledig, på basen/patrulje",
      "first_seen": "2026-04-06T19:40:00+00:00",
      "last_seen": "2026-04-06T21:10:00+00:00",
      "seen_count": 14
    }
  ]
}
```

---

## Changing vessel later

To track a different vessel:

1. Open the stack in Portainer
2. Edit the stack
3. Change `VESSEL_MMSI` or one of the fallback selectors
4. Redeploy the stack

You do **not** need to rebuild the image just to change vessel.

---

## Cache behavior

The app fetches upstream data only when an endpoint is requested.

With the default settings:

- first request fetches fresh data
- repeated requests within `120` seconds use cached data
- first request after cache expiry fetches fresh data again

If Home Assistant is configured with:

```yaml
scan_interval: 300
```

then the upstream API will usually be queried about every 5 minutes.

---

## Troubleshooting

### The container does not start

Check the stack logs in Portainer.
Common causes:

- port `8080` is already in use
- the image could not be pulled
- invalid YAML in the stack
- the history file path is not writable

### `/healthz` works but `/status` fails

Check the container logs.
Possible causes:

- the upstream RS API is unavailable
- the selected `VESSEL_MMSI`, `RS_ID`, or `RS_NAME` does not match a vessel
- outbound internet access from the container is blocked

### `/status-texts` does not survive restarts

Make sure `/data` is persisted with a Docker volume or bind mount.
The default Compose file already does this with:

```yaml
volumes:
  - rs-status-data:/data
```

### Home Assistant cannot read the endpoint

Check:

- the URL is correct
- Home Assistant can reach the container IP
- the published port is correct
- a firewall is not blocking traffic

### Data looks old

The app caches results for `CACHE_SECONDS` seconds.
Reduce that value if you want more frequent upstream refreshes.

---

## Summary

For most users, setup is:

1. Open Portainer
2. Create a stack from the Web editor
3. Paste the Compose file
4. Set `VESSEL_MMSI`
5. Deploy the stack
6. Point Home Assistant to `http://YOUR_CONTAINER_IP:8080/status`
7. Use `http://YOUR_CONTAINER_IP:8080/status-texts` to see the growing duplicate-free status list
