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
| 1. Capture | Stand up a listener on port 80 and 8443 with a local CA, point the garden at it through DNS, and log everything the garden sends. Establish whether the garden accepts the local certificate chain | Done — see result below |
| 2. Decode | Work out framing, authentication and the message set of the garden-to-cloud protocol from the logs | Blocked on the phase-1 result |
| 3. Bridge | Implement the server: connection handling, state model, local API, persistence | |
| 4. Home Assistant | Custom integration with the entity set above; HACS packaging | |
| 5. Hardening | Documentation, container image, tests against recorded traffic, handling of multiple gardens and of firmware updates | |

**Phase 1 result.** The bridge stood up and the garden reached it: it fetched the
CA over HTTP, and it accepted the original vendor CA bytes served back verbatim.
It **rejected a replacement CA**, so it never opened the TLS connection, and no
application bytes were captured. The cause is a 32-byte header on the CA file with
two computed fields that could not be reproduced — the full finding is in
[protocol.md](protocol.md#ca-trust-file-format-and-phase-1-bridge-results). Phase 2
(decode) cannot start until that header algorithm is known. The garden's firmware,
which contains it, is delivered only inside the TLS connection and so cannot be
pulled over the network.

Fallbacks, given the phase-1 result:

1. A Home Assistant integration that calls the vendor's phone-app REST API (fully documented in [protocol.md](protocol.md)). This depends on the vendor's service staying available but needs no changes to the garden. **This is currently the only working control path.**
2. Recovering the CA-file header algorithm so the local bridge can proceed — e.g. a flash/debug read of the controller board (opening the base; the Marvell part may use read-protected internal flash), a published server-side tool, or more `CA-*.bin` samples that constrain the algorithm.
3. The garden's LAN port 8080 was checked on a Bounty Elite: it accepts a TCP connection but returns nothing to `C5` frames or a plain read, so it is not a usable local interface here.

## Safety principles

- Do not send unknown or guessed bytes to a garden. Only replay documented frames or messages observed in real traffic.
- Keep every network change reversible (a single DNS record).
- The bridge never stores or logs the Wi-Fi password, account credentials or tokens.
