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
        # 1단계: 검색으로 선박 상세 페이지 URL 찾기
        search_url = f"https://www.myshiptracking.com/vessels?mmsi={mmsi}"
        r = http_req.get(search_url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        # 상세 페이지 링크 찾기 (mmsi가 URL에 포함된 링크)
        detail_url = None
        for a in soup.find_all('a', href=True):
            if f'mmsi-{mmsi}' in a['href']:
                href = a['href']
                if not href.startswith('http'):
                    href = 'https://www.myshiptracking.com' + href
                detail_url = href
                break

        if not detail_url:
            # 직접 URL 패턴 시도
            detail_url = f"https://www.myshiptracking.com/vessels?mmsi={mmsi}"

        # 2단계: 상세 페이지에서 위치 데이터 추출
        r2 = http_req.get(detail_url, headers=HEADERS, timeout=10)
        if r2.status_code != 200:
            return None

        soup2 = BeautifulSoup(r2.text, 'html.parser')
        text = soup2.get_text()

        # 선박명
        ship_name = ''
        h1 = soup2.find('h1')
        if h1:
            ship_name = h1.get_text(strip=True)

        # 좌표 추출
        lat, lng = None, None
        speed, course = 0, 0

        # 패턴: -26.27357° / 153.42024° 또는 유사
        coord_matches = re.findall(r'(-?\d+\.\d{3,6})\s*[°]?\s*/\s*(-?\d+\.\d{3,6})', text)
        if coord_matches:
            lat = float(coord_matches[0][0])
            lng = float(coord_matches[0][1])

        # 속도 추출
        spd_m = re.search(r'(\d+\.?\d*)\s*(?:Knots|kn|kt)', text, re.IGNORECASE)
        if spd_m:
            speed = float(spd_m.group(1))

        # 방향 추출
        crs_m = re.search(r'Course[:\s]*(\d+\.?\d*)\s*°', text, re.IGNORECASE)
        if crs_m:
            course = int(float(crs_m.group(1)))

        # meta 태그에서도 시도
        if lat is None:
            for meta in soup2.find_all('meta'):
                content = meta.get('content', '')
                geo_m = re.search(r'(-?\d+\.\d+)[,;\s]+(-?\d+\.\d+)', content)
                if geo_m:
                    lat = float(geo_m.group(1))
                    lng = float(geo_m.group(2))
                    break

        # script 태그에서도 시도
        if lat is None:
            for script in soup2.find_all('script'):
                txt = script.string or ''
                lat_m = re.search(r'lat["\']?\s*[:=]\s*(-?\d+\.\d+)', txt)
                lng_m = re.search(r'(?:lng|lon)["\']?\s*[:=]\s*(-?\d+\.\d+)', txt)
                if lat_m and lng_m:
                    lat = float(lat_m.group(1))
                    lng = float(lng_m.group(1))
                    break

        if lat is None or lng is None:
            return None

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
