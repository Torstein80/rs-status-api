# Node-RED example

This example flow reads `sensor.rs_vessel_status` from Home Assistant and shows how to:

- inspect RS vessel fields in Node-RED
- filter notifications so they only trigger on meaningful status changes
- send phone notifications with image and vessel details
- control Philips Hue scenes based on `raw_status`

## Files

- `rs-status-flow.json` - importable Node-RED flow

## What the flow does

### Poll RS vessel status

The flow starts by polling:

```text
sensor.rs_vessel_status
```

### Fan out RS fields

A function node splits the Home Assistant entity into separate messages so you can inspect or reuse:

- `raw_status`
- `station`
- `mmsi`
- `name`
- `image_url`
- and other attributes

### Notification filter

A small function creates a key from `mmsi` and `raw_status`.
An `rbe` node blocks repeated notifications unless either the vessel or raw status changes.

### Mobile notification

The flow builds a Home Assistant Companion notification with:

- vessel name as title
- operational status
- station and region
- RS number, MMSI, and callsign
- last update timestamp
- vessel image

### Philips Hue scene control

The flow also uses `raw_status` to activate different Home Assistant scenes.

## Update after import

Before deploying the flow, update these items for your own setup:

- select your Home Assistant server in the imported nodes
- change the mobile notify service if your phone service name is different
- change the scene entity IDs if your scene names are different
- change the entity ID if you renamed `sensor.rs_vessel_status`

## Main flow paths

Notification path:

```text
poll-state -> Fan out RS fields -> function 5 -> rbe -> function 4 -> notify.mobile_app_...
```

Hue path:

```text
poll-state -> Fan out RS fields -> switch(raw_status) -> scene.turn_on
```
