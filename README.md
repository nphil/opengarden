# OpenGarden

Local control for AeroGarden Wi-Fi gardens, with Home Assistant integration.

AeroGarden Wi-Fi gardens (Bounty Elite and relatives) are controlled today only through the manufacturer's cloud service. If that service is slow, changes, or is discontinued, the garden's touchscreen keeps working, but the app, scheduling from your phone and any automation stop. OpenGarden documents how the garden communicates and aims to provide a small server on your own network that the garden can talk to instead, so that you can keep controlling hardware you own.

## Status

**Research phase.** Nothing here is ready to install yet.

| Area | State |
|---|---|
| Phone-app-to-cloud REST API (`v1/*`) | Documented, see [docs/protocol.md](docs/protocol.md) |
| Device state model, enums, string encodings | Documented |
| LAN TCP port 8080 frame format | Documented (two commands known) |
| Wi-Fi provisioning (SoftAP) | Documented for older models |
| Garden-to-cloud connection (TLS, port 8443, 2 s heartbeat) | Connection behaviour observed; the application protocol inside it is **not yet decoded** |
| Local bridge server | Planned, see [docs/architecture.md](docs/architecture.md) |
| Home Assistant integration | Planned |

## Supported hardware

| Model | Wi-Fi chip (per public filings and app analysis) | Status |
|---|---|---|
| AeroGarden Bounty Elite | Marvell 88MC200 + 88W8801, or MediaTek MT7682 in later revisions (unconfirmed per unit) | Primary target, research in progress |
| AeroGarden Bounty / Bounty Basic | Same family | Expected to work the same way, untested |
| AeroGarden Farm 12 / 24 series | Same family | Expected, untested. Known to have the LAN port 8080 light-lift command |
| Harvest Elite / Harvest Classic | Marvell or MediaTek (SoftAP provisioning flow) | Provisioning documented; otherwise untested |
| Stem / Tabletop / Trio grow lights | Bluetooth LE only | Out of scope (an existing BLE integration covers the Stem light) |

## How it works (planned)

1. **Local DNS.** Your router or DNS server answers the garden's cloud hostname (`app5.aerogarden.com`) with the address of a machine on your LAN running the OpenGarden bridge. The official phone app uses the same hostname, so the rule should apply to the garden only (a per-client DNS rule, or a router rule matched on the garden's address); a house-wide record would stop the phone app from working.
2. **Local certificate authority.** The garden opens a TLS connection to the cloud host on port 8443 and, as observed, retrieves a CA certificate over plain HTTP before doing so. The bridge serves its own CA certificate on port 80 and presents a server certificate signed by it on port 8443.
3. **Local server.** The bridge accepts the garden's connection, keeps it alive, and exposes the garden's state and controls on a local API.
4. **Home Assistant.** A custom integration reads state and sends commands through the bridge. No account or internet access is required.

The one missing piece is the application-level protocol the garden speaks inside the TLS connection. See [docs/protocol.md](docs/protocol.md#garden-to-cloud-connection) and the open questions at the end of that document.

## Documentation

- [docs/protocol.md](docs/protocol.md): protocol reference (cloud REST API, state model, encodings, LAN port 8080, provisioning, BLE)
- [docs/research.md](docs/research.md): company and cloud status, prior art, what other projects do
- [docs/architecture.md](docs/architecture.md): bridge design, planned Home Assistant entities, development phases

## Project structure

```
opengarden/
  README.md
  LICENSE
  docs/
    protocol.md        Protocol reference
    research.md        Research notes
    architecture.md    Bridge and integration design
  bridge/              Local bridge server (planned)
  custom_components/   Home Assistant integration (planned)
  tools/               Capture and analysis helpers (planned)
```

## Contributing

Useful contributions right now:

- Packet captures of a garden's own traffic on your network (remove your Wi-Fi password and account details first).
- Which Wi-Fi chip family your unit uses (the FCC ID on its label helps).
- Whether your own garden accepts a TCP connection on port 8080 of its LAN address.
- Corrections to the documents, especially the open questions in the protocol reference.

Please never post credentials, tokens, account e-mail addresses or your real MAC address or network details.

## Credits

OpenGarden builds on public work by others:

- **dalinicus**, **jacobdonenfeld**, **ksheumaker** and **epotex**: Home Assistant integrations and the original documentation of the legacy cloud API.
- **vagelim** (blog.evangelosm.com): early traffic analysis of a Bounty garden.
- **sionide21**: Bluetooth LE integration for the Stem grow light.
- **ethanfritzt** and **c99koder**: ESP32/ESPHome work on the Sprout.
- Projects whose techniques informed this one: Bumper, LocalTuya, msmart-ng, python-kasa, Valetudo, dorita980. See [docs/research.md](docs/research.md).

## Disclaimer

OpenGarden is an independent project and is not affiliated with or endorsed by AeroGrow, Scotts Miracle-Gro or Intretech. "AeroGarden" is a trademark of its owner. Use it only with hardware you own, on networks you control. Provided as is, without warranty.

## License

MIT. See [LICENSE](LICENSE).
