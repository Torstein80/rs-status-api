# RS status API for Home Assistant

This image exposes vessel status from the RS feed over a small HTTP API so it can be consumed by Home Assistant or other systems.

It is intended for users who already have:

- an LXC or VM running Docker
- Portainer installed
- network access from Home Assistant to the container

The API exposes:

- `/status` - vessel status as JSON
- `/healthz` - simple health endpoint

---

## What this container does

The service fetches vessel data from the upstream RS API, normalizes the status text, and returns a JSON response like this:

```json
{
  "ok": true,
  "rs": "127",
  "name": "Anne-Lise",
  "raw_status": "...",
  "status": "Operativ",
  "station": "...",
  "timestamp": "...",
  "source": "...",
  "served_at": "...",
  "stale": false
}
```

The app does **not** poll continuously.
It only fetches upstream data when `/status` is requested, and then caches the result for a short period.

---

## Docker image

Use this image:

```text
ghcr.io/Torstein80/rs-status-api:latest
```

---

## Environment variables

The following environment variables are supported:

| Variable | Required | Default | Description |
|---|---:|---|---|
| `RS_ID` | No | `127` | Rescue vessel ID |
| `RS_NAME` | No | `Anne-Lise` | Vessel name fallback used for matching |
| `LISTEN_HOST` | No | `0.0.0.0` | Bind address inside the container |
| `LISTEN_PORT` | No | `8080` | HTTP port inside the container |
| `CACHE_SECONDS` | No | `120` | Cache lifetime before a new upstream fetch |
| `REQUEST_TIMEOUT` | No | `20` | Timeout in seconds for upstream requests |
| `TZ` | No | `Europe/Oslo` | Container time zone |

In normal use, you usually only need to change:

- `RS_ID`
- `RS_NAME`

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
      RS_ID: ${RS_ID:-127}
      RS_NAME: ${RS_NAME:-Anne-Lise}
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

### 3. Set environment variables in Portainer

Before deploying the stack, set these variables in the Portainer UI if you want a vessel other than the defaults:

Find the available rescue vessels here: https://aistracker.rs.no/#/

```text
RS_ID=127
RS_NAME=Anne-Lise
```

You can keep the defaults and deploy immediately, or replace them with the vessel you want to track.

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
```

Expected behavior:

- `/healthz` returns a simple JSON health response
- `/status` returns vessel data in JSON

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

      - name: "RS Vessel Station"
        unique_id: rs_vessel_station
        value_template: "{{ value_json.station }}"

      - name: "RS Vessel Raw Status"
        unique_id: rs_vessel_raw_status
        value_template: "{{ value_json.raw_status }}"

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
3. Change:
   - `RS_ID`
   - `RS_NAME`
4. Redeploy the stack

You do **not** need to rebuild the image just to change vessel.

---

## Cache behavior

The app fetches upstream data only when `/status` is requested.

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

### Portainer cannot pull the image

If the image is private, configure GHCR registry credentials in Portainer.
If the image is public, no registry credentials are needed.

### `/healthz` works but `/status` fails

Check the container logs.
Possible causes:

- the upstream RS API is unavailable
- the selected `RS_ID` / `RS_NAME` does not match a vessel
- outbound internet access from the container is blocked

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
4. Set `RS_ID` and `RS_NAME`
5. Deploy the stack
6. Point Home Assistant to `http://YOUR_CONTAINER_IP:8080/status`

That is all that is needed to use the image.
