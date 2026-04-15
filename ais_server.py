"""
AIS Proxy — VesselFinder scraping + AISStream fallback
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
    return jsonify({"ok": True, "service": "AIS Proxy v2"})


@app.route("/ais", methods=["POST", "OPTIONS"])
@app.route("/api/ais", methods=["POST", "OPTIONS"])
@app.route("/", methods=["POST", "OPTIONS"])
def ais_proxy():
    if request.method == "OPTIONS":
        return "", 204

    body = request.get_json(force=True, silent=True) or {}
    mmsi_list = [str(m) for m in body.get("mmsi_list", [])]

    if not mmsi_list:
        return jsonify({"error": "mmsi_list required"}), 400

    positions = {}
    for mmsi in mmsi_list:
        pos = scrape_vesselfinder(mmsi)
        if pos:
            positions[mmsi] = pos

    return jsonify(positions)


def scrape_vesselfinder(mmsi):
    """VesselFinder에서 MMSI로 선박 마지막 위치 스크래핑"""
    try:
        url = f"https://www.vesselfinder.com/?mmsi={mmsi}"
        r = http_req.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        # 선박명
        name_el = soup.find('h1') or soup.find('title')
        ship_name = ''
        if name_el:
            ship_name = name_el.get_text(strip=True).split('-')[0].strip()
            ship_name = ship_name.replace('Ship', '').replace('Vessel', '').strip()

        # 좌표: meta tag 또는 테이블에서 추출
        lat, lng = None, None
        speed, heading = 0, 0

        # 방법1: og:image 또는 script에서 좌표 추출
        for script in soup.find_all('script'):
            txt = script.string or ''
            # lat/lng 패턴
            lat_m = re.search(r'["\']lat["\']?\s*[:=]\s*(-?\d+\.?\d*)', txt)
            lng_m = re.search(r'["\'](?:lng|lon)["\']?\s*[:=]\s*(-?\d+\.?\d*)', txt)
            if lat_m and lng_m:
                lat = float(lat_m.group(1))
                lng = float(lng_m.group(1))
            # speed
            spd_m = re.search(r'["\']speed["\']?\s*[:=]\s*(\d+\.?\d*)', txt)
            if spd_m:
                speed = float(spd_m.group(1))
            # heading/course
            hdg_m = re.search(r'["\'](?:heading|course)["\']?\s*[:=]\s*(\d+\.?\d*)', txt)
            if hdg_m:
                heading = int(float(hdg_m.group(1)))

        # 방법2: 테이블 td에서 좌표 추출
        if lat is None:
            for td in soup.find_all('td'):
                txt = td.get_text(strip=True)
                # "35.12345 / 129.12345" 패턴
                coord_m = re.match(r'(-?\d+\.\d+)\s*/\s*(-?\d+\.\d+)', txt)
                if coord_m:
                    lat = float(coord_m.group(1))
                    lng = float(coord_m.group(2))
                    break
                # "N 35° 12.345" 패턴
                dms_m = re.match(r'([NS])\s*(\d+)[°]\s*(\d+\.?\d*)', txt)
                if dms_m:
                    d = float(dms_m.group(2)) + float(dms_m.group(3)) / 60
                    if dms_m.group(1) == 'S': d = -d
                    lat = d

        # 방법3: 링크에서 좌표 추출
        if lat is None:
            for a in soup.find_all('a', href=True):
                m = re.search(r'centerx=(-?\d+\.?\d*)&centery=(-?\d+\.?\d*)', a['href'])
                if m:
                    lng = float(m.group(1))
                    lat = float(m.group(2))
                    break

        if lat is None or lng is None:
            return None

        return {
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "speed": round(speed, 1),
            "heading": heading,
            "name": ship_name,
            "time_utc": "",
            "timestamp": int(time.time()),
            "is_live": False,
            "age_seconds": 0,
            "source": "vesselfinder"
        }
    except Exception as e:
        print(f"[scrape] MMSI {mmsi} error: {e}")
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
