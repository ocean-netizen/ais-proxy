"""
AIS Proxy v3 — regex-only scraping (no BeautifulSoup)
Ultra-light for Render free 512MB
"""
import json
import re
import time
import os

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests as http_req

app = Flask(__name__)
CORS(app)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Sec-Ch-Ua': '"Google Chrome";v="131", "Chromium";v="131"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
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
        pos = scrape_position(mmsi, v.get("name", ""), v.get("imo", ""))
        if pos:
            positions[mmsi] = pos

    return jsonify(positions)


def scrape_position(mmsi, vessel_name='', imo=''):
    try:
        slug = vessel_name.lower().replace(' ', '-') if vessel_name else 'vessel'
        slug = re.sub(r'[^a-z0-9-]', '', slug)
        slug = re.sub(r'-+', '-', slug).strip('-') or 'vessel'
        url = f"https://www.myshiptracking.com/vessels/{slug}-mmsi-{mmsi}-imo-{imo or 0}"
        print(f"[scrape] {mmsi}: {url}", flush=True)

        r = http_req.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        print(f"[scrape] {mmsi}: status {r.status_code}", flush=True)

        if r.status_code != 200:
            url2 = f"https://www.myshiptracking.com/vessels/v-mmsi-{mmsi}-imo-{imo or 0}"
            r = http_req.get(url2, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                return None

        text = r.text

        # 선박명: <h1> 태그
        name_m = re.search(r'<h1[^>]*>([^<]+)</h1>', text)
        ship_name = name_m.group(1).strip() if name_m else vessel_name

        # 좌표: "-26.27357° / 153.42024°"
        lat, lng = None, None
        coord_m = re.findall(r'(-?\d+\.\d{3,6})\s*°?\s*/\s*(-?\d+\.\d{3,6})', text)
        if coord_m:
            lat = float(coord_m[0][0])
            lng = float(coord_m[0][1])

        # 속도
        speed = 0
        spd_m = re.search(r'(\d+\.?\d*)\s*(?:Knots|kn)', text, re.IGNORECASE)
        if spd_m:
            speed = float(spd_m.group(1))

        # 방향
        course = 0
        crs_m = re.search(r'Course[:\s]*(\d+\.?\d*)\s*°', text, re.IGNORECASE)
        if crs_m:
            course = int(float(crs_m.group(1)))

        if lat is None or lng is None:
            print(f"[scrape] {mmsi}: no coords found", flush=True)
            return None

        print(f"[scrape] {mmsi}: OK {ship_name} {lat},{lng}", flush=True)
        return {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "speed": round(speed, 1),
            "heading": course,
            "name": ship_name,
            "timestamp": int(time.time()),
            "is_live": False,
            "age_seconds": 0,
            "source": "myshiptracking"
        }
    except Exception as e:
        print(f"[scrape] {mmsi} error: {e}", flush=True)
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
