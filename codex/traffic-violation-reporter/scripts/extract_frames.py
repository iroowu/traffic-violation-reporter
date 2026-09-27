#!/usr/bin/env python3
"""從影片抽出關鍵畫面，讓 Claude 用視覺判讀違規事實與車牌。

用法：
  python3 extract_frames.py 影片.mp4 --out-dir frames/            # 每秒 1 張（預設）
  python3 extract_frames.py 影片.mp4 --out-dir frames/ --fps 2     # 每秒 2 張
  python3 extract_frames.py 影片.mp4 --out-dir frames/ --at 00:00:12 --at 00:00:13.5   # 只抽指定時間點
  python3 extract_frames.py 影片.mp4 --out-dir frames/ --at 12 --crop 0.45,0.55,0.35,0.30   # 放大車牌區（x,y,w,h 皆為 0 到 1 的比例）

抽出的圖統一縮到寬 1280，檔名帶秒數（f_0012.50.jpg），方便回頭對應時間碼。
--crop 會額外輸出放大 2 倍的裁切圖（crop_0012.50.jpg），看車牌用。
"""
import argparse, pathlib, subprocess, sys

def hms_to_sec(s):
    parts = [float(x) for x in str(s).split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return parts[0]*3600 + parts[1]*60 + parts[2]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--out-dir", required=True)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--at", action="append", help="指定時間點，可重複")
    ap.add_argument("--crop", help="x,y,w,h 比例，放大車牌區")
    ap.add_argument("--width", type=int, default=1280)
    a = ap.parse_args()
    out = pathlib.Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    made = []
    if a.at:
        for t in a.at:
            sec = hms_to_sec(t)
            f = out / f"f_{sec:07.2f}.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{sec:.3f}", "-i", a.src, "-frames:v", "1",
                            "-vf", f"scale={a.width}:-2", "-q:v", "2", str(f)], check=True)
            made.append(str(f))
            if a.crop:
                x, y, w, h = [float(v) for v in a.crop.split(",")]
                c = out / f"crop_{sec:07.2f}.jpg"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{sec:.3f}", "-i", a.src, "-frames:v", "1",
                                "-vf", f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale=iw*2:ih*2:flags=lanczos", "-q:v", "2", str(c)], check=True)
                made.append(str(c))
    else:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a.src, "-vf", f"fps={a.fps},scale={a.width}:-2",
                        "-q:v", "3", "-frame_pts", "1", str(out / "f_%06d.jpg")], check=True)
        made = sorted(str(p) for p in out.glob("f_*.jpg"))
    print(f"抽出 {len(made)} 張到 {out}")
    for m in made[:60]: print(m)
    if len(made) > 60: print(f"... 共 {len(made)} 張")

if __name__ == "__main__":
    main()
