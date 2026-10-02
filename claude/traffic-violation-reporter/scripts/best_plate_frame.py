#!/usr/bin/env python3
"""在一段影片裡鎖定違規車的車牌、逐格追蹤，找出「行進中車牌拍得最清楚」的那一格。

為什麼要這張：違規那一秒通常離得遠或在晃，車牌不清楚；審核員要能單獨從一張圖讀出完整車號，
所以檢舉一定要另附一張車牌最清楚的截圖（2026-10-02 使用者定案）。

用法：
  # 1. 先用 extract_frames.py 抽一張車子離你最近的畫面，看出車牌在原始畫面裡的位置（像素，左上角 x,y 與寬高）
  # 2. 從那一秒往前後追蹤，列出最清楚的幾格，並輸出一張放大對照圖讓人用眼睛確認
  python3 best_plate_frame.py 原始.MP4 --seed 109.0 --box 1508,1437,52,26 --start 104 --end 114 --sheet 車牌候選.jpg
輸出：JSON，best_sec＝最清楚那一格在原始影片的秒數；接著把它交給 build_case.py --plate-photo。

方法：以 seed 那一格的車牌為範本，逐格做正規化互相關（normalized cross-correlation）追蹤位置，
再用車牌區塊的邊緣強度（字越銳利分數越高）排序。只用 numpy 與 Pillow。
⚠️ 分數只是排序參考，一定要開 --sheet 對照圖用眼睛確認每一碼都讀得出來；相關係數（corr）低於 0.8 代表可能追丟了。
"""
import argparse, json, pathlib, subprocess, sys, tempfile

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--seed", type=float, required=True, help="車牌位置已知的那一秒（原始影片秒數）")
    ap.add_argument("--box", required=True, help="seed 那一秒車牌在原始畫面的 x,y,w,h（像素）")
    ap.add_argument("--start", type=float, required=True); ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--sheet", help="輸出前 6 名的放大對照圖")
    a = ap.parse_args()
    import numpy as np
    from PIL import Image, ImageDraw
    bx, by, bw, bh = [int(v) for v in a.box.split(",")]
    # 只解碼車牌周圍一大塊，省記憶體
    pad = 400
    cx0, cy0 = max(0, bx - pad), max(0, by - pad)
    cw, ch = bw + pad * 2, bh + pad * 2
    tmp = pathlib.Path(tempfile.mkdtemp())
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a.start:.3f}", "-i", a.src, "-t", f"{a.end - a.start:.3f}",
                        "-vf", f"fps={a.fps},crop={cw}:{ch}:{cx0}:{cy0}:exact=1,format=gray", str(tmp / "f%05d.png")],
                       capture_output=True, text=True)
    if r.returncode != 0: sys.exit("ffmpeg 失敗：" + r.stderr[-800:])
    fs = sorted(tmp.glob("f*.png")); n = len(fs)
    if not n: sys.exit("沒有抽到畫面，檢查 --start／--end")
    load = lambda i: np.array(Image.open(fs[i])).astype(float)
    i0 = min(n - 1, max(0, round((a.seed - a.start) * a.fps)))
    x0, y0 = bx - cx0, by - cy0
    seq = {}

    def track(rng):
        x, y = x0, y0
        T = load(i0)[y:y + bh, x:x + bw]
        for i in rng:
            A = load(i); best = (-2, x, y)
            for dy in range(-12, 13):
                for dx in range(-16, 17):
                    P = A[y + dy:y + dy + bh, x + dx:x + dx + bw]
                    if P.shape != T.shape: continue
                    p = P - P.mean(); t = T - T.mean()
                    c = (p * t).sum() / np.sqrt((p * p).sum() * (t * t).sum() + 1e-9)
                    if c > best[0]: best = (c, x + dx, y + dy)
            c, x, y = best
            T = A[y:y + bh, x:x + bw]
            sharp = np.abs(np.diff(T, 1, 1)).mean() + np.abs(np.diff(T, 1, 0)).mean()
            seq[i] = (float(round(c, 3)), x + cx0, y + cy0, float(round(sharp, 2)))

    track(range(i0, n)); track(range(i0, -1, -1))
    ranked = sorted(seq.items(), key=lambda kv: -kv[1][3] if kv[1][0] >= 0.8 else 0)
    top = [{"sec": round(a.start + i / a.fps, 2), "sharpness": v[3], "corr": v[0], "box": [v[1], v[2], bw, bh]} for i, v in ranked[:6]]
    if a.sheet:
        W = Image.new("RGB", (1440, 240 * 3))
        for k, t in enumerate(top):
            i = round((t["sec"] - a.start) * a.fps)
            im = Image.open(fs[i]).convert("RGB")
            X, Y = t["box"][0] - cx0, t["box"][1] - cy0
            cr = im.crop((X - bw // 2, Y - bh // 2, X + bw * 3 // 2, Y + bh * 3 // 2)).resize((720, 240), Image.LANCZOS)
            ImageDraw.Draw(cr).text((6, 6), f"{t['sec']}s  sharp={t['sharpness']}  corr={t['corr']}", fill=(255, 255, 0))
            W.paste(cr, ((k % 2) * 720, (k // 2) * 240))
        W.save(a.sheet, quality=90)
    for f in fs: f.unlink()
    tmp.rmdir()
    print(json.dumps({"best_sec": top[0]["sec"] if top else None, "top": top, "frames": n, "sheet": a.sheet},
                     ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
