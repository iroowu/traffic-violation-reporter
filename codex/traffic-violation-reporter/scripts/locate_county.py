#!/usr/bin/env python3
"""把 GPS 座標（WGS84 十進位度）對到台灣的縣市。純標準庫，不需要 shapely。

用法：
  python3 locate_county.py 24.8138 120.9675
  python3 locate_county.py --json gps.json      # 讀 extract_gps.py 的輸出，回報主要縣市
輸出 JSON：{"county": "新竹市", "lat": ..., "lon": ..., "confidence": "inside" | "nearest"}
"""
import argparse, json, math, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
MAX_NEAREST_DEG = 0.2   # 約 22 公里；超過就不硬指派縣市
GEOJSON = HERE.parent / "assets" / "taiwan_counties.geojson"
TOWNS = HERE.parent / "assets" / "taiwan_towns.geojson"

def point_in_ring(lon, lat, ring):
    """射線法：點是否在單一多邊形環內。ring 是 [[lon, lat], ...]"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside

def point_in_polygon(lon, lat, polygon):
    """polygon = [outer_ring, hole1, hole2...]"""
    if not point_in_ring(lon, lat, polygon[0]):
        return False
    for hole in polygon[1:]:
        if point_in_ring(lon, lat, hole):
            return False
    return True

def point_in_feature(lon, lat, geom):
    t = geom["type"]
    if t == "Polygon":
        return point_in_polygon(lon, lat, geom["coordinates"])
    if t == "MultiPolygon":
        return any(point_in_polygon(lon, lat, poly) for poly in geom["coordinates"])
    return False

def ring_min_dist(lon, lat, ring):
    # 粗略最近距離（度），只用來在點落在海上或邊界縫隙時挑最近縣市
    return min(math.hypot((x - lon) * math.cos(math.radians(lat)), y - lat) for x, y in ring[::max(1, len(ring)//400)])

def feature_min_dist(lon, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return min(ring_min_dist(lon, lat, poly[0]) for poly in polys)

def load_features():
    if not GEOJSON.exists():
        sys.exit(f"找不到縣市邊界檔：{GEOJSON}")
    data = json.loads(GEOJSON.read_text(encoding="utf-8"))
    feats = []
    for f in data["features"]:
        p = f["properties"]
        name = p.get("COUNTYNAME") or p.get("name") or p.get("縣市")
        feats.append((name, f["geometry"]))
    return feats

_TOWN_CACHE = None
def load_towns():
    global _TOWN_CACHE
    if _TOWN_CACHE is None:
        _TOWN_CACHE = []
        if TOWNS.exists():
            for f in json.loads(TOWNS.read_text(encoding="utf-8"))["features"]:
                pr = f["properties"]; _TOWN_CACHE.append((pr["COUNTYNAME"], pr["TOWNNAME"], f["geometry"]))
    return _TOWN_CACHE

def locate_town(lat, lon, county):
    """在該縣市底下找鄉鎮市區（表單的「行政區」下拉要用）。找不到回 None。"""
    cands = [(c, t, g) for c, t, g in load_towns() if c == county] or load_towns()
    for c, t, g in cands:
        if point_in_feature(lon, lat, g): return t
    if cands:
        best = min(cands, key=lambda x: feature_min_dist(lon, lat, x[2]))
        if feature_min_dist(lon, lat, best[2]) < 0.03: return best[1]
    return None

def locate(lat, lon, feats=None):
    feats = feats or load_features()
    for name, geom in feats:
        if point_in_feature(lon, lat, geom):
            return {"county": name, "district": locate_town(lat, lon, name), "lat": lat, "lon": lon, "confidence": "inside"}
    # 不在任何多邊形內（海上、邊界簡化縫隙）：找最近的，但太遠就判定不在台灣
    best = min(feats, key=lambda ng: feature_min_dist(lon, lat, ng[1]))
    dist_deg = feature_min_dist(lon, lat, best[1])
    if dist_deg > MAX_NEAREST_DEG:
        return {"county": None, "lat": lat, "lon": lon, "confidence": "outside_taiwan",
                "note": f"座標離台灣任何縣市都超過 {MAX_NEAREST_DEG*111:.0f} 公里，不是台灣境內；請確認 GPS 是否正確"}
    return {"county": best[0], "district": locate_town(lat, lon, best[0]), "lat": lat, "lon": lon, "confidence": "nearest",
            "approx_km": round(dist_deg * 111, 1),
            "note": "座標不在任何縣市多邊形內（海上或邊界縫隙），取最近縣市；請人工確認"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", nargs="?", type=float)
    ap.add_argument("lon", nargs="?", type=float)
    ap.add_argument("--json", help="extract_gps.py 的輸出檔")
    a = ap.parse_args()
    feats = load_features()
    if a.json:
        g = json.loads(pathlib.Path(a.json).read_text(encoding="utf-8"))
        pts = g.get("points") or []
        if not pts:
            print(json.dumps({"error": "GPS 檔裡沒有座標點"}, ensure_ascii=False)); return
        # 逐點定位後取眾數，並回報「事件時間點」的縣市
        from collections import Counter
        votes = Counter(); conf = Counter()
        per_point = []
        for p in pts:
            r = locate(p["lat"], p["lon"], feats)
            votes[r["county"] or "（台灣境外）"] += 1; conf[r["confidence"]] += 1
            per_point.append({**p, "county": r["county"]})
        main_county, n = votes.most_common(1)[0]
        mid = per_point[len(per_point)//2]
        mid_r = locate(mid["lat"], mid["lon"], feats)
        out = {"county": None if main_county == "（台灣境外）" else main_county, "district": mid_r.get("district"),
               "votes": dict(votes), "confidence": dict(conf), "points": len(pts),
               "midpoint": {"lat": mid["lat"], "lon": mid["lon"], "county": mid["county"], "time": mid.get("time")}}
        at = g.get("at")
        if at:
            ra = locate(at["lat"], at["lon"], feats)
            out["at_event"] = {"sample_sec": at.get("sample_sec"), "time": at.get("time"), "lat": at["lat"], "lon": at["lon"],
                               "county": ra["county"], "district": ra.get("district"), "confidence": ra["confidence"]}
            out["district"] = ra.get("district")
            if ra["county"]: out["county"] = ra["county"]   # 違規那一刻的縣市優先於整段影片的眾數
        notes = []
        if conf.get("outside_taiwan"): notes.append("有座標落在台灣境外，GPS 資料可疑")
        if len([k for k in votes if k != "（台灣境外）"]) > 1: notes.append("影片跨越縣市界，以違規發生那一秒（at_event）的縣市為準")
        if conf.get("nearest"): notes.append("部分座標落在海上或邊界縫隙，用最近縣市補上")
        if notes: out["note"] = "；".join(notes)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif a.lat is not None and a.lon is not None:
        print(json.dumps(locate(a.lat, a.lon, feats), ensure_ascii=False, indent=2))
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
