#!/usr/bin/env python3
"""一鍵把一段行車記錄器影片整理成「檢舉案件包」：GPS → 縣市與路名 → 剪片壓縮 → 抽畫面 → 案件摘要。

用法：
  python3 build_case.py 原始.MP4 --at 00:01:32 [--before 8 --after 8] [--county 新竹縣] [--out-root ~/交通檢舉]

--at 是「違規發生那一刻」在影片裡的時間點（使用者按事件鍵的那一秒，或看畫面找到的那一秒）。
--county 手動指定縣市（GPS 讀不到時用）。
產出資料夾 <out-root>/<日期>_<縣市>_<影片檔名>/ 內含：
  clip.mp4        剪好、壓到該縣市上限以下的檢舉影片
  frames/         違規前後每秒一張畫面 + 事件那一刻的車牌放大圖
  gps.json        完整 GPS 軌跡
  case.json       機器可讀的案件資料（時間、座標、縣市、路名、檔案大小、限制）
  摘要.md         給使用者看的乾跑清單（要核對的每一項）
縣市上傳限制讀自 ../references/counties.json（沒有該縣市資料就用保守值 20 MB、mp4）。
"""
import argparse, json, pathlib, re, subprocess, sys, datetime

HERE = pathlib.Path(__file__).resolve().parent
PY = sys.executable

def run_json(args):
    r = subprocess.run([PY, *args], capture_output=True, text=True)
    out = r.stdout.strip()
    # 腳本可能在 JSON 後面多印一行說明，只取第一個 JSON 物件
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {"error": (r.stderr or out)[-800:]}
    try: return json.loads(m.group(0))
    except json.JSONDecodeError: return {"error": out[-800:]}

def hms_to_sec(s):
    parts = [float(x) for x in str(s).split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return parts[0]*3600 + parts[1]*60 + parts[2]

def county_limits(county):
    f = HERE.parent / "references" / "counties.json"
    default = {"max_mb": 20, "formats": ["mp4"], "note": "查無該縣市規格，用保守值"}
    if not f.exists() or not county: return default
    data = json.loads(f.read_text(encoding="utf-8"))
    c = data.get(county) or {}
    up = c.get("upload") or {}
    return {"max_mb": up.get("max_mb_per_file") or default["max_mb"], "formats": up.get("formats") or default["formats"],
            "max_files": up.get("max_files"), "max_seconds": up.get("max_seconds"), "url": c.get("url"), "system": c.get("system")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--at", required=True)
    ap.add_argument("--before", type=float, default=8); ap.add_argument("--after", type=float, default=8)
    ap.add_argument("--county"); ap.add_argument("--out-root", default=str(pathlib.Path.home() / "交通檢舉"))
    ap.add_argument("--plate-crop", default="0.35,0.45,0.30,0.30", help="車牌放大區 x,y,w,h 比例，預設畫面中央偏下")
    a = ap.parse_args()
    src = pathlib.Path(a.src).expanduser().resolve()
    if not src.exists(): sys.exit(f"找不到影片：{src}")
    tmp = pathlib.Path(a.out_root).expanduser() / "_working"; tmp.mkdir(parents=True, exist_ok=True)

    # 1. GPS
    gps_path = tmp / "gps.json"
    gps = run_json([HERE / "extract_gps.py", str(src), "--out", str(gps_path), "--at", a.at])
    has_gps = bool(gps.get("count"))
    # 2. 縣市與路名
    county, loc, geo = a.county, None, None
    if has_gps:
        loc = run_json([HERE / "locate_county.py", "--json", str(gps_path)])
        county = county or loc.get("county")
        geo = run_json([HERE / "reverse_geocode.py", "--json", str(gps_path)])
    # 3. 違規時刻的實際時間
    event_time = None
    if has_gps and gps.get("at") and gps["at"].get("time"):
        event_time = gps["at"]["time"]
    elif gps.get("create_date") and gps["create_date"] not in ("0000:00:00 00:00:00", None):
        try:
            base = datetime.datetime.strptime(gps["create_date"][:19], "%Y:%m:%d %H:%M:%S")
            event_time = (base + datetime.timedelta(seconds=hms_to_sec(a.at))).strftime("%Y-%m-%d %H:%M:%S") + "（由檔案建立時間推算，請核對畫面水印）"
        except ValueError: pass
    # 4. 案件資料夾
    day = (event_time or datetime.datetime.now().isoformat())[:10].replace("-", "")
    case_dir = pathlib.Path(a.out_root).expanduser() / f"{day}_{county or '縣市未定'}_{src.stem}"
    case_dir.mkdir(parents=True, exist_ok=True)
    gps_path.rename(case_dir / "gps.json"); gps_path = case_dir / "gps.json"
    # 5. 剪片壓縮
    lim = county_limits(county)
    clip = run_json([HERE / "clip_video.py", str(src), "--center", a.at, "--before", str(a.before), "--after", str(a.after),
                     "--max-mb", str(lim["max_mb"]), "--out", str(case_dir / "clip.mp4")])
    # 6. 抽畫面：片段內每秒一張，另抽事件那一刻與前後 0.5 秒的車牌放大圖
    frames = case_dir / "frames"
    subprocess.run([PY, HERE / "extract_frames.py", str(case_dir / "clip.mp4"), "--out-dir", str(frames), "--fps", "1"], capture_output=True)
    ev = a.before  # 片段內事件位置
    for t in (ev - 0.5, ev, ev + 0.5):
        subprocess.run([PY, HERE / "extract_frames.py", str(case_dir / "clip.mp4"), "--out-dir", str(frames / "plate"),
                        "--at", f"{max(0, t):.2f}", "--crop", a.plate_crop], capture_output=True)
    # 7. 寫 case.json 與摘要
    case = {"source_video": str(src), "event_offset_in_source": a.at, "event_time": event_time,
            "gps_available": has_gps, "gps_points": gps.get("count", 0), "device": {"make": gps.get("make"), "model": gps.get("model"), "handler": gps.get("handler")},
            "county": county, "district": (loc or {}).get("district"),
            "county_confidence": (loc or {}).get("at_event", {}).get("confidence") if loc else ("manual" if a.county else None),
            "location": geo if geo and not geo.get("error") else None,
            "coords_at_event": (gps.get("at") or {}) if has_gps else None,
            "clip": clip, "limits": lim, "frames_dir": str(frames), "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "violation": {"type": None, "article": None, "plate": None, "vehicle_type": None, "description": None},
            "notes": [n for n in [gps.get("note"), (loc or {}).get("note"), (geo or {}).get("error")] if n]}
    (case_dir / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    loc_text = (geo or {}).get("suggested_location_text") if geo and not geo.get("error") else "（GPS 讀不到，請看畫面填）"
    md = f"""# 檢舉案件摘要（請逐項核對）

| 項目 | 小精靈判讀 | 請核對 |
|---|---|---|
| 原始影片 | {src.name} | |
| 違規時刻（影片內） | {a.at} | 這一秒是不是違規發生的瞬間 |
| 違規時間（實際） | {event_time or '讀不到，請看畫面水印'} | 與畫面上的日期時間水印一致嗎 |
| 縣市 | {county or '無法判定'} | {'GPS 判定' if has_gps and not a.county else '手動指定' if a.county else ''} |
| 行政區（表單下拉用） | {(loc or {}).get('district') or '無法判定'} | 離線邊界判定，與路名對一下 |
| 地點 | {loc_text} | 路名、路口、方向要與畫面相符 |
| 座標 | {json.dumps(case['coords_at_event'], ensure_ascii=False) if case['coords_at_event'] else '無'} | |
| 檢舉影片 | clip.mp4，{clip.get('size_mb')} MB（上限 {lim['max_mb']} MB，{clip.get('mode')}） | 有沒有拍到號誌、車牌、完整過程 |
| 車牌 | （待判讀，見 frames/plate/） | |
| 違規事實與法條 | （待判讀） | |

{'⚠️ ' + '；'.join(case['notes']) if case['notes'] else ''}
"""
    (case_dir / "摘要.md").write_text(md, encoding="utf-8")
    try: tmp.rmdir()
    except OSError: pass
    print(json.dumps({"case_dir": str(case_dir), "county": county, "event_time": event_time, "location": loc_text,
                      "clip_mb": clip.get("size_mb"), "limit_mb": lim["max_mb"], "within_limit": clip.get("within_limit"),
                      "frames": len(list(frames.glob("*.jpg"))), "notes": case["notes"]}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
