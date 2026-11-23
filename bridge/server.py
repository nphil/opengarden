"""
OpenGarden bridge — Phase 1: capture.

Accepts the garden's TLS connection in place of the vendor cloud and
logs the application-layer bytes for protocol analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import struct
import time
from datetime import datetime
from pathlib import Path

from certs import ensure_certificates

CONFIG_DIR = Path(os.environ.get("OG_CONFIG", "/config"))
CERTS_DIR = CONFIG_DIR / "certs"
LOG_DIR = CONFIG_DIR / "logs"
HTTP_PORT = int(os.environ.get("OG_HTTP_PORT", "80"))
TLS_PORT = int(os.environ.get("OG_TLS_PORT", "8443"))
HOSTNAME = "app5.aerogarden.com"

log = logging.getLogger("opengarden")


# ---------------------------------------------------------------------------
# HTTP server (port 80) — serves the CA cert the garden downloads on boot
# ---------------------------------------------------------------------------

async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle one HTTP request from the garden."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=10)
        if not request_line:
            return
        request_text = request_line.decode("ascii", errors="replace").strip()
        log.info("HTTP %s from %s", request_text, writer.get_extra_info("peername"))

        # Consume remaining headers (unused)
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line in (b"\r\n", b"\n", b""):
                break

        if "/api/Admin/GetCA" in request_text:
            await _serve_get_ca(writer)
        elif "/api/Admin/GetFile" in request_text:
            await _serve_ca_file(writer)
        else:
            await _serve_404(writer, request_text)
    except Exception as exc:
        log.warning("HTTP error: %s", exc)
    finally:
        writer.close()
        await writer.wait_closed()


def _build_wrapped_ca() -> bytes:
    """Wrap our PEM CA cert in the 32-byte firmware header the garden expects.

    The original CA file (CA-KFW-2041-DIGI-G2.bin) has this structure:
      [0:4]   u32 LE  PEM body size
      [4:8]   fe ca 58 03  (constant)
      [8:12]  "KFW\\0"  (module name, matches fwModule= query param)
      [12:16] "2041"   (version, from versionName "CA-V2041")
      [16:19] 8e 5d 98 (constant in the original; purpose unknown)
      [19:32] zero padding
    """
    pem = (CERTS_DIR / "ca.pem").read_bytes()
    hdr = bytearray(32)
    struct.pack_into("<I", hdr, 0, len(pem))
    hdr[4:8] = b"\xfe\xca\x58\x03"
    hdr[8:12] = b"KFW\x00"
    hdr[12:16] = b"2041"
    hdr[16:19] = b"\x8e\x5d\x98"
    return bytes(hdr) + pem


async def _serve_get_ca(writer: asyncio.StreamWriter):
    wrapped = _build_wrapped_ca()
    body = json.dumps({
        "fw_url": (
            f"http://{HOSTNAME}/api/Admin/GetFile"
            f"?fileName=opengarden-ca.bin"
        ),
        "bwVersion": "KFW",
        "deviceTypeValue": "CA",
        "pkgSize": len(wrapped),
        "versionCode": 300000,
        "versionName": "CA-V2041",
        "websocketHost": HOSTNAME,
        "websocketPort": TLS_PORT,
    })
    _write_http(writer, 200, "application/json; charset=utf-8", body.encode())
    await writer.drain()
    log.info("HTTP served GetCA (wrapped size %d)", len(wrapped))


async def _serve_ca_file(writer: asyncio.StreamWriter):
    wrapped = _build_wrapped_ca()
    _write_http(writer, 200, "application/octet-stream", wrapped)
    await writer.drain()
    log.info("HTTP served CA file (%d bytes, with firmware header)", len(wrapped))


async def _serve_404(writer: asyncio.StreamWriter, path: str):
    _write_http(writer, 404, "text/plain", b"Not Found")
    await writer.drain()
    log.info("HTTP 404 %s", path)


def _write_http(
    writer: asyncio.StreamWriter, status: int, content_type: str, body: bytes
):
    reason = "OK" if status == 200 else "Not Found"
    header = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    writer.write(header + body)


# ---------------------------------------------------------------------------
# TLS server (port 8443) — accepts the garden's connection and logs traffic
# ---------------------------------------------------------------------------

_conn_counter = 0


async def handle_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global _conn_counter
    _conn_counter += 1
    cid = _conn_counter
    peer = writer.get_extra_info("peername")
    log.info("TLS [%d] connected from %s", cid, peer)

    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"garden_{cid}_{ts_str}.bin"
    total = 0

    with open(log_path, "wb") as fh:
        try:
            while True:
                data = await asyncio.wait_for(reader.read(8192), timeout=30)
                if not data:
                    log.info("TLS [%d] disconnected (clean close)", cid)
                    break

                total += len(data)
                # Timestamped record: [f64 unix_ts][u32 length][bytes]
                fh.write(struct.pack("!dI", time.time(), len(data)))
                fh.write(data)
                fh.flush()

                log.info(
                    "TLS [%d] recv %d bytes (total %d): %s%s",
                    cid, len(data), total,
                    data[:80].hex(),
                    "..." if len(data) > 80 else "",
                )
        except asyncio.TimeoutError:
            log.info("TLS [%d] no data for 30 s, closing", cid)
        except (ConnectionResetError, BrokenPipeError) as exc:
            log.info("TLS [%d] connection lost: %s", cid, exc)

    writer.close()
    log.info("TLS [%d] done — %d bytes, log %s", cid, total, log_path.name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    ca_path, cert_path, key_path = ensure_certificates(CERTS_DIR, HOSTNAME)
    log.info("Certificates ready in %s", CERTS_DIR)

    # TLS context — the garden speaks TLS 1.2 with RSA key-exchange ciphers
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    ctx.set_ciphers(
        "AES128-SHA:AES256-SHA:AES128-SHA256:AES256-SHA256:@SECLEVEL=0"
    )
    ctx.minimum_version = ssl.TLSVersion.TLSv1
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2

    http_srv = await asyncio.start_server(handle_http, "0.0.0.0", HTTP_PORT)
    tls_srv = await asyncio.start_server(handle_tls, "0.0.0.0", TLS_PORT, ssl=ctx)

    log.info("OpenGarden bridge (phase 1 — capture)")
    log.info("  HTTP  :%d  (CA distribution)", HTTP_PORT)
    log.info("  TLS   :%d  (garden connection)", TLS_PORT)
    log.info("  Logs  %s", LOG_DIR)

    async with http_srv, tls_srv:
        await asyncio.gather(
            http_srv.serve_forever(),
            tls_srv.serve_forever(),
        )


if __name__ == "__main__":
    asyncio.run(main())
