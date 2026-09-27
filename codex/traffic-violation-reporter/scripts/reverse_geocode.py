#!/usr/bin/env python3
"""把座標換成「縣市＋鄉鎮市區＋路名」，填檢舉表單的「違規地點」欄位用。

用 OpenStreetMap 的 Nominatim 公開服務（免費、不必金鑰；規定：每秒最多 1 次、要帶 User-Agent）。
沒網路時會失敗，這時改用 locate_county.py 的離線縣市結果，路名請使用者看畫面補。

用法：
  python3 reverse_geocode.py 24.8273 121.0128
  python3 reverse_geocode.py --json gps.json          # 用 extract_gps.py 輸出裡的 at（違規那一刻）或 median 座標
輸出 JSON：{"county": "新竹縣", "district": "竹北市", "road": "光明六路", "display": "...", "source": "nominatim"}
"""
import argparse, json, pathlib, sys, time, urllib.parse, urllib.request

UA = "traffic-violation-reporter-skill/1.0 (open-source dashcam report helper)"

def nominatim(lat, lon, lang="zh-TW"):
    q = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 17, "addressdetails": 1, "accept-language": lang})
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/reverse?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def normalize(d, lat, lon):
    a = d.get("address", {})
    county = a.get("city") or a.get("county") or a.get("state") or ""
    # OSM 對台灣的層級不一致：直轄市在 city，縣在 county；區在 suburb/town/city_district
    district = a.get("town") or a.get("city_district") or a.get("suburb") or a.get("village") or a.get("township") or ""
    road = a.get("road") or a.get("pedestrian") or a.get("footway") or ""
    # 台灣習慣寫「臺」，OSM 多寫「台」，兩種都留
    return {"lat": lat, "lon": lon, "county": county, "district": district, "road": road,
            "house_number": a.get("house_number"), "display": d.get("display_name"), "source": "nominatim",
            "suggested_location_text": " ".join(x for x in [county, district, road] if x) or d.get("display_name")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", nargs="?", type=float); ap.add_argument("lon", nargs="?", type=float)
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.json:
        g = json.loads(pathlib.Path(a.json).read_text(encoding="utf-8"))
        src = g.get("at") or g.get("median")
        if not src: sys.exit("GPS 檔裡沒有座標")
        lat, lon = src["lat"], src["lon"]
    elif a.lat is not None and a.lon is not None:
        lat, lon = a.lat, a.lon
    else:
        ap.print_help(); return
    try:
        d = nominatim(lat, lon)
    except Exception as e:
        print(json.dumps({"lat": lat, "lon": lon, "error": f"線上反查失敗：{e}", "hint": "改用 locate_county.py 取縣市，路名請看影片畫面補"}, ensure_ascii=False)); sys.exit(1)
    print(json.dumps(normalize(d, lat, lon), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
