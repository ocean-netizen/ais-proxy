"""
AIS Proxy — ultra-light for Render free 512MB
No websocket libs, uses subprocess for minimal memory
"""
import json
import time
import os
import subprocess
import sys

from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


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

    body = request.get_json(force=True, silent=True) or {}
    api_key = body.get("api_key", "").strip()
    mmsi_list = [str(m) for m in body.get("mmsi_list", [])]

    if not api_key:
        return jsonify({"error": "api_key required"}), 400

    try:
        result = subprocess.run(
            [sys.executable, "-c", FETCH_SCRIPT],
            input=json.dumps({"api_key": api_key, "mmsi_list": mmsi_list}),
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return jsonify(json.loads(result.stdout.strip()))
        return jsonify({})
    except subprocess.TimeoutExpired:
        return jsonify({})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


FETCH_SCRIPT = '''
import asyncio, json, sys, time

async def main():
    import websockets
    data = json.loads(sys.stdin.read())
    api_key = data["api_key"]
    mmsi_list = data["mmsi_list"]
    positions = {}
    targets = set(mmsi_list)
    now_ts = int(time.time())
    sub = {
        "APIKey": api_key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FilterMessageTypes": ["PositionReport"],
    }
    if mmsi_list:
        sub["FiltersShipMMSI"] = mmsi_list
    try:
        async with websockets.connect(
            "wss://stream.aisstream.io/v0/stream",
            additional_headers={"Origin": "https://aisstream.io"},
            open_timeout=5,
        ) as ws:
            await ws.send(json.dumps(sub))
            deadline = asyncio.get_event_loop().time() + 8
            async for raw in ws:
                if asyncio.get_event_loop().time() > deadline:
                    break
                if targets and positions.keys() >= targets:
                    break
                try:
                    d = json.loads(raw)
                    if d.get("error"): break
                    meta = d.get("Metadata") or d.get("MetaData", {})
                    pr = d.get("Message", {}).get("PositionReport", {})
                    mmsi = str(meta.get("MMSI", ""))
                    if not mmsi or (targets and mmsi not in targets): continue
                    lat = meta.get("Latitude") or pr.get("Latitude")
                    lng = meta.get("Longitude") or pr.get("Longitude")
                    if lat is None: continue
                    positions[mmsi] = {
                        "lat": round(float(lat), 6),
                        "lng": round(float(lng), 6),
                        "speed": round(float(pr.get("Sog") or 0), 1),
                        "heading": int(pr.get("TrueHeading") or pr.get("Cog") or 0),
                        "name": meta.get("ShipName", "").strip(),
                        "time_utc": meta.get("time_utc", ""),
                        "timestamp": now_ts,
                        "is_live": True,
                        "age_seconds": 0,
                    }
                except: pass
    except: pass
    print(json.dumps(positions))

asyncio.run(main())
'''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
