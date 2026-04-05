# RS status API for Home Assistant via Portainer

This repo contains:

- `app.py`: small HTTP API that exposes `/status` and `/healthz`
- `Dockerfile`: container image build
- `docker-compose.yml`: Portainer stack file
- `.github/workflows/build-ghcr.yml`: GitHub Actions workflow that builds and pushes the image to GHCR

## What you edit

- In the repo once: replace `YOUR_GITHUB_USERNAME` in `docker-compose.yml`
- In Portainer UI: `RS_ID` and `RS_NAME`

## Endpoints

- `http://YOUR-LXC-IP:8080/status`
- `http://YOUR-LXC-IP:8080/healthz`

## Home Assistant example

```yaml
rest:
  - resource: "http://10.69.250.67:8080/status"
    scan_interval: 300
    sensor:
      - name: "RS Anne-Lise Status"
        unique_id: rs_anne_lise_status
        value_template: "{{ value_json.status }}"

      - name: "RS Anne-Lise Station"
        unique_id: rs_anne_lise_station
        value_template: "{{ value_json.station }}"

      - name: "RS Anne-Lise Raw Status"
        unique_id: rs_anne_lise_raw_status
        value_template: "{{ value_json.raw_status }}"

      - name: "RS Anne-Lise Timestamp"
        unique_id: rs_anne_lise_timestamp
        value_template: "{{ value_json.timestamp }}"

      - name: "RS Anne-Lise Data Stale"
        unique_id: rs_anne_lise_data_stale
        value_template: "{{ value_json.stale }}"
```
