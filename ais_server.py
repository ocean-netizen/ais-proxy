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
    mmsi_list = [str(m) for m in body.get("mmsi_list", [])]

    if not mmsi_list:
        return jsonify({"error": "mmsi_list required"}), 400

    positions = {}
    for mmsi in mmsi_list:
        pos = scrape_myshiptracking(mmsi)
        if pos:
            positions[mmsi] = pos

    return jsonify(positions)


def scrape_myshiptracking(mmsi):
    """MyShipTracking에서 MMSI로 선박 마지막 위치 스크래핑"""
    try:
        # 1단계: 검색 페이지에서 상세 페이지 링크 찾기
        search_url = f"https://www.myshiptracking.com/vessels?mmsi={mmsi}"
        r = http_req.get(search_url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        # mmsi가 포함된 상세 페이지 링크 찾기
        detail_path = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            if f'mmsi-{mmsi}' in href and '/vessels/' in href:
                detail_path = href
                break

        if not detail_path:
            print(f"[scrape] MMSI {mmsi}: detail link not found on search page")
            return None

        # 2단계: 상세 페이지에서 위치 데이터 추출
        detail_url = 'https://www.myshiptracking.com' + detail_path if not detail_path.startswith('http') else detail_path
        print(f"[scrape] MMSI {mmsi}: fetching {detail_url}")

        r2 = http_req.get(detail_url, headers=HEADERS, timeout=10)
        if r2.status_code != 200:
            return None

        text = r2.text
        soup2 = BeautifulSoup(text, 'html.parser')

        # 선박명
        ship_name = ''
        h1 = soup2.find('h1')
        if h1:
            ship_name = h1.get_text(strip=True)

        # 좌표 추출: "-26.27357° / 153.42024°" 패턴
        lat, lng = None, None
        speed, course = 0, 0

        coord_matches = re.findall(r'(-?\d+\.\d{3,6})\s*°?\s*/\s*(-?\d+\.\d{3,6})', text)
        if coord_matches:
            lat = float(coord_matches[0][0])
            lng = float(coord_matches[0][1])

        # 속도: "16.7 Knots"
        spd_m = re.search(r'(\d+\.?\d*)\s*(?:Knots|kn|kt)', text, re.IGNORECASE)
        if spd_m:
            speed = float(spd_m.group(1))

        # 방향: "Course: 23.2°"
        crs_m = re.search(r'Course[:\s]*(\d+\.?\d*)\s*°', text, re.IGNORECASE)
        if crs_m:
            course = int(float(crs_m.group(1)))

        if lat is None or lng is None:
            print(f"[scrape] MMSI {mmsi}: coords not found in detail page")
            return None

        print(f"[scrape] MMSI {mmsi}: {ship_name} at {lat}, {lng}")
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
        print(f"[scrape] MMSI {mmsi} error: {e}")
        return None



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
