"""
AIS Proxy — MyShipTracking scraping for last known position
Ultra-light for Render free 512MB
"""
import json
import re
import time
import os

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests as http_req
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


@app.route("/health", methods=["GET", "HEAD"])
@app.route("/", methods=["GET", "HEAD"])
def health():
    return jsonify({"ok": True, "service": "AIS Proxy v3"})


@app.route("/ais", methods=["POST", "OPTIONS"])
@app.route("/api/ais", methods=["POST", "OPTIONS"])
@app.route("/", methods=["POST", "OPTIONS"])
def ais_proxy():
    if request.method == "OPTIONS":
        return "", 204

    body = request.get_json(force=True, silent=True) or {}
    vessels = body.get("vessels", [])
    if not vessels:
        mmsi_list = [str(m) for m in body.get("mmsi_list", [])]
        vessels = [{"mmsi": m} for m in mmsi_list]

    if not vessels:
        return jsonify({"error": "vessels or mmsi_list required"}), 400

    positions = {}
    for v in vessels:
        mmsi = str(v.get("mmsi", ""))
        if not mmsi:
            continue
        pos = scrape_myshiptracking(mmsi, v.get("name", ""), v.get("imo", ""))
        if pos:
            positions[mmsi] = pos

    return jsonify(positions)


def scrape_myshiptracking(mmsi, vessel_name='', imo=''):
    try:
        slug = vessel_name.lower().replace(' ', '-').replace('.', '-') if vessel_name else 'vessel'
        slug = re.sub(r'[^a-z0-9-]', '', slug)
        slug = re.sub(r'-+', '-', slug).strip('-') or 'vessel'
        detail_url = f"https://www.myshiptracking.com/vessels/{slug}-mmsi-{mmsi}-imo-{imo or 0}"
        print(f"[scrape] MMSI {mmsi}: trying {detail_url}", flush=True)

        r = http_req.get(detail_url, headers=HEADERS, timeout=10, allow_redirects=True)
        print(f"[scrape] MMSI {mmsi}: status {r.status_code}", flush=True)

        if r.status_code != 200:
            alt_url = f"https://www.myshiptracking.com/vessels/vessel-mmsi-{mmsi}-imo-{imo or 0}"
            print(f"[scrape] MMSI {mmsi}: trying alt {alt_url}", flush=True)
            r = http_req.get(alt_url, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                print(f"[scrape] MMSI {mmsi}: failed status {r.status_code}", flush=True)
                return None

        text = r.text
        soup = BeautifulSoup(text, 'html.parser')

        ship_name = vessel_name
        h1 = soup.find('h1')
        if h1:
            ship_name = h1.get_text(strip=True)

        lat, lng = None, None
        speed, course = 0, 0

        coord_matches = re.findall(r'(-?\d+\.\d{3,6})\s*°?\s*/\s*(-?\d+\.\d{3,6})', text)
        if coord_matches:
            lat = float(coord_matches[0][0])
            lng = float(coord_matches[0][1])

        spd_m = re.search(r'(\d+\.?\d*)\s*(?:Knots|kn|kt)', text, re.IGNORECASE)
        if spd_m:
            speed = float(spd_m.group(1))

        crs_m = re.search(r'Course[:\s]*(\d+\.?\d*)\s*°', text, re.IGNORECASE)
        if crs_m:
            course = int(float(crs_m.group(1)))

        if lat is None or lng is None:
            print(f"[scrape] MMSI {mmsi}: coords not found in page", flush=True)
            return None

        print(f"[scrape] MMSI {mmsi}: {ship_name} at {lat}, {lng}", flush=True)
        return {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "speed": round(speed, 1),
            "heading": course,
            "name": ship_name,
            "time_utc": "",
            "timestamp": int(time.time()),
            "is_live": False,
            "age_seconds": 0,
            "source": "myshiptracking"
        }
    except Exception as e:
        print(f"[scrape] MMSI {mmsi} error: {e}", flush=True)
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
