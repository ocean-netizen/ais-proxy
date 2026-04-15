"""
AIS Proxy Server — Flask + websockets
POST /ais  →  AISStream.io  →  vessel positions JSON
"""

import asyncio
import json
import time
import os

from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    import websockets
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

app = Flask(__name__)
CORS(app)

ORIGIN = "https://aisstream.io"


@app.route("/health", methods=["GET", "HEAD"])
@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"ok": True, "service": "AIS Proxy"})



@app.route("/ais", methods=["POST", "OPTIONS"])
@app.route("/api/ais", methods=["POST", "OPTIONS"])
@app.route("/", methods=["POST", "OPTIONS"])
def ais_proxy():
    if request.method == "OPTIONS":
        return "", 204

    body      = request.get_json(force=True, silent=True) or {}
    api_key   = body.get("api_key", "").strip()
    mmsi_list = [str(m) for m in body.get("mmsi_list", [])]

    if not api_key:
        return jsonify({"error": "api_key required"}), 400

    try:
        positions = asyncio.run(fetch_positions(api_key, mmsi_list, timeout=22))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(positions)


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
                    if data.get("error"):
                        break
                    meta     = data.get("Metadata") or data.get("MetaData", {})
                    pr       = data.get("Message", {}).get("PositionReport", {})
                    mmsi_val = str(meta.get("MMSI", ""))
                    if not mmsi_val or (targets and mmsi_val not in targets):
                        continue
                    lat = meta.get("Latitude") or meta.get("latitude") or pr.get("Latitude")
                    lng = meta.get("Longitude") or meta.get("longitude") or pr.get("Longitude")
                    if lat is None:
                        continue
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
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
