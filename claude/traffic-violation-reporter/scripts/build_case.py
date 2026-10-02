#!/usr/bin/env python3
"""一鍵把一段行車記錄器影片整理成「檢舉案件包」：GPS → 縣市與路名 → 剪片壓縮 → 抽畫面 → 案件摘要。

用法：
  python3 build_case.py 原始.MP4 --at 00:01:32 [--before 8 --after 8] [--county 新竹縣] [--out-root ~/交通檢舉]
  python3 build_case.py 原始.MP4 --at 00:01:56 --before 12 --after 4 --county 新竹縣 \
      --crop 0,0.4,0.6,0.6 --photos 114.4,116.3 --plate-photo 107.3   # 裁切放大車牌＋違規截圖＋最清楚車牌截圖

--crop 是裁切範圍 x,y,w,h（0 到 1 比例），以「車牌放大」為主，但必須保留號誌與停止線、左下日期時間車速水印、地點環境。
       先用 clip_video.py --preview 逐秒確認裁切框沒有切掉這三樣，再正式產出（2026-10-02 使用者定案）。
--photos 是原始影片裡的秒數（逗號分隔），各抽一張同樣裁切的原始解析度截圖 photo1.jpg…，與影片一起上傳當補充證據。
--plate-photo 是「行進中車牌拍得最清楚」那一格的秒數（用 best_plate_frame.py 找），輸出 plate.jpg。
       違規那一秒的車牌通常不清楚，⛔ 不能只附違規時間點的截圖，一定要另附這張（2026-10-02 使用者定案）。

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
    ap.add_argument("--crop", help="檢舉影片的裁切範圍 x,y,w,h 比例（放大車牌用）；省略＝不裁切")
    ap.add_argument("--photos", help="證據截圖的原始影片秒數，逗號分隔，例 114.4,116.3")
    ap.add_argument("--plate-photo", type=float, help="行進中車牌最清楚那一格的原始影片秒數（best_plate_frame.py 找出），輸出 plate.jpg")
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
    photos = [float(x) for x in a.photos.split(",")] if a.photos else []
    # 截圖約各 1 MB，先從影片的額度裡扣掉，讓影片＋截圖合計不超過上限
    n_stills = len(photos) + (1 if a.plate_photo is not None else 0)
    clip_mb = max(5, lim["max_mb"] - 1.2 * n_stills)
    clip_args = [HERE / "clip_video.py", str(src), "--center", a.at, "--before", str(a.before), "--after", str(a.after),
                 "--max-mb", str(clip_mb), "--out", str(case_dir / "clip.mp4")]
    if a.crop: clip_args += ["--crop", a.crop]
    clip = run_json(clip_args)
    # 5b. 證據截圖：原始解析度、同樣裁切、不縮放
    vf = []
    if a.crop and clip.get("crop_px"): vf = ["-vf", "crop=" + clip["crop_px"]]
    for i, t in enumerate(photos, 1):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", *vf, "-q:v", "2",
                        str(case_dir / f"photo{i}.jpg")], capture_output=True)
    if a.plate_photo is not None:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a.plate_photo:.3f}", "-i", str(src), "-frames:v", "1", *vf, "-q:v", "2",
                        str(case_dir / "plate.jpg")], capture_output=True)
    if lim.get("max_files") and 1 + n_stills > lim["max_files"]:
        print(f"⚠️ 該縣市最多 {lim['max_files']} 個檔，現在有 {1 + n_stills} 個（影片＋截圖），上傳時依「影片＞車牌截圖＞違規截圖」的順序取捨", file=sys.stderr)
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
            "clip": clip, "crop": a.crop, "photos": [f"photo{i}.jpg @ {t}s" for i, t in enumerate(photos, 1)] + ([f"plate.jpg @ {a.plate_photo}s（最清楚車牌）"] if a.plate_photo is not None else []), "limits": lim, "frames_dir": str(frames), "created": datetime.datetime.now().isoformat(timespec="seconds"),
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
