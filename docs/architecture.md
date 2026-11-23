# Architecture

OpenGarden has two parts: a **bridge** that the garden connects to instead of the vendor's cloud, and a **Home Assistant integration** that talks to the bridge. Nothing in this repository is implemented yet; this document describes the plan. The protocol details are in [protocol.md](protocol.md).

## Overview

```
                    your LAN
 +-----------+      DNS: app5.aerogarden.com -> bridge       +-----------------+
 |           |  TLS :8443   (and plain HTTP :80 for CA)      |                 |
 |  Garden   | --------------------------------------------> |     Bridge      |
 | (Wi-Fi)   | <--------------------------------------------  |  (OpenGarden)   |
 |           |        state reports / commands                |                 |
 +-----------+                                                +--------+--------+
                                                                       |
                                                              local API (HTTP/WebSocket)
                                                                       |
                                                              +--------v--------+
                                                              |  Home Assistant |
                                                              |  custom         |
                                                              |  integration    |
                                                              +-----------------+
```

The garden is configured as it is today (Wi-Fi entered on its touchscreen). The only network change is that the local DNS server answers the garden's cloud hostname with the bridge's LAN address. No internet access is needed for operation.

## Bridge server

A small service, intended to run in a container on the same LAN as the garden.

| Port | Protocol | Purpose |
|---|---|---|
| 80 | HTTP | Serves the bridge's CA certificate. The garden is observed to fetch a CA certificate over plain HTTP before connecting. |
| 8443 | TLS | Accepts the garden's connection using a server certificate signed by the bridge's CA. Handles the 2-second heartbeat and automatic reconnects, and the garden-to-cloud application protocol once decoded. |
| local API port (to be chosen) | HTTP and WebSocket | Exposes garden state and accepts commands from Home Assistant. |

Responsibilities:

- Generate and persist a CA and server certificate for the cloud hostname on first run.
- Keep the garden's connection alive and log the raw bytes of everything it sends (during the research phase this log is the main output).
- Maintain the current state of each connected garden, keyed by MAC address.
- Translate local API commands into messages for the garden.
- Provide the state in the same shape as the vendor's phone-app API (`GET v1/devices`, `PUT v1/devices/{mac}`, with the decimal string encodings) so that code can be shared with a cloud-based integration if that fallback is ever needed. An optional compatibility mode could also serve the old form-encoded API for the existing community integrations.
- Optionally allow the owner to keep the garden's firmware update path unreachable (for example by not forwarding unknown hostnames), so updates are never applied unexpectedly.

### Local DNS

The bridge does not run DNS. The owner adds a single record on the router or local DNS server (for example in a Pi-hole, AdGuard Home or router host-override list):

```
app5.aerogarden.com  ->  192.168.1.x   (the bridge)
```

The phone app uses the same hostname (`app5.aerogarden.com`), so a house-wide record would send the phone app to the bridge as well, and the app would stop working. The record should therefore apply to the garden's address only: a per-client rule in AdGuard Home or Pi-hole, or a router destination-NAT rule that matches the garden's source address on ports 80 and 8443. Removing the rule restores the original behaviour.

## Home Assistant integration

A custom integration (HACS-installable) in `custom_components/opengarden/`, using local polling or push from the bridge's local API. Config flow: bridge address, optional token.

### Planned entities

Per garden (one device per MAC):

| Entity | Type | Source field |
|---|---|---|
| Light | `light` (on/off, brightness) | `light.status`, `light.dimming` |
| Light schedule on / off time | `time` | `light.cycle` |
| Sunrise / sunset ramp duration | `number` (minutes) | `light.sunrise`, `light.sunset` |
| Sunrise/sunset ramp enabled | `switch` | `light.sunriseSunsetEnabled` |
| Vacation mode | `switch` | `light.vacationModeEnabled` |
| Pump | `switch` | `pump.status` |
| Pump minutes on / off | `number` | `pump.cycle` |
| Pump test | `button` | `pump.performTest` |
| Drain | `button` or `switch` | `pump.drain` |
| Low-water safety mode | `switch` | `pump.pumpSafetyMode` |
| Water level | `sensor` (low / medium / high) | `pump.waterLevel` |
| Water needed | `binary_sensor` | `pump.shortage` |
| Plant food needed | `binary_sensor` | `nutrition.shortage` |
| Plant food days left | `sensor` | `nutrition.reminder` |
| Plant food reminder | `switch` | `nutrition.reminderFlag` |
| Days planted / days until harvest | `sensor` | `plant.daysPlanted`, `plant.totalDaysUntilHarvest` |
| Connectivity | `binary_sensor` | `isOnline` |
| Clock sync | `button` | `clock` |
| Firmware version, IP address, SSID | diagnostic `sensor` | `version.*`, `network.*` |

Some entities depend on open questions in the protocol reference (for example the exact meaning of `light.status` versus `light.temporaryStatus`, and whether a Bounty Elite reports one zone or two).

## Development phases

| Phase | Goal | Status |
|---|---|---|
| 0. Research | Document the phone-app API, state model, encodings and LAN frames; survey prior work | Done (see docs) |
| 1. Capture | Stand up a listener on port 80 and 8443 with a local CA, point the garden at it through DNS, and log everything the garden sends. Establish whether the garden accepts the local certificate chain | Next |
| 2. Decode | Work out framing, authentication and the message set of the garden-to-cloud protocol from the logs | |
| 3. Bridge | Implement the server: connection handling, state model, local API, persistence | |
| 4. Home Assistant | Custom integration with the entity set above; HACS packaging | |
| 5. Hardening | Documentation, container image, tests against recorded traffic, handling of multiple gardens and of firmware updates | |

Fallbacks if phase 1 shows the garden cannot be pointed at a local server:

1. A Home Assistant integration that calls the vendor's phone-app REST API (fully documented in [protocol.md](protocol.md)). This depends on the vendor's service staying available but needs no changes to the garden.
2. A one-time check of the garden's LAN port 8080 (the Farm light lift uses it) to see whether the Bounty Elite exposes any local interface.
3. Hardware-level options, only if the owner explicitly chooses them.

## Safety principles

- Do not send unknown or guessed bytes to a garden. Only replay documented frames or messages observed in real traffic.
- Keep every network change reversible (a single DNS record).
- The bridge never stores or logs the Wi-Fi password, account credentials or tokens.
