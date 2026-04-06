# RS status API for Home Assistant

This container exposes vessel status from the RS feed over a small HTTP API so it can be consumed by Home Assistant or other systems.

It is intended for users who already have:

- an LXC or VM running Docker
- Portainer installed
- network access from Home Assistant to the container

The API exposes:

- `/status` - status for the selected vessel as JSON
- `/status-texts` - duplicate-free list of all unique `status_text` values this running service has ever seen
- `/healthz` - health and cache information

---

## What this container does

The service fetches vessel data from the upstream RS API, selects one vessel, normalizes the status fields, and returns a compact JSON response.

By default, vessel selection should be done by MMSI.
The current stack file is preconfigured for **RS 127 "Anne-Lise"** using **MMSI `257895900`**.

Example `/status` response:

```json
{
  "ok": true,
  "rs": "127",
  "name": "RS 127 \"Anne-Lise\"",
  "mmsi": "257895900",
  "raw_status": "30 min beredskap",
  "status": "30 min beredskap",
  "status_text": "30 min beredskap",
  "state_description": "Beredskap",
  "station": "Lillesand",
  "timestamp": "2026-04-06T18:56:06.000Z",
  "source": "https://prod-rsfeed-xml2json-proxy.rs-marine-services.rs.no/prefetch/getboats",
  "served_at": "2026-04-06T20:00:00+00:00",
  "stale": false
}
```

The app does **not** poll continuously.
It only fetches upstream data when `/status`, `/status-texts`, or `/healthz` is requested, and then caches the upstream response for a short period.

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
| `RS_ID` | No | `127` | Optional fallback vessel selector |
| `RS_NAME` | No | `Anne-Lise` | Optional fallback vessel selector |
| `LISTEN_HOST` | No | `0.0.0.0` | Bind address inside the container |
| `LISTEN_PORT` | No | `8080` | HTTP port inside the container |
| `CACHE_SECONDS` | No | `120` | Cache lifetime before a new upstream fetch |
| `REQUEST_TIMEOUT` | No | `20` | Timeout in seconds for upstream requests |
| `STATUS_HISTORY_FILE` | No | `/data/status_text_history.json` | Persistent file used by `/status-texts` |
| `TZ` | No | `Europe/Oslo` | Container time zone |

In normal use, you usually only need to set:

- `VESSEL_MMSI`

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
      VESSEL_MMSI: "257895900" # RS 127 "Anne-Lise"
      LISTEN_HOST: 0.0.0.0
      LISTEN_PORT: 8080
      CACHE_SECONDS: 120
      REQUEST_TIMEOUT: 20
      STATUS_HISTORY_FILE: /data/status_text_history.json
      TZ: Europe/Oslo
      # Optional fallback selectors if you do not want to use MMSI:
      # RS_ID: "127"
      # RS_NAME: "Anne-Lise"
    ports:
      - "8080:8080"
    volumes:
      - rs-status-api-data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

volumes:
  rs-status-api-data:
```

### 3. Set environment variables in Portainer

The included stack already targets **RS 127 "Anne-Lise"**.

If you want to track another vessel, replace:

```text
VESSEL_MMSI=257895900
```

with the MMSI for the vessel you want.

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

- `/healthz` returns JSON with cache and history info
- `/status` returns vessel data in JSON
- `/status-texts` returns a persistent duplicate-free list of all seen `status_text` values

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

## Changing vessel later

To track a different vessel:

1. Open the stack in Portainer
2. Edit the stack
3. Change `VESSEL_MMSI`
4. Redeploy the stack

You do **not** need to rebuild the image just to change vessel.

---

## Status history behavior

The `/status-texts` endpoint keeps a duplicate-free history of every unique upstream `status_text` this service has seen.

That history is stored in:

```text
/data/status_text_history.json
```

Because the stack mounts `/data` as a Docker volume, the history survives container restarts and recreations.

---

## Cache behavior

The app fetches upstream data only when an endpoint is requested.

With the default settings:

- first request fetches fresh data
- repeated requests within `120` seconds use cached data
- first request after cache expiry fetches fresh data again
- if upstream fetch fails but cached data exists, the app serves cached data with `stale: true`

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

### `/healthz` works but `/status` fails

Check the container logs.
Possible causes:

- the upstream RS API is unavailable
- the selected `VESSEL_MMSI` does not match a vessel
- outbound internet access from the container is blocked

### `/status-texts` is empty

The service only learns status texts from live upstream responses.
If it has not yet completed a successful fetch, the list may still be empty.

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
4. Keep `VESSEL_MMSI=257895900` for Anne-Lise, or replace it with another vessel MMSI
5. Deploy the stack
6. Point Home Assistant to `http://YOUR_CONTAINER_IP:8080/status`

That is all that is needed to use the image.
