#!/usr/bin/env python3
"""從行車記錄器影片抽出 GPS 軌跡（用 exiftool 的嵌入串流解析），輸出 JSON。

支援：exiftool 13.x 能讀的所有行車記錄器格式（Novatek 晶片機種如 Mio／DOD／Viofo／PAPAGO、Garmin、
BlackVue、Thinkware、70mai、Nextbase、Kenwood、Transcend、Vantrue、Azdome、Akaso、GoPro、DJI、Insta360 等）。

用法：
  python3 extract_gps.py 影片.MP4                 # 印出 JSON
  python3 extract_gps.py 影片.MP4 --out gps.json   # 存檔，給 locate_county.py --json 用
  python3 extract_gps.py 影片.MP4 --at 00:00:12    # 額外回報影片第 12 秒最接近的座標（違規那一刻）

輸出：
{
  "file": "...", "points": [{"time": "2026-09-26 08:12:33+08:00", "sample_sec": 12.0, "lat": 24.81, "lon": 120.97, "speed_kmh": 42.3}, ...],
  "count": 120, "first_time": "...", "last_time": "...", "median": {"lat":..., "lon":...},
  "at": {"sample_sec": 12.0, "lat":..., "lon":..., "time": "..."}   # 只有帶 --at 才有
}
沒有 GPS 時 points 為空，並在 note 說明可能原因（機種沒 GPS 模組、GPS 沒定位到、格式 exiftool 不認得）。
"""
import argparse, json, pathlib, re, shutil, statistics, subprocess, sys
from datetime import datetime, timedelta, timezone

def hms_to_sec(s):
    parts = [float(x) for x in str(s).split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return parts[0]*3600 + parts[1]*60 + parts[2]

def parse_dt(s):
    """exiftool 的 GPSDateTime 格式：2026:09:26 08:12:33Z 或 2026:09:26 08:12:33.500+08:00"""
    if not s: return None
    s = s.strip()
    m = re.match(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:\d{2})?$", s)
    if not m: return None
    y, mo, d, h, mi = map(int, m.groups()[:5]); sec = float(m.group(6)); tz = m.group(7)
    dt = datetime(y, mo, d, h, mi, int(sec), int((sec % 1) * 1e6))
    if tz == "Z" or tz is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        sign = 1 if tz[0] == "+" else -1
        dt = dt.replace(tzinfo=timezone(sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6]))))
    return dt

def parse_rmc_line(line):
    """解 NMEA 的 $GPRMC／$GNRMC 句，回傳 (datetime_utc, lat, lon, speed_kmh) 或 None。不依賴 pynmea2。"""
    if not line.startswith(("$GPRMC", "$GNRMC")): return None
    f = line.strip().split("*")[0].split(",")
    if len(f) < 10 or f[2] != "A" or not f[3] or not f[5]: return None
    try:
        t, d = f[1], f[9]
        hh, mm, ss = int(t[0:2]), int(t[2:4]), float(t[4:])
        dd, mo, yy = int(d[0:2]), int(d[2:4]), 2000 + int(d[4:6])
        dt = datetime(yy, mo, dd, hh, mm, int(ss), int((ss % 1) * 1e6), tzinfo=timezone.utc)
        def nmea_deg(v, hemi, width):
            deg = int(v[:width]); minutes = float(v[width:]); val = deg + minutes / 60
            return -val if hemi in ("S", "W") else val
        lat = nmea_deg(f[3], f[4], 2); lon = nmea_deg(f[5], f[6], 3)
        spd = float(f[7]) * 1.852 if f[7] else None
        return dt, lat, lon, spd
    except (ValueError, IndexError):
        return None

def find_sidecar(src):
    """找與影片同資料夾的 GPS 旁檔：Mio／PAPAGO／BlackVue 舊機的同名 .NMEA .nmea .gps，70mai 的 GPSData*.txt，Tesla 的 event.json。"""
    folder = src.parent
    for ext in (".NMEA", ".nmea", ".gps", ".GPS", ".txt", ".TXT"):
        cand = src.with_suffix(ext)
        if cand.exists() and cand != src: return cand, "nmea"
    for cand in sorted(folder.glob("GPSData*.txt")) + sorted(folder.glob("GPSData*.TXT")):
        return cand, "70mai"
    ev = folder / "event.json"
    if ev.exists(): return ev, "tesla"
    return None, None

def points_from_sidecar(path, kind, out_tz):
    pts = []
    if kind == "nmea":
        for line in path.read_text(errors="ignore").splitlines():
            r = parse_rmc_line(line)
            if r:
                dt, lat, lon, spd = r
                pts.append({"time": dt.astimezone(out_tz).replace(microsecond=0).isoformat(sep=" "), "sample_sec": None,
                            "lat": round(lat, 6), "lon": round(lon, 6), "speed_kmh": round(spd, 1) if spd is not None else None})
    elif kind == "70mai":
        # 每行：unix_time, A/V, lat, lon, heading, speed(cm/s), ...（依 dashcamtalk 整理的格式）
        for line in path.read_text(errors="ignore").splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) < 4 or f[1] != "A": continue
            try:
                dt = datetime.fromtimestamp(int(f[0]), tz=timezone.utc)
                spd = float(f[5]) * 0.036 if len(f) > 5 and f[5] else None
                pts.append({"time": dt.astimezone(out_tz).isoformat(sep=" "), "sample_sec": None,
                            "lat": round(float(f[2]), 6), "lon": round(float(f[3]), 6), "speed_kmh": round(spd, 1) if spd is not None else None})
            except ValueError: continue
    elif kind == "tesla":
        try:
            e = json.loads(path.read_text(encoding="utf-8"))
            lat, lon = float(e.get("est_lat")), float(e.get("est_lon"))
            pts.append({"time": e.get("timestamp"), "sample_sec": None, "lat": round(lat, 6), "lon": round(lon, 6), "speed_kmh": None,
                        "note": f"Tesla event.json 只有事件估計座標（{e.get('city')}），不是逐秒軌跡"})
        except (ValueError, TypeError, json.JSONDecodeError): pass
    # 旁檔沒有 SampleTime：用第一筆時間當影片 0 秒推算
    if pts and pts[0].get("time"):
        try:
            t0 = datetime.fromisoformat(pts[0]["time"])
            for p in pts:
                if p.get("time"): p["sample_sec"] = round((datetime.fromisoformat(p["time"]) - t0).total_seconds(), 2)
        except ValueError: pass
    return pts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--out"); ap.add_argument("--at")
    ap.add_argument("--tz", default="+08:00", help="輸出時間要換成的時區，預設台灣 +08:00")
    ap.add_argument("--diagnose", action="store_true", help="不認得的機種用：列出影片的軌道、含 GPS 字樣的區塊、同資料夾檔案，幫助判斷 GPS 藏在哪")
    a = ap.parse_args()
    if a.diagnose:
        src = pathlib.Path(a.src)
        print("== ffprobe 軌道（有 subtitle／data／text 軌通常就是 GPS）==")
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,codec_tag_string:stream_tags=handler_name",
                            "-of", "compact", str(src)], capture_output=True, text=True); print(r.stdout or r.stderr[-500:])
        print("== exiftool 主檔資訊 ==")
        r = subprocess.run(["exiftool", "-G3", "-a", "-s", "-Make", "-Model", "-HandlerDescription", "-CompressorName", "-Software", "-Encoder",
                            "-MajorBrand", "-CompatibleBrands", str(src)], capture_output=True, text=True); print(r.stdout)
        print("== exiftool -ee3 抓到的 GPS 相關標籤（前 20 行）==")
        r = subprocess.run(["exiftool", "-ee3", "-api", "LargeFileSupport=1", "-G3", "-a", "-s", "-gps*", "-SampleTime", "-Accelerometer", str(src)], capture_output=True, text=True)
        lines = r.stdout.splitlines(); print("\n".join(lines[:20]) or "（沒有）"); print(f"（共 {len(lines)} 行）")
        print("== 檔案裡的 GPS 字樣（前 1 MB 與最後 1 MB 各掃一次，看是哪一派）==")
        data = src.read_bytes()
        head, tail = data[:1_000_000], data[-1_000_000:]
        for tag in [b"freeGPS", b"GPS ", b"LIGOGPSINFO", b"$GPRMC", b"$GNRMC", b"gpmd", b"camm", b"GPSDATA", b"gps0", b"nbmt", b"PNDM", b"udta"]:
            n = head.count(tag) + tail.count(tag)
            if n: print(f"  {tag!r}: {n} 次")
        print("== 同資料夾的非影片檔（旁檔候選）==")
        for f in sorted(src.parent.iterdir()):
            if f.is_file() and f.suffix.lower() not in (".mp4", ".mov", ".avi", ".ts", ".mkv") and f.stat().st_size < 50_000_000:
                print(f"  {f.name}  {f.stat().st_size:,} bytes")
        return
    if not shutil.which("exiftool"):
        sys.exit("找不到 exiftool，請先安裝（macOS: brew install exiftool）")
    src = pathlib.Path(a.src)
    r = subprocess.run(["exiftool", "-ee3", "-G3", "-j", "-n", "-api", "LargeFileSupport=1",
                        "-GPSLatitude", "-GPSLongitude", "-GPSDateTime", "-GPSSpeed", "-GPSSpeedRef", "-SampleTime", "-GPSTrack",
                        "-CreateDate", "-MediaCreateDate", "-Duration", "-Make", "-Model", "-HandlerDescription", "-CompressorName",
                        str(src)], capture_output=True, text=True)
    if r.returncode not in (0, 1) or not r.stdout.strip():
        sys.exit("exiftool 失敗：" + r.stderr[-1000:])
    data = json.loads(r.stdout)[0]
    # 主檔（Main）的欄位與各嵌入文件（Doc1, Doc2...）的欄位混在同一個 dict，用 group 前綴分開
    main = {k.split(":", 1)[1]: v for k, v in data.items() if k.startswith("Main:")}
    docs = {}
    for k, v in data.items():
        if k.startswith("Doc"):
            g, name = k.split(":", 1)
            # 群組名可能是 Doc12 或 Doc1-3（子文件），轉成整數元組好排序
            key = tuple(int(x) for x in re.findall(r"\d+", g))
            docs.setdefault(key, {})[name] = v
    sign = 1 if a.tz[0] == "+" else -1
    out_tz = timezone(sign * timedelta(hours=int(a.tz[1:3]), minutes=int(a.tz[4:6])))
    points = []
    for i in sorted(docs):
        d = docs[i]
        lat, lon = d.get("GPSLatitude"), d.get("GPSLongitude")
        if lat is None or lon is None: continue
        try: lat, lon = float(lat), float(lon)
        except (TypeError, ValueError): continue
        if lat == 0 and lon == 0: continue          # 未定位的空值
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): continue
        spd = d.get("GPSSpeed"); ref = (d.get("GPSSpeedRef") or "").upper()
        if spd is not None:
            spd = float(spd)
            if ref in ("N", "KNOTS"): spd *= 1.852
            elif ref in ("M", "MPH"): spd *= 1.609
        dt = parse_dt(str(d.get("GPSDateTime", "")))
        points.append({"time": dt.astimezone(out_tz).replace(microsecond=0).isoformat(sep=" ") if dt else None,
                       "sample_sec": float(d["SampleTime"]) if d.get("SampleTime") is not None else None,
                       "lat": round(lat, 6), "lon": round(lon, 6),
                       "speed_kmh": round(spd, 1) if spd is not None else None})
    # 高頻機種（GoPro 18Hz 等）只有每秒第一個點帶時間戳，其餘用 SampleTime 差推回去
    # 子文件（同一秒內的多個點）常常連 SampleTime 也沒有：先繼承上一個有值的 SampleTime，再往下推時間
    last_sec = None
    for p in points:
        if p["sample_sec"] is None: p["sample_sec"] = last_sec
        else: last_sec = p["sample_sec"]
    last_dt, last_sec = None, None
    for p in points:
        if p["time"]:
            last_dt, last_sec = datetime.fromisoformat(p["time"]), p["sample_sec"]
        elif last_dt is not None and p["sample_sec"] is not None and last_sec is not None:
            p["time"] = (last_dt + timedelta(seconds=p["sample_sec"] - last_sec)).replace(microsecond=0).isoformat(sep=" ")
    gps_source = "embedded" if points else None
    if not points:
        side, kind = find_sidecar(src)
        if side:
            points = points_from_sidecar(side, kind, out_tz)
            if points: gps_source = f"sidecar:{kind}:{side.name}"
    res = {"file": str(src), "gps_source": gps_source, "make": main.get("Make"), "model": main.get("Model"),
           "handler": main.get("HandlerDescription"), "compressor": main.get("CompressorName"),
           "create_date": main.get("CreateDate") or main.get("MediaCreateDate"), "duration_sec": main.get("Duration"),
           "points": points, "count": len(points)}
    if points:
        res["first_time"] = points[0]["time"]; res["last_time"] = points[-1]["time"]
        res["median"] = {"lat": statistics.median(p["lat"] for p in points), "lon": statistics.median(p["lon"] for p in points)}
        if a.at:
            t = hms_to_sec(a.at)
            with_s = [p for p in points if p["sample_sec"] is not None]
            if with_s:
                res["at"] = min(with_s, key=lambda p: abs(p["sample_sec"] - t))
            elif points[0]["time"]:
                # 沒有 SampleTime 就用第一筆時間加位移推
                t0 = datetime.fromisoformat(points[0]["time"])
                res["at"] = min(points, key=lambda p: abs((datetime.fromisoformat(p["time"]) - t0).total_seconds() - t))
    else:
        res["note"] = ("影片裡讀不到 GPS，同資料夾也沒有旁檔。可能原因：(1) 這台行車記錄器沒有 GPS 模組，或當時沒定位到；"
                       "(2) GPS 存在記憶卡的旁檔（Mio／PAPAGO 的同名 .NMEA、70mai 的 GPSData000001.txt、Tesla 的 event.json），"
                       "請把整個資料夾一起提供；(3) 新韌體加密格式（LIGOGPSINFO）需要 exiftool 13.07 以上。"
                       "替代做法：看畫面下方燒錄的座標與時間水印，或請使用者直接說違規路口。")
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        brief = {k: v for k, v in res.items() if k != "points"}
        print(json.dumps(brief, ensure_ascii=False, indent=2)); print(f"→ 完整軌跡已存 {a.out}")
    else:
        print(text)

if __name__ == "__main__":
    main()
