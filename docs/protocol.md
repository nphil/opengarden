# OpenGarden protocol reference

This document collects what is known about how AeroGarden Wi-Fi gardens, the official apps and the vendor's cloud service exchange data. It is derived from static analysis of the two official Android apps, public community work, and observation of a garden's connection behaviour on the owner's own network.

Evidence labels used below:

- **[APP]** found by static analysis of the official Android app (new app 2.1.4 or old app 1.6.16)
- **[OBS]** observed on the owner's own network
- **[INF]** inference, not proven

All MAC addresses in this document are placeholders (`AA:BB:CC:DD:EE:FF`) and LAN addresses are generic (`192.168.1.x`). The one real fixed address is `192.168.10.1`, the garden's own SoftAP address during Wi-Fi provisioning.

Contents:

1. [Cloud REST API](#cloud-rest-api)
2. [Device state model](#device-state-model)
3. [String encodings](#string-encodings)
4. [Garden-to-cloud connection](#garden-to-cloud-connection)
5. [LAN TCP port 8080](#lan-tcp-port-8080)
6. [Wi-Fi provisioning (SoftAP)](#wi-fi-provisioning-softap)
7. [Old cloud API](#old-cloud-api)
8. [BLE grow light protocol](#ble-grow-light-protocol)
9. [Hardware](#hardware)
10. [Open questions](#open-questions)

There are two separate communication links, and the apps only show the first:

| Link | Description | Status |
|---|---|---|
| A | Phone app to cloud (REST `v1/*` plus a Firebase listener for live state) | Documented in sections 1-3 |
| B | Garden to cloud (what the garden itself sends and receives) | Connection behaviour known, application protocol **not decoded** (section 4) |

---

## Cloud REST API

Used by the current official app (package `com.aerogarden.app` 2.1.4, a Flutter application). **[APP]**

### Base URLs

| Environment | Base URL |
|---|---|
| production | `https://app5.aerogarden.com/` |
| staging | `https://app5-rc.aerogarden.com/` |
| development | `https://app5-dev.aerogarden.com/` |

All paths below are relative to the base URL. Request and response bodies are JSON (`content-type: application/json`).

The app also uses Firebase (Authentication, Firestore, Cloud Messaging, Remote Config). Firebase is not part of the garden control path; see [Live state](#live-state-firestore).

### Headers

| Header | Value |
|---|---|
| `x-ping-access-token` | The access token (a JWT) returned by login. **Not** an `Authorization: Bearer` header. |
| `x-trans-id` | A random UUID v4, one per request |
| `x-app-version` | The app version string |

Login and refresh calls are sent without the token header.

### Authentication flow

1. `POST v1/users/login/site` with e-mail and password returns tokens.
2. Every later request carries `x-ping-access-token: <access_token>`.
3. The app decodes the JWT to read its expiry. On a `401` it calls `v1/users/refresh-token` with the stored refresh token, stores the new tokens and retries the request once. If the refresh fails the user is logged out.
4. After login the app calls `GET v1/users/firebase-token` and signs in to Firebase with the returned custom token. This is only needed for the live-state listener.

| Method and path | Request | Response |
|---|---|---|
| `POST v1/users/login/site` | `{"email", "password"}` | login object (below) |
| `POST v1/users/send-otp` | `{"email"}` | `{"email", "sessionId"}` |
| `POST v1/users/login-otp` | `{"otp", "sessionId"}` | login object |
| `POST v1/users/native-social-login` | `{"provider": "google", "idToken"}` | login object **[INF]** |
| `GET v1/users/login/idp?provider=apple` | query only | `{"redirectUrl", "sessionId"}` |
| `GET v1/users/oauth-return?continueToken=..&sessionId=..` | query only (`accept: application/json`) | login object **[INF]** |
| `POST v1/users/reset-password` | `{"email"}` | ok |
| `POST v1/users/register` | `{"email", "password", "firstName", "lastName"}` | `{"authType", "creationDate", "customerId", "customerNo", "email", "enabled", "firstName", "lastModified", "lastName", "login"}` |
| `POST v1/users/refresh-token` | `{"refreshToken"}` | `{"access_token", "refresh_token", "firebase_token"}` |
| `GET v1/users/firebase-token` | none (token header) | `{"customToken"}` |

The login object contains: `usid`, `access_token`, `id_token`, `refresh_token`, `expires_in`, `refresh_token_expires_in`, `token_type`, `customer_id`, `enc_user_id`, `idp_access_token`, `idp_refresh_token`, `email`.

There is no account-deletion endpoint in the app's user resource.

### Error contract

Error bodies are JSON `{"message": "<string>"}` and the app branches on the message text:

| Status | Message | Meaning |
|---|---|---|
| 400 | last word is an `ApiModel` name (e.g. `...BountyElite`) | wrong garden model chosen when adding a device |
| 401 | `Invalid email and/or password.` | bad credentials (any other 401 triggers a token refresh) |
| 401 | `Missing access token` | no token header (observed on an unauthenticated request) |
| 403 | `Device has already been added to another user.` | device claimed by another account |
| 403 | `Account is locked` | |
| 409 | `Device has already been added to this user.` | |
| 409 | `Account already registered.` | |
| 409 | `Password reset required` | |

### Device endpoints

`{id}` is the garden's MAC address as returned by the server in `macAddress`. **[APP]**

| Method and path | Request body or query | Response |
|---|---|---|
| `GET v1/devices?metadata=true&light=true` | query | list of device state objects |
| `GET v1/devices/{id}?alarm=true` | query | list of device state objects; the app uses the entry whose `side` is `"Right"` **[INF]** |
| `POST v1/devices` | `{"deviceID", "deviceModel", "metadata": {"name"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (name) | `{"metadata": {"name"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (image) | `{"metadata": {"image"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (alarm) | `{"side", "alarm": {"enabled", "cycle"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (nutrient) | `{"side", "nutrition": {"cycle", "reminder", "reminderFlag"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (pump) | `{"side", "pump": {"status", "cycle", "shortageReminder", "pumpSafetyMode", "performTest", "drain"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (light) | `{"side", "light": {"status", "cycle", "temporaryStatus", "dimming", "sunrise", "sunset", "sunriseSunsetEnabled", "vacationModeEnabled"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (quick plant) | `{"side", "plant": {"plantType", "daysPlanted": 0}, "light": {"cycle"}, "nutrition": {"reminder", "cycle": 28}, "pump": {"cycle", "pumpSafetyMode": false}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}` (clock) | `{"clock": {"clock", "timezone"}}` | `{"macAddress"}` |
| `PUT v1/devices/{id}/environment` | `{"environment": ...}` (value type not decoded) | `{"macAddress"}` |
| `PUT v1/devices/sync/time` | `{"clock", "timezone"}` (applies to all gardens) | ok |
| `GET v1/devices/notifications` | none | `{"waterNotificationEnabled", "nutrientNotificationEnabled"}` |
| `PUT v1/devices/notifications` | `{"waterNotificationEnabled", "nutrientNotificationEnabled", "tipNotificationEnabled"}` | ok |
| `DELETE v1/devices/{id}` | none | ok |

Notes:

- The update response contains one field, `macAddress`.
- The app **always sends every key of the sub-object**, using JSON `null` for values the user did not change. A server must treat `null` as "leave unchanged". **[APP][INF]**
- `side` is `"Left"` or `"Right"`. What a single-zone garden sends is unknown (possibly null). **[INF]**
- Where each setting lives:
  - Light on/off, dimming, schedule, sunrise/sunset ramp, vacation mode: the `light` object.
  - Pump on/off, schedule, pump test (`performTest`), drain, low-water safety (`pumpSafetyMode`): the `pump` object.
  - Plant-food timer: `nutrition.cycle` (days; quick plant uses 28), `nutrition.reminder`, `nutrition.reminderFlag`.
  - Audio alert: `alarm.enabled`, `alarm.cycle`.
- The app has no call that starts or checks a garden firmware update.

### Claiming a garden

The garden shows a scan code on its touchscreen (Wi-Fi options, scan code). The user scans it or types it. The app posts it unchanged:

```
POST v1/devices
{"deviceID": "<16 hex characters>", "deviceModel": "BountyElite", "metadata": {"name": "Kitchen"}}
-> {"macAddress": "AA:BB:CC:DD:EE:FF"}
```

The code format, from the old app, is 16 hex characters: the literal `6272` followed by the 12 hex digits of the MAC. The MAC is then written with `:` after every 2 characters. For example `6272AABBCCDDEEFF` becomes `AA:BB:CC:DD:EE:FF`. The server parses this; the new app does no substring handling. The server also needs to know whether the garden is online (the old API returned code `-1` for offline).

### Other endpoints (not garden control)

| Method and path | Body or query | Response |
|---|---|---|
| `POST v1/images` | multipart `{type: "DeviceImage", file: jpeg}` | `{"id"}` |
| `GET v1/images/{id}` | | `{"url"}` |
| `GET v1/images?limit=15&page=N` | | `{"message", "data": [{"id","fileSize","type","macAddress","createDate","deleteDate"}]}` |
| `DELETE v1/images/{id}` | | ok |
| `GET v1/journal/{deviceId}` | `page`, `limit`, `side` | list of journal entries |
| `POST v1/journal/{deviceId}` | `{"title", "message", "side", "photoId"}` | ok |
| `PUT v1/journal/{deviceId}/{entryId}` | `{"title", "message", "photoId"}` | ok |
| `DELETE v1/journal/{deviceId}/{entryId}` | | ok |
| `GET v1/content?contentType=guide&limit=&skip=` | | `{"items": [...]}` (guides) |
| `POST v1/mobile-devices` | `{"registrationToken", "type", "model"}` | ok |
| `DELETE v1/mobile-devices/{id}` | | ok |
| `POST v1/contact-us` | contact form fields | ok |

Journal entry fields: `createDate, id, macAddress, side, type, updateDate, deletedDate, description, imageId, quickPlantType, title, value, oldValue`. Entry `type` values: `LightScheduleUpdated`, `LightOnDurationUpdated`, `LightIntensityUpdated`, `SunriseSettingOnUpdated`, `SunriseSettingOffUpdated`, `SunsetSettingOnUpdated`, `SunsetSettingOffUpdated`, `SunriseDurationUpdated`, `SunsetDurationUpdated`, `PlantFoodCycleUpdated`, `DaysLeftinCurrentCycleUpdated`, `UserJournalEntry`, `QuickPlant`, `PowerOutage`, `PlantFoodAdded`, `SunriseSunsetSettingUpdated`, `PumpCycleUpdated`, `Other`. The service appears to add an automatic entry whenever a setting changes or power returns. **[INF]**

### Live state (Firestore)

The app loads the device list over REST and then listens to a Firestore collection to keep it fresh. **[APP]**

- Path: `ais-aerogarden-users/{userId}/devices` (the user id is the Firebase uid minted by the vendor's backend).
- Each document decodes with the same model as one element of `GET v1/devices`.
- Commands never go through Firestore; they use the REST `PUT` calls above.
- The garden itself most likely does not talk to Firestore; the backend mirrors telemetry into it. **[INF]**

### Observed behaviour of the hosts

Observed with unauthenticated requests on 2026-11-22:

| Request | Result |
|---|---|
| `GET https://app5.aerogarden.com/` | 200, an HTML "Link Account" page |
| `GET https://app5.aerogarden.com/v1/devices` (no token) | 401 `{"message":"Missing access token","error":"Unauthorized","statusCode":401}` |
| `GET http://app1.aerogarden.com/` (plain HTTP, port 80) | 200, same HTML page |
| `GET https://app3.aerogarden.com:8443/` | 200, same HTML page |
| `GET https://app4.aerogarden.com/` | 200 `text/plain`, a Cloudflare Worker status line |
| DNS | `app1`, `app3`, `app4`, `app5`, `app5-rc`, `app5-dev` resolve to Cloudflare addresses; `app2`, `ws`, `mqtt`, `api` do not resolve |

The `app1`, `app3` and `app5` hosts appear to be fronted by one Express/Node server. **[INF]**

---

## Device state model

One garden is represented by this object (the element of `GET v1/devices` and of a Firestore device document). **[APP]**

Top level fields: `macAddress, model, side, isOnline, alarm, clock, light, metadata, network, nutrition, plant, pump, version`.

| Object | Fields (type) |
|---|---|
| top level | `macAddress` string, `model` ApiModel, `side` ApiSide, `isOnline` bool |
| `alarm` | `enabled` bool, `status` bool, `cycle` string |
| `clock` | `clock` string, `timezone` int |
| `light` | `status` bool, `cycle` string, `dimming` int, `sunrise` int, `sunset` int, `sunriseSunsetEnabled` bool, `vacationModeEnabled` bool |
| `metadata` | all strings: `name, description, imageUrl, createdAt, updatedAt, pairedDate` |
| `network` | all strings: `ssid, deviceIpAddress, serverIpAddress, routerMacAddress, routerIpAddress` |
| `nutrition` | `cycle` int, `reminder` int, `reminderFlag` bool, `shortage` bool |
| `plant` | `plantType` enum, `totalDaysUntilHarvest` int, `daysPlanted` int |
| `pump` | `status` bool, `cycle` string, `waterLevel` enum, `shortage` bool, `shortageReminder` bool, `pumpSafetyMode` bool, `drain` bool |
| `version` | `swVersion, hwVersion, bwVersion` (strings) |

Not present in the model, so the cloud cannot show them: water temperature, humidity, light-hours counter, pump run counters.

The `network` object shows that the garden reports its SSID, LAN address and router details upward. `serverIpAddress` may identify the server the garden is connected to. **[INF]**

### Enums (wire strings)

- **ApiModel**: `Unknown, LegacyBounty, LegacyHarvest, LegacyFarm, LegacyFarmSmall, Bounty, BountyElite, Farm24, Farm12, TabletopGrowlight, StemGrowLight, TrioGrowLight`. A Bounty Elite is `BountyElite`.
- **App device type to ApiModel**: stem to `StemGrowLight`; tabletop to `TabletopGrowlight`; trio to `TrioGrowLight`; bounty to `Bounty`; bountyElite to `BountyElite`; bountyClassic to `LegacyBounty`; farm12 and farm12xl to `Farm12`; farm24basic, farm24plus, farm24xl to `Farm24`; farmClassic to `LegacyFarm`; farmPlus to `LegacyFarmSmall`; harvestClassic to `LegacyHarvest`.
- **ApiSide**: `Left`, `Right`.
- **ApiWaterLevel**: `Low`, `Medium`, `High`.
- **ApiPlantType**: `Herbs, Tomatoes, Lettuce, Peppers, Flowers, SeedStarter, GrowBowl, Custom, MicroGreens`. The app's quick-plant presets carry pump minutes on/off: Herbs, Tomatoes, Lettuce, Peppers, Flowers and SeedStarter use 60/660 (a 12-hour cycle); GrowBowl uses 2/500; MicroGreens and Custom use 5/55. **[INF]**
- **Provisioning type**: Wi-Fi for the Bounty Elite and Farms; Bluetooth for the Stem, Tabletop and Trio grow lights.

### Restore-defaults values

What the app sends for "restore defaults" on a Wi-Fi garden: light status true, on 16:00, off 22:00, `temporaryStatus` false, `dimming` 100, `sunrise` 60, `sunset` 60, `sunriseSunsetEnabled` false, `vacationModeEnabled` false; pump status true, 10 minutes on, 50 minutes off, `performTest` true, `pumpSafetyMode` true, `shortageReminder` true, `drain` true. Then the clock is synced. The 60/60 values look like ramp minutes and `dimming` appears to be 0-100. **[INF]**

---

## String encodings

These matter most for any integration, because the formats differ from the old API.

### Light cycle

`light.cycle` is 8 **decimal** digits, `HHMMHHMM`: on-hour, on-minute, off-hour, off-minute (clock times). Default `00000000`.

- `07301830` means on at 07:30, off at 18:30.
- Decode: `int(s[0:2])`, `int(s[2:4])`, `int(s[4:6])`, `int(s[6:8])`.
- Encode: each value zero-padded to 2 digits, on pair first.
- The schedule editor passes the "light on" time first, so despite the parameter names in the app code, the first pair is the on time.
- Open point: "restore defaults" sends 16:00/22:00 and quick plant sends `<X><Y>0000`, which are not obviously sensible daily light hours, so the meaning of the first pair is not fully proven. See [open questions](#open-questions).

### Pump cycle

`pump.cycle` is 6 **decimal** digits, `{minutesOn:03}{minutesOff:03}`. Default `000000`.

- `010050` means 10 minutes on, 50 minutes off.
- Decode: `substring(0,3)` and `substring(3)`.

### Clock

- `clock.clock` is the local time formatted `HHmmss` (for example `183045`).
- `clock.timezone` is the local UTC offset in whole hours, truncated.

### Old API encodings (for comparison)

The old API used **hex** pairs: `lightCycle` is 8 hex characters `onHH onMM offHH offMM` where each pair is one hex byte (07:30 to 18:30 is `071E121E`); `pumpCycle` is two 4-hex-digit values; `clock` is hex with the first 4 characters as `HHMM`.

---

## Garden-to-cloud connection

This is link B. The garden does not use the phone app's REST API. Its connection behaviour, **[OBS]** on the owner's network:

| Property | Value |
|---|---|
| Hostname | `app5.aerogarden.com` |
| Port | 8443 |
| Transport | TLS |
| CA certificate | The garden fetches a CA certificate over **plain HTTP** (port 80) |
| Heartbeat | Every 2 seconds |
| Reconnect | Automatic after the connection drops |

What this means for a local server:

- DNS for `app5.aerogarden.com`, as seen by the garden, must resolve to the local server.
- The local server needs to answer plain HTTP on port 80 for the CA certificate request and accept TLS on port 8443 with a certificate that chains to that CA.
- Whether the garden validates the server certificate against the fetched CA, and what else it checks (for example the host name), is part of what the bridge work will determine.

**The application protocol inside the TLS connection is not yet decoded.** Neither official app contains it: the apps only use the REST API (link A). Unknown: message framing, authentication, message set, how state is reported, how commands are delivered, and the firmware update flow.

Historical clue: a community write-up of an older Bounty garden reported an unencrypted HTTP request to `app1.aerogarden.com` followed by a websocket carrying commands to the device, with encoded replies. The current behaviour (TLS on 8443) differs, but the message layer may be related. **[INF]**

---
## CA trust file format and Phase 1 bridge results

**[OBS]** A bridge was stood up on the owner's LAN: a local DNS record pointed
`app5.aerogarden.com` at it, it answered the CA request on port 80, and it
accepted TLS on port 8443 with a self-signed CA and a matching server
certificate. The garden reached the bridge and fetched the CA, but **rejected a
replacement CA** and never progressed to the TLS connection. When the bridge
served the original vendor CA bytes back verbatim, the garden accepted them —
so the DNS, the HTTP exchange, and the response shape are all correct, and the
sole blocker is the format of the CA file itself.

### The CA file has a 32-byte header

`GET /api/Admin/GetCA?aioGuid=<MAC>&fwModule=kfw` returns the JSON described
above, pointing at `GET /api/Admin/GetFile?fileName=CA-KFW-2041-DIGI-G2.bin`.
That file is **not** a bare PEM. It is a 32-byte binary header followed by the
PEM certificate (DigiCert Global Root G2):

| Offset | Bytes (kfw sample) | Meaning |
|---|---|---|
| 0-3   | `24 05 00 00` | u32 little-endian = 1316, the PEM payload length |
| 4-7   | `fe ca 58 03` | computed field A (see below) |
| 8-11  | `4b 46 57 00` | ASCII `KFW\0`, the module name (matches `fwModule=`) |
| 12-15 | `32 30 34 31` | ASCII `2041`, the version (matches `versionName` `CA-V2041`) |
| 16-19 | `8e 5d 98 00` | computed field B (see below) |
| 20-31 | `00 …`        | zero padding |

Total file size is 1348 bytes (32 + 1316), matching `pkgSize` in the JSON.

### The two computed fields block CA replacement

Requesting the same endpoint with a different `fwModule` gives a second sample
that wraps the identical PEM:

| Module | Byte 8 | Field A (4-7) | Field B (16-19) |
|---|---|---|---|
| `kfw` | `4b` (`K`) | `fe ca 58 03` | `8e 5d 98 00` |
| `mfw` | `4d` (`M`) | `fe ca 58 03` | `e4 4e da 04` |

From the two samples:

- **Field A (bytes 4-7)** is unchanged when only the module name changes, so it
  depends on the PEM payload only.
- **Field B (bytes 16-19)** changes with the module name, so it depends on the
  header fields (at least the module name), and presumably the PEM as well.

When a bridge serves its own CA with these two fields copied verbatim from the
vendor file (correct module, version, and size), the garden still rejects it —
confirming both fields are content-dependent and must be recomputed for a new
certificate.

Field A and Field B were tested against a wide set of algorithms over the PEM,
the DER, the base64 body, and header+payload combinations: CRC-32 (standard and
the Marvell no-preset/no-final-invert variant, plus several polynomial and
reflection variants), CRC-16 (CCITT, IBM, MODBUS, XMODEM, DNP, MAXIM, USB),
CRC-24 (OpenPGP), Adler-32, Fletcher-16/32, negated byte sums, XOR,
DJB2/SDBM/FNV-1a/Jenkins/Murmur mixing, and MD5/SHA-1/SHA-256 truncations.
**None matched.** The algorithm is not yet identified.

The two official apps do **not** compute this header. Static analysis of the
legacy app's grow-light updater shows it reads the 32-byte header and forwards
it unchanged, and uses one-byte sums only for its own Bluetooth framing. The
header is produced server-side and verified by the garden firmware. **[APP]**

### Firmware is delivered inside the TLS connection

The touchscreen `Settings → Wi-Fi → Software Update` performs the firmware check
over the TLS link (port 8443), not over the plain-HTTP GetFile endpoint. On an
up-to-date unit it reports "up to date" and downloads nothing, so the firmware
image cannot be captured from the network this way. The GetCA/GetFile endpoints
over plain HTTP serve only CA files (`deviceTypeValue` `CA`); only `fwModule`
values `kfw` and `mfw` return data. Recovering the header algorithm from the
firmware therefore requires reading the device flash directly — which means
opening the base, and the Marvell part may store code in internal,
read-protected flash. **[OBS]**

### The connection is TLS regardless of the port (no downgrade)

The `GetCA` response (plain HTTP, fully attacker-controlled) dictates
`websocketHost` and `websocketPort`. A test served the garden the accepted
vendor CA and set `websocketPort` to a plain, non-TLS port with a byte logger.
The garden **obeyed the redirect** — it connected to the named port — but it
still opened a **TLS ClientHello** there (`16 03 01 …`, offering the RSA
key-exchange ciphers seen in the original capture). So the garden chooses TLS
from firmware, not from the port number; pointing it at a plain port does not
downgrade it. We control where the garden connects, but not whether it uses
TLS, so the server-certificate requirement (and the CA-file blocker above)
stands. **[OBS]**

### Next step for a local bridge

The one remaining blocker to a local cloud replacement is the CA-file header
algorithm (fields A and B). Candidate ways to recover it: a flash/debug read of
the garden's controller board, a leaked or published server-side tool, or more
`CA-*.bin` samples that constrain the algorithm. Until then, the local bridge
cannot complete the TLS handshake, and the documented cloud REST API (link A) is
the only working control path.

### Observed unit

One Bounty Elite, touchscreen `Settings → Garden Status` version
`KFW-V0.47 / SW-V1.02`. `Settings → Wi-Fi` menu options: Connect to Wi-Fi, Scan
Code, Software Update, Unpair Garden, Troubleshooting, Disable WiFi. **[OBS]**


## LAN TCP port 8080

The only live LAN control path in the new app is the light lift of Farm-series gardens. **[APP]**

### Frame format

```
C5 | len | cmdHi cmdLo | plen | hdrChk | payload... | pChk
```

| Field | Meaning |
|---|---|
| `C5` | start byte |
| `len` | total frame length minus 1 |
| `cmdHi cmdLo` | 16-bit command id, big endian |
| `plen` | payload length |
| `hdrChk` | `(-(C5 + len + cmdHi + cmdLo + plen)) & 0xFF` |
| `payload` | `plen` bytes |
| `pChk` | `(-sum(payload)) & 0xFF` |

### Known commands

| Command | Frame | Notes |
|---|---|---|
| `0x003D` lift, side 0 up | `C5 08 00 3D 02 F4 00 01 FF` | payload = (side, direction); direction 1 up, 2 down |
| `0x003D` lift, side 0 down | `C5 08 00 3D 02 F4 00 02 FE` | |
| `0x003D` lift, side 1 up | `C5 08 00 3D 02 F4 01 01 FE` | |
| `0x003D` lift, side 1 down | `C5 08 00 3D 02 F4 01 02 FD` | |
| `0x00FF` disconnect | | Disconnect command id; in practice **closing the TCP socket is what stops the lift** (press-and-hold) |

Usage by the app: open a TCP connection to the garden's LAN address (taken from the cloud state `network.deviceIpAddress`, 5 second connect timeout), write the frame, and close the socket to stop. A connect-then-disconnect is also used as a reachability probe.

Only the seven Farm models use this in the app. The Bounty, Bounty Elite, Bounty Classic and Harvest do not. On a Bounty Elite, port 8080 **does accept a TCP connection** but returns nothing to a `C5` lift frame, to other `C5` command ids, or to a plain read — consistent with a light-lift server whose only effect is physical (a motor) with no network reply, on a unit that has no lift. Whether it exposes any other local interface is unknown. **[OBS]**

---

## Wi-Fi provisioning (SoftAP)

Older models (Harvest family) are provisioned by the phone app joining the garden's own access point. Bounty and Farm models are provisioned on the touchscreen instead (see [Claiming a garden](#claiming-a-garden)).

Hold OK for 3-5 seconds on the garden to raise an open access point named `Harvest...<last 4 MAC hex digits>`. The app joins it without a password. The garden's address is `192.168.10.1`. Hotspot discovery matches SSIDs that start with `Harvest` or contain `MTK`. **[APP]**

### Marvell variant (HTTP)

```
POST http://192.168.10.1/sys/network
Content-Type: application/json

{"ssid": "ExampleNetwork", "security": 4, "channel": 0, "key": "example-password", "ip": 1}
```

- `security`: WPA2 = 4, WPA = 3, WEP = 1, anything else = 0.
- Success when the response body contains `success`.
- The new app sends a reduced body `{"ssid","security","key"}`.
- Unused helper in the old app: `GET http://192.168.10.1/sys/` returns `connection.station.{configured,status}`.

### MediaTek variant (TCP, SSID contains `MTK`)

Open TCP to `192.168.10.1:8080` and send ASCII text:

```
ssid,password,5,,1
```

A reply of `1` means success. The old app uses a 10 second timeout, 5 retries with 3 seconds between them, and a 128-byte read every 50 ms.

---

## Old cloud API

Used by the old app (`com.intretech.bounty`) and by every community Home Assistant integration. Since the new backend launched in 2024-06 it reportedly returns stale data. **[APP]**

- Hosts seen: `https://app3.aerogarden.com:8443` (the old app's host), `https://app4.aerogarden.com`, and older hard-coded addresses.
- All requests are `POST` with `Content-Type: application/x-www-form-urlencoded`. There is no token; the "session" is a numeric `userID` returned by login.
- The old app polls every 10 s; community integrations poll every 30 s.

| Endpoint | Form fields | Result |
|---|---|---|
| `/api/Admin/Login` | `mail`, `userPwd` | `{"code": N}`; `code > 0` is the userID; `-2` account not found, `-4` bad password |
| `/api/CustomData/QueryUserDevice` | `userID` | JSON list, one entry per garden (per side for dual-side Farms) |
| `/api/Custom/UpdateDeviceConfig` | `userID`, `airGuid`, `chooseGarden`, `plantConfig` (JSON string) | `{"code": 1}` on success |
| `/api/Custom/AddUserDevice` | `userID`, `airGuid`, `deviceID` (raw code) | `{code, msg, sugName}`; `>0` ok, `-1` offline, `-2` invalid number, `-3` already bound |
| `/api/Custom/DeleteUserDevice` | | |
| `/api/Custom/QueryDeviceOnline` | `userID` or `airGuid` | online state |
| `/api/Custom/InitDeviceConfig` | `airGuid`, `plantConfig`, `isSync`, `chooseGarden` | |
| `/api/CustomData/QueryDeviceStatus` | `userID`, `airGuid` | |
| `/api/CustomData/BountyWifiLastVersion` | `deviceType`, `Version`, `airGuid` | `{versionName, versionCode, fw_url, pkgSize, deviceTypeValue, bwVersion}` (metadata only) |
| `/api/Admin/GetVerification`, `Register`, `ChangePwd`, `RetrievePwd`, `GetServerDomain` | account management | |

Old state fields (`PlantConfig`): `airGuid` (the MAC), `chooseGarden` (0 left, 1 right), `plantedName` (base64), `plantedDay`, `lightTemp`, `lightStat` (0 means on), `lightCycle`, `lightDimming`, `pumpStat` (0 means on), `pumpCycle`, `pumpLevel` (low-water flag), `pumpHydro`, `pumpDrain`, `pumpDrainState`, `nutriCycle`, `nutriRemindDay`, `nutriStatus`, `clock`, `hwVersion`, `swVersion`, `bwVersion`, `deviceIP`, `vacationMode`, `sunRise`, `sunSet`, `sunFunSwitch`, `audioAlarmCycle`, `audioAlarmStat`, `msgType`.

Control uses partial JSON, for example the light toggle sends `{"lightTemp": <int>}`; light dimming sends `{"lightDimming": N}`; farm lift sends `{"upCtl", "downCtl", "chooseGarden"}`; pump drain sends `{"pumpDrain", "pumpDrainState", "chooseGarden"}`. Push `msgType` values: 0 status, 1 bound or low water, 2 unbound or low nutrient, 3 online, 4 offline, 5 tips.

Mapping to the new API: field names differ (`lightCycle` to `light.cycle`, `pumpCycle` to `pump.cycle`) and the cycle encodings differ (hex to decimal).

---

## BLE grow light protocol

Included for completeness. It applies to the Stem, Tabletop and Trio grow lights, **not** to Wi-Fi gardens. **[APP]**

| Item | Value |
|---|---|
| GATT service | `0xAE3A` (advertised service `0xAF30`) |
| Write characteristic | `0xAE3B` |
| Notify characteristic | `0xAE3C` |
| Inner frame | `C5 | len (u16 LE) | cmd | hdrChk | payload | pChk`, where `hdrChk = (C5 + lenLo + lenHi + cmd) & 0xFF` and `pChk = sum(payload) & 0xFF` (not negated) |
| Outer frame | `5A | len | isEncrypt | body` from app to device; `A5` back |
| Encryption | AES-128-CBC with PKCS5 padding; key is the ASCII text `GrowLightBluetoo` (a fixed key shared by all devices), IV `12 34 56 78 9A BC DE F0` repeated twice |
| Chunking | 20-byte chunks with 20 ms gaps |

Commands: 1 VERSION, 2 TYPE, 3 UPLOAD_INFO, 4 GET_INFO, 5 CONTROL, 6 GET_MAC, 7 UPDATE, 8 UPDATE_INFO, 9 OTA_HEAD, 10 OTA_DATA, 11 OTA_END, 12 OTA_SUCCESS.

The status payload carries: planted type, RTC seconds since midnight (3 bytes LE), light-on and sun-function flags, light on/off times, days planted (u16 LE), dimming, sunrise, sunset, season mode and permanent dimming.

An existing Home Assistant integration for the Stem grow light already uses this protocol.

---

## Hardware

- The garden electronics are built by **Xiamen Intretech**, which is also the publisher named in the old app's package (`com.intretech.bounty`). The new app is `com.aerogarden.app`.
- Wi-Fi gardens use one of two module families, according to the old app's provisioning code and public FCC filings:
  - **Marvell 88MC200** (Cortex-M3) with an **88W8801** 2.4 GHz Wi-Fi chip, on a module marked "SM008A". Seen in the Harvest Elite (FCC ID 2AJNO1006).
  - **MediaTek MT7682** (Cortex-M4 Wi-Fi SoC), in later revisions (FCC filings `2AJNO1006MTK`, `2AJNO1009MTK`, `2AJNO-MT7682`). **[INF]**
- Which chip a given Bounty Elite has depends on its build date and revision; the FCC ID on its label or the on-screen hardware version tells.
- Only 2.4 GHz Wi-Fi is supported.
- The touchscreen controller and the Wi-Fi radio may be on a single chip, in which case there is no separate serial protocol between them. **[INF]**
- No firmware image of a Wi-Fi garden is public, and none is contained in either app. The only firmware file in the old app is for a BLE grow-light MCU.

---

## Open questions

In priority order. The top blocker is now item 1.

1. **CA-file header algorithm (the main blocker).** How fields A (bytes 4-7) and
   B (bytes 16-19) of the 32-byte CA-file header are computed. Without this a
   bridge cannot present a CA the garden trusts, so the TLS connection never
   starts. See [CA trust file format](#ca-trust-file-format-and-phase-1-bridge-results).
2. **Garden-to-cloud application protocol**: framing, authentication, message
   set, state reports, command delivery, firmware update flow. Blocked on item 1,
   since the bytes only become visible once the garden accepts the bridge's CA
   and completes the TLS handshake.
3. Whether the garden pins or otherwise further validates the server certificate
   beyond chaining to the fetched CA (host name, key, etc.). Partly answered: the
   garden accepts a self-signed CA served in the vendor file's exact wrapper, so
   the CA is not pinned; the open part is what else it checks once the CA passes.
4. Port 8080 on a Bounty Elite accepts a TCP connection but returns nothing to
   `C5` frames or a plain read (see [LAN TCP port 8080](#lan-tcp-port-8080)).
   Whether it exposes any other local interface, and what Farm `C5` command ids
   exist beyond `0x003D`, is still open.
5. Meaning of the first pair of `light.cycle` (see [Light cycle](#light-cycle)); confirm against a live reading from a garden with a known schedule.
6. Units of `dimming`, `sunrise`, `sunset` (0-100 and minutes are assumed).
7. `light.status` versus `light.temporaryStatus`.
8. `alarm.cycle` format and `alarm.status` versus `alarm.enabled`.
9. `nutrition.cycle`, `nutrition.reminder` (days left?) and `reminderFlag`.
10. Body of `PUT v1/devices/{id}/environment`.
11. Whether a Bounty Elite produces one state entry or one per side, and what `side` is for it.
12. Exact error text for a wrong model (400) and for an offline garden on claim.
13. Firestore device document id and any extra fields.
14. Whether the legacy `/api/*` surface still answers on `app1` and `app3`.
15. What `network.serverIpAddress` contains.
16. Which Wi-Fi chip family each unit uses.
