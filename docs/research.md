# Research notes

Background gathered while preparing OpenGarden: the state of the vendor's service, what the community has already built, what has been observed about the garden's network behaviour, and techniques other projects use for local control of cloud-connected devices. Technical detail lives in [protocol.md](protocol.md).

## Company and cloud status

| Date | Event |
|---|---|
| 2020 | Scotts Miracle-Gro acquired AeroGrow (maker of AeroGarden). |
| 2023-06/07 | Multi-week cloud outage. Support described a "server issue" connecting gardens to Wi-Fi and the app. Gardens reconnected by themselves around mid/late July. Gardens depend on the cloud to appear online but keep their on-device schedule. |
| 2024-06-26 | New app and backend launched "under new firmware & software". The old and new apps cannot work at the same time. Pre-2019 Classic Harvest, Bounty and Farm gardens dropped from app support. |
| 2024-10 | Announcement that the brand would stop selling and cease operations effective 2025-01-01. Press said the app would keep working for an extended period and that the gardens remain usable from the touchscreen. |
| 2024-12 to 2025-03 | Reports that the decision was reversed. |
| 2025 H2 | Official statement that AeroGarden remains part of the Scotts Miracle-Gro family, with a new digital home planned. |
| 2026-11 | Third-party coverage still describes the brand as in business. |

Summary as of 2026-11-22: the brand is active and no cloud shutdown date has been announced. There is no public cloud API. The cloud is a single point of failure: it can change or be discontinued without notice, which is the reason to have a local option.

The current Android app (`com.aerogarden.app`) had about 5K+ downloads and a 3.6 rating on Google Play; the iOS app was listed in 2024-07. Some users reported login problems in late 2025; those reports have not been verified.

## Prior Home Assistant integrations

All of these use the **old** cloud API (plain form POSTs to `/api/Admin/Login`, `/api/CustomData/QueryUserDevice`, `/api/Custom/UpdateDeviceConfig`) and all are cloud-polling. None is maintained for the post-2024 backend, which reportedly returns stale data on the old endpoints.

| Project | Status | Notes |
|---|---|---|
| dalinicus/homeassistant-aerogarden | Permanently broken by the new API; removed from the HACS default list in 2025 | Offered to be revived if someone documents the new API |
| jacobdonenfeld/homeassistant-aerogarden | Only dependency-bot updates | Light on/off and binary sensors only. An open issue asks for local socket control; no result |
| ksheumaker/homeassistant-aerogarden | Abandoned (author no longer owns a garden) | Derived from the 2017 forum work |
| epotex/hagarden and the 2017 community thread | Abandoned | Origin of the legacy API knowledge |
| eskibars/aerogarden-tools | Not checked | Python client: login, update, light toggle |
| caseypugh/homebridge-aerogarden | Not checked | Homebridge plugin, light toggle only |
| sionide21/ha-aerogarden-ble | Active | Stem grow light only, over Bluetooth LE. Local. Wi-Fi gardens are not supported |
| ethanfritzt/aerogarden | Active hobby project | Sprout (no Wi-Fi) driven by an ESP32 over MQTT |
| c99koder/m5stickc-aerogarden | Hobby project | ESPHome sensor add-on for a Sprout |

The legacy integrations expose a light on/off switch, pump and low-water binary sensors, and nutrient/days-planted sensors. None offers dimming or pump control.

## Community traffic analysis

A blog post by **vagelim** (blog.evangelosm.com) describes an early analysis of a Bounty garden:

- The garden was run through a capture access point on a Raspberry Pi.
- It looked up `app1.aerogarden.com`, then made an unencrypted HTTP request to that host, then opened a websocket carrying commands to the device, with encoded replies.
- The author pointed `app1.aerogarden.com` at a local nginx server through the access point's hosts file, and the post ends with "to be continued". No follow-up was found.

This is the only public work on the garden-to-cloud link. The post is undated and describes a different generation of hardware or firmware than the TLS behaviour observed today.

A 2023 forum thread notes the router shows a new device when the garden joins, even when the garden reports a failure, and that the garden remembers the last network. Several 2020-2024 forum and Reddit threads ask for local control; none published results.

## Our analysis

### Apps analysed

| App | Package | Version | Technology |
|---|---|---|---|
| New app | `com.aerogarden.app` | 2.1.4 | Flutter (Dart AOT), analysed through a disassembly of the compiled library and bundled assets |
| Old app | `com.intretech.bounty` | 1.6.16 | Java, analysed through decompiled sources |

### Key findings

1. The new cloud is one REST API (`https://app5.aerogarden.com/v1/...`) plus Firebase for live state mirroring. There is no MQTT, websocket or firmware endpoint in the app.
2. Authentication is a JWT carried in a custom `x-ping-access-token` header, with refresh-token support.
3. All control is `PUT v1/devices/{mac}` with a small JSON body. All status is `GET v1/devices` or the Firestore listener.
4. A garden is identified by its MAC address. The claim code is `6272` plus the MAC in hex, typed or scanned from the garden's touchscreen.
5. The new app never talks to a Bounty Elite on the LAN. The only LAN socket code is the Farm light lift (TCP 8080, `C5` frames) and the SoftAP set-up of older Harvest models.
6. Light and pump schedules use decimal string encodings in the new API (`HHMMHHMM`, `{on:03}{off:03}`), versus hex in the old API.
7. The old app's Wi-Fi gardens were controlled only through the cloud; its `C5` socket frames are unused code there.
8. The garden-to-cloud protocol appears in neither app. It is the main unknown.
9. The 2.1.4 APK contains no network security configuration, bundled certificates or pinning package. An earlier community report of a failed traffic-inspection attempt is consistent with Android's default of not trusting user-installed CAs in apps. This does not matter for a local integration, which does not need the official app.
10. The old app disables TLS validation in its HTTP client and contains an expired (2021) certificate that is never applied.
11. No firmware or update endpoint exists in either app for Wi-Fi gardens. Firmware changes therefore travel over the garden-to-cloud link.

### Traffic observation

Observed on the owner's own network, for a Bounty Elite:

- The garden resolves `app5.aerogarden.com` and connects to it on **TCP port 8443 using TLS**.
- It retrieves a **CA certificate over plain HTTP** from the same service.
- It sends a **heartbeat every 2 seconds** and **reconnects automatically** if the connection drops.
- The application data inside the TLS connection has not yet been decoded.

## Local control approach

The approach is the same pattern other projects use for cloud-connected devices (see the table below):

1. **DNS.** The local DNS server resolves the garden's cloud hostname to a machine on the LAN. Nothing is changed on the garden.
2. **Certificates.** The garden connects over TLS and fetches a CA certificate over HTTP. The local server serves its own CA certificate on port 80 and presents a server certificate signed by that CA on port 8443. Whether the garden accepts this depends on how it validates the chain; that is to be tested.
3. **Protocol.** Once the garden connects, the local server needs to speak the application protocol. It can be learned by logging the bytes the garden sends and observing how it reacts to what the server returns.
4. **Local API.** The server exposes state and controls to Home Assistant.

If the garden turns out to validate the connection in a way that cannot be satisfied locally, the fallbacks are the cloud-based path (mirroring the phone app's REST API from a Home Assistant integration; documented in the protocol reference) and, as a last resort, hardware-level options. Hardware work is deliberately out of scope for now.

Additional notes:

- Re-pointing DNS is reversible by deleting the rule.
- Firmware updates can break reverse-engineered protocols. Once local control works, the garden's update path should be left unreachable (as the iRobot community recommends), so that updates arrive only when the owner chooses.
- Plan order from the research: passive observation first, then the local server, then optionally a cloud-API integration as a fallback.

## Techniques from other projects

| Project | Device family | Technique | Relevance |
|---|---|---|---|
| **Bumper** | Ecovacs robots | Self-hosted server implementing the vendor cloud (HTTPS API, MQTT, XMPP). Local DNS points vendor hostnames at the server; the robot trusts the server's certificate. Newer firmware pins certificates, which requires replacing CA files on the robot | **Closest model.** Same DNS-plus-local-server pattern, with the same certificate question |
| **LocalTuya / TinyTuya / tuya-local** | Tuya devices | Devices expose a LAN TCP port (6668) with AES keyed by a per-device local key fetched once from the cloud | Applies only if the garden has a keyed LAN protocol (unknown) |
| **msmart-ng** | Midea air conditioners | LAN TCP control; a token and key are fetched once from the vendor cloud. Protocol learned from vendor plugins inside the vendor app | Lesson: the vendor app is the protocol spec. Used here for the `C5` frames |
| **python-kasa** | TP-Link Kasa/Tapo | UDP discovery then local encrypted TCP/HTTP; protocol learned by capturing app-to-device traffic | Lesson: capture traffic during a local command. The garden's app does not use a local path for set-up |
| **Valetudo** | Roborock and others | Replaces the vendor cloud client with a local web UI and MQTT after installing custom firmware | Requires firmware access; out of scope |
| **dorita980 / roombapy** | iRobot | Robot runs local MQTT over TLS; credentials fetched from the robot itself or the cloud. Advice: block internet access so firmware updates do not break the integration | Lesson: block the update path once local control works |
| python-miio | Xiaomi | Per-device token over UDP 54321, fetched once from the cloud | Token model; no token concept seen for the garden |
| python-broadlink | Broadlink | Local protocol; provisioning sends Wi-Fi credentials to the device in AP mode | Similar to the garden's SoftAP provisioning for older models |
| Govee LAN API, Bambu Lab LAN mode | Govee, Bambu | Vendor-provided local modes enabled in the app or on the device screen | A hidden local mode on the garden's touchscreen is unlikely but cheap to check |
| tuya-cloudcutter | Tuya (Beken, Realtek) | Firmware-level detachment from the cloud on specific chips | Wrong chips and cloud; not applicable |

## Hardware notes

- Wi-Fi gardens use a Marvell 88MC200 with an 88W8801 Wi-Fi chip (older) or a MediaTek MT7682 (later), per FCC filings and the old app's provisioning code. Marvell's SDK is largely open source, and a community tool exists for converting Marvell 88MW30x firmware images; it has not been verified against the 88MC200.
- No firmware dump of an AeroGarden has been published, and no UART protocol between a Wi-Fi module and a main MCU is documented. They may be one chip.
- No reflash project exists for a Wi-Fi garden. ESP32 replacement of the controller has been done for the non-Wi-Fi Sprout only.

## Sources

Public pages used for this survey: the Scotts Miracle-Gro announcements of the new app and of the brand's return; coverage by The Verge, Ars Technica and Wired of the 2024 announcement; the AeroGarden Addicts forum threads on the 2023 outage and 2024 app launch; the HACS issue on the removal of the dalinicus integration; the repositories listed above; FCC filings by grantee `2AJNO`; the TechInfoDepot teardown entry for the Harvest Elite; and the vagelim blog post.
