#!/usr/bin/env python3
"""從行車記錄器原始影片剪出違規片段，並壓到指定大小以下（各縣市上傳上限不同）。

用法：
  python3 clip_video.py 原始.MP4 --start 00:01:23 --end 00:01:41 --max-mb 20 --out 檢舉片段.mp4
  python3 clip_video.py 原始.MP4 --center 00:01:32 --before 8 --after 8 --max-mb 20 --out 檢舉片段.mp4

原則：
- 保留違規前後各數秒，讓審核員看得到「號誌狀態、車輛動線、車牌」的完整脈絡。
- 先嘗試不重新編碼（-c copy，畫質零損失、速度最快）；超過大小上限才重新編碼，逐步降碼率直到達標。
- 一律輸出 H.264 + AAC 的 .mp4，這是所有縣市系統都收的格式。
- 不加任何濾鏡、不裁切、不加字幕：檢舉影片必須是原始畫面，加工反而會被質疑。
"""
import argparse, json, pathlib, subprocess, sys

def hms_to_sec(s):
    if s is None: return None
    parts = [float(x) for x in str(s).split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return parts[0]*3600 + parts[1]*60 + parts[2]

def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg 失敗：\n" + r.stderr[-2000:])

def size_mb(p): return pathlib.Path(p).stat().st_size / 1024 / 1024

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--center"); ap.add_argument("--before", type=float, default=8); ap.add_argument("--after", type=float, default=8)
    ap.add_argument("--max-mb", type=float, required=True, help="該縣市系統的單檔上限（MB）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-height", type=int, default=1080, help="重新編碼時的最大高度，預設 1080")
    a = ap.parse_args()

    dur = probe_duration(a.src)
    if a.center:
        c = hms_to_sec(a.center); start = max(0, c - a.before); end = min(dur, c + a.after)
    else:
        start = hms_to_sec(a.start) or 0; end = hms_to_sec(a.end) or dur
    if end <= start: sys.exit("結束時間必須晚於開始時間")
    length = end - start
    out = pathlib.Path(a.out)

    # 第一輪：不重新編碼
    run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", a.src, "-t", f"{length:.3f}",
         "-c", "copy", "-movflags", "+faststart", "-map", "0:v:0", "-map", "0:a?", str(out)])
    mode = "copy"
    if size_mb(out) > a.max_mb:
        # 第二輪起：重新編碼，目標碼率留 8% 餘裕
        target_kbps = int(a.max_mb * 8192 * 0.92 / length) - 96  # 扣掉音訊 96k
        attempt = 0
        while True:
            attempt += 1
            vf = f"scale=-2:'min({a.max_height},ih)'"
            run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", a.src, "-t", f"{length:.3f}",
                 "-map", "0:v:0", "-map", "0:a?", "-vf", vf,
                 "-c:v", "libx264", "-preset", "medium", "-b:v", f"{target_kbps}k", "-maxrate", f"{int(target_kbps*1.1)}k",
                 "-bufsize", f"{target_kbps*2}k", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)])
            mode = f"reencode@{target_kbps}k"
            if size_mb(out) <= a.max_mb or attempt >= 4: break
            target_kbps = int(target_kbps * 0.8)
    ok = size_mb(out) <= a.max_mb
    print(json.dumps({"out": str(out), "start_sec": round(start, 2), "end_sec": round(end, 2), "length_sec": round(length, 2),
                      "size_mb": round(size_mb(out), 2), "limit_mb": a.max_mb, "mode": mode, "within_limit": ok},
                     ensure_ascii=False, indent=2))
    if not ok: sys.exit(2)

if __name__ == "__main__":
    main()
