#!/usr/bin/env python3
"""從行車記錄器原始影片剪出違規片段，裁切放大車牌，並壓到指定大小以下（各縣市上傳上限不同）。

用法：
  # 先看裁切框會不會切掉號誌或水印（每秒一格，紫框＝要保留的範圍），不產影片
  python3 clip_video.py 原始.MP4 --center 00:01:56 --before 12 --after 4 --crop 0,0.333,0.667,0.667 --preview 預覽.jpg
  # 正式產出
  python3 clip_video.py 原始.MP4 --center 00:01:56 --before 12 --after 4 --crop 0,0.333,0.667,0.667 --max-mb 50 --out clip.mp4
  python3 clip_video.py 原始.MP4 --start 00:01:44 --end 00:01:59.5 --max-mb 20 --out clip.mp4      # 不裁切

原則（2026-10-02 使用者定案）：
- 以「車牌放大」為主：裁掉跟違規無關的天空、引擎蓋、路邊，讓車牌在畫面裡的比例越大越好，檢舉成功率越高。
- 裁切一定要保留三樣：① 違規事實（同向號誌、停止線、違規車的完整動線）② 行車記錄器資訊（日期時間水印、車速，通常在左下）
  ③ 看得出地點與環境的範圍（路名牌、路口樣貌）。用 --preview 逐秒確認三樣都在框內才正式產出。
- 只裁切、不放大重取樣、不加字、不調色、不變速、不拼接。裁切後的像素就是原始像素。
- ⛔ 不縮小解析度：4K 縮成 1080p 車牌會糊到讀不出來（2026-10-02 實測）。預設保留原解析度，只靠碼率控制檔案大小。
- 不裁切時先嘗試不重新編碼（-c copy）；有裁切或超過大小上限才重新編碼（兩階段編碼，同樣大小畫質最好）。
- 一律輸出 H.264 + AAC 的 .mp4，所有縣市系統都收。
- 重新編碼後把原始檔的拍攝時間等中繼資料抄回去（新竹縣等明文要求「剪輯轉檔仍須保留原始檔 EXIF」）。
--crop 為 x,y,w,h，皆為 0 到 1 的比例（以原始畫面為準），左上角為原點。
"""
import argparse, json, pathlib, subprocess, sys, tempfile

def hms_to_sec(s):
    if s is None: return None
    parts = [float(x) for x in str(s).split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return parts[0]*3600 + parts[1]*60 + parts[2]

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    return float(j["format"]["duration"]), int(j["streams"][0]["width"]), int(j["streams"][0]["height"])

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg 失敗：\n" + r.stderr[-2000:])

def size_mb(p): return pathlib.Path(p).stat().st_size / 1024 / 1024

def copy_dates(src, out):
    """把原始檔的拍攝時間等中繼資料抄到剪輯檔（多數縣市要求剪輯轉檔後仍保留原始檔的 EXIF／建立時間）。
    只改中繼資料、不動畫面；沒有 exiftool 就略過（ffmpeg 已帶上 creation_time）。"""
    import shutil
    if not shutil.which("exiftool"): return
    subprocess.run(["exiftool", "-q", "-overwrite_original", "-tagsFromFile", str(src),
                    "-QuickTime:CreateDate", "-QuickTime:ModifyDate", "-Track1:TrackCreateDate", "-Track1:TrackModifyDate",
                    "-Track1:MediaCreateDate", "-Track1:MediaModifyDate", "-Track2:all", "-Make", "-Model", str(out)],
                   capture_output=True)

def crop_px(crop, W, H):
    """比例 → 偶數像素的 ffmpeg crop 參數 w:h:x:y"""
    x, y, w, h = [float(v) for v in crop.split(",")]
    cw = int(W * w) // 2 * 2; ch = int(H * h) // 2 * 2
    cx = min(int(W * x) // 2 * 2, W - cw); cy = min(int(H * y) // 2 * 2, H - ch)
    return cw, ch, cx, cy

def preview(src, start, length, box, W, H, out):
    """每秒抽一張，畫上裁切框，拼成一張總覽圖，讓人確認號誌與水印有沒有被切掉。"""
    from PIL import Image, ImageDraw  # 只有預覽需要 Pillow
    tmp = pathlib.Path(tempfile.mkdtemp())
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{length:.3f}",
         "-vf", "fps=1", "-q:v", "3", str(tmp / "p%03d.jpg")])
    fs = sorted(tmp.glob("p*.jpg"))
    cw, ch, cx, cy = box
    tw = 480; th = int(tw * H / W); cols = 4; rows = (len(fs) + cols - 1) // cols
    sheet = Image.new("RGB", (tw * cols, th * rows))
    for i, f in enumerate(fs):
        im = Image.open(f); d = ImageDraw.Draw(im)
        d.rectangle((cx, cy, cx + cw - 1, cy + ch - 1), outline=(255, 0, 255), width=max(4, W // 320))
        d.text((10, 10), f"+{i}s", fill=(255, 255, 0))
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
        f.unlink()
    tmp.rmdir()
    sheet.save(out, quality=82)
    return len(fs)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--center"); ap.add_argument("--before", type=float, default=8); ap.add_argument("--after", type=float, default=8)
    ap.add_argument("--crop", help="裁切範圍 x,y,w,h（0 到 1 的比例）；省略＝不裁切")
    ap.add_argument("--preview", help="只輸出裁切框總覽圖到這個路徑，不產影片")
    ap.add_argument("--max-mb", type=float, help="該縣市系統的單檔上限（MB）")
    ap.add_argument("--out")
    ap.add_argument("--max-height", type=int, default=0, help="重新編碼時的最大高度；0＝保留原解析度（預設，⛔ 不建議縮小）")
    a = ap.parse_args()

    dur, W, H = probe(a.src)
    if a.center:
        c = hms_to_sec(a.center); start = max(0, c - a.before); end = min(dur, c + a.after)
    else:
        start = hms_to_sec(a.start) or 0; end = hms_to_sec(a.end) or dur
    if end <= start: sys.exit("結束時間必須晚於開始時間")
    length = end - start
    box = crop_px(a.crop, W, H) if a.crop else None

    if a.preview:
        n = preview(a.src, start, length, box or (W, H, 0, 0), W, H, a.preview)
        print(json.dumps({"preview": a.preview, "frames": n, "source_size": f"{W}x{H}",
                          "crop_px": f"{box[0]}x{box[1]} 起點({box[2]},{box[3]})" if box else None,
                          "zoom": round(W / box[0], 2) if box else 1.0}, ensure_ascii=False, indent=2))
        return
    if not (a.max_mb and a.out): sys.exit("正式產出需要 --max-mb 與 --out")
    out = pathlib.Path(a.out)

    vf = []
    if box: vf.append("crop={}:{}:{}:{}".format(*box))
    if a.max_height: vf.append(f"scale=-2:'min({a.max_height},ih)'")
    mode = "copy"
    if not vf:
        run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", a.src, "-t", f"{length:.3f}",
             "-c", "copy", "-movflags", "+faststart", "-map", "0:v:0", "-map", "0:a?", str(out)])
    if vf or size_mb(out) > a.max_mb:
        target_kbps = int(a.max_mb * 8192 * 0.92 / length) - 96  # 留 8% 餘裕，扣掉音訊 96k
        target_kbps = min(target_kbps, 40000)
        passlog = str(out.with_suffix("")) + "_2pass"
        attempt = 0
        while True:
            attempt += 1
            common = ["-ss", f"{start:.3f}", "-i", a.src, "-t", f"{length:.3f}", "-map", "0:v:0"]
            vargs = (["-vf", ",".join(vf)] if vf else []) + ["-c:v", "libx264", "-preset", "slow", "-b:v", f"{target_kbps}k",
                     "-maxrate", f"{int(target_kbps*1.4)}k", "-bufsize", f"{target_kbps*2}k", "-pix_fmt", "yuv420p",
                     "-passlogfile", passlog]
            run(["ffmpeg", "-y", *common, *vargs, "-pass", "1", "-an", "-f", "mp4", "/dev/null"])
            run(["ffmpeg", "-y", *common, "-map", "0:a?", *vargs, "-pass", "2", "-c:a", "aac", "-b:a", "96k",
                 "-map_metadata", "0", "-map_metadata:s:v", "0:s:v", "-map_metadata:s:a", "0:s:a",
                 "-movflags", "+faststart", str(out)])
            mode = f"reencode@{target_kbps}k" + (f" crop={box[0]}x{box[1]}" if box else "")
            if size_mb(out) <= a.max_mb or attempt >= 4: break
            target_kbps = int(target_kbps * 0.85)
        for f in pathlib.Path(passlog).parent.glob(pathlib.Path(passlog).name + "*"): f.unlink()
    copy_dates(a.src, out)
    ok = size_mb(out) <= a.max_mb
    print(json.dumps({"out": str(out), "start_sec": round(start, 2), "end_sec": round(end, 2), "length_sec": round(length, 2),
                      "source_size": f"{W}x{H}", "crop_px": "{}:{}:{}:{}".format(*box) if box else None,
                      "size_mb": round(size_mb(out), 2), "limit_mb": a.max_mb, "mode": mode, "within_limit": ok},
                     ensure_ascii=False, indent=2))
    if not ok: sys.exit(2)

if __name__ == "__main__":
    main()
