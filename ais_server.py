# -*- coding: utf-8 -*-
"""
AIS HTTP Server — Render.com deployment
POST /ais  →  connects to AISStream.io  →  returns vessel positions
No secrets stored here. API key is passed per request from the client.
"""

import asyncio
import json
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import websockets
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

ORIGIN = "https://aisstream.io"
PORT   = int(os.environ.get("PORT", 10000))


class Handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors(); self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "service": "AIS Proxy"})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path not in ("/ais", "/api/ais", "/"):
            self.send_response(404); self.end_headers(); return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            body = {}

        api_key   = body.get("api_key", "").strip()
        mmsi_list = [str(m) for m in body.get("mmsi_list", [])]

        if not api_key:
            self._json(400, {"error": "api_key required"}); return

        try:
            positions = asyncio.run(fetch_positions(api_key, mmsi_list, timeout=22))
        except Exception as e:
            self._json(500, {"error": str(e)}); return

        self._json(200, positions)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass


async def fetch_positions(api_key, mmsi_list, timeout=22):
    positions = {}
    targets   = set(mmsi_list)
    now_ts    = int(time.time())

    try:
        async with websockets.connect(
            "wss://stream.aisstream.io/v0/stream",
            additional_headers={"Origin": ORIGIN},
            open_timeout=10,
        ) as ws:
            sub = {
                "APIKey":             api_key,
                "BoundingBoxes":      [[[-90, -180], [90, 180]]],
                "FilterMessageTypes": ["PositionReport"],
            }
            if mmsi_list:
                sub["FiltersShipMMSI"] = mmsi_list

            await ws.send(json.dumps(sub))
            deadline = asyncio.get_event_loop().time() + timeout

            async for raw in ws:
                if asyncio.get_event_loop().time() > deadline:
                    break
                if targets and positions.keys() >= targets:
                    break
                try:
                    data     = json.loads(raw)
                    if data.get("error"): break
                    meta     = data.get("Metadata") or data.get("MetaData", {})
                    pr       = data.get("Message", {}).get("PositionReport", {})
                    mmsi_val = str(meta.get("MMSI", ""))
                    if not mmsi_val or (targets and mmsi_val not in targets):
                        continue
                    lat = meta.get("Latitude") or meta.get("latitude") or pr.get("Latitude")
                    lng = meta.get("Longitude") or meta.get("longitude") or pr.get("Longitude")
                    if lat is None: continue
                    positions[mmsi_val] = {
                        "lat":         round(float(lat), 6),
                        "lng":         round(float(lng), 6),
                        "speed":       round(float(pr.get("Sog") or 0), 1),
                        "heading":     int(pr.get("TrueHeading") or pr.get("Cog") or 0),
                        "name":        meta.get("ShipName", "").strip(),
                        "time_utc":    meta.get("time_utc", ""),
                        "timestamp":   now_ts,
                        "is_live":     True,
                        "age_seconds": 0,
                    }
                except Exception:
                    pass
    except Exception:
        pass

    return positions


if __name__ == "__main__":
    print(f"[AIS Server] Starting on port {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
