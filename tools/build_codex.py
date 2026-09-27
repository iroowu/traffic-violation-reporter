#!/usr/bin/env python3
"""從 Claude 版 skill 產生 Codex 版：scripts／references／assets 原樣複製，SKILL.md 換掉只有 Claude 才有的機制。

用法：
  python3 tools/build_codex.py <claude_skill_dir> <codex_out_dir>
  例：python3 tools/build_codex.py claude/traffic-violation-reporter codex/traffic-violation-reporter

兩邊必須同源：改了 Claude 版之後重跑這支，⛔ 不要手改 Codex 版。
"""
import pathlib, shutil, sys

# Claude 專屬機制 → Codex 的對應寫法（原文必須完全對中，對不中會印警告）
PLATFORM = [
    ("填網站需要能操作瀏覽器的工具（Claude in Chrome 擴充功能，或同等的瀏覽器自動化工具）；",
     "填網站需要能操作瀏覽器的工具（Codex 桌面版的電腦操作功能，或同等的瀏覽器自動化工具）；"),
    ("有選擇題工具就用選擇題讓使用者點；沒有就列表請使用者回「都對」或指出哪一項要改。",
     "把六項列成編號清單，請使用者回「都對」或指出哪一項要改。"),
    ("2. 用瀏覽器工具開網址。第一次到該站可能要使用者在瀏覽器裡按「允許」。",
     "2. 用瀏覽器工具開網址；沒有瀏覽器工具就把「網址＋每一欄要填的值」整理成一張表給使用者自己貼。"),
    ("## 流程總覽",
     "## Codex 專屬：防當機\n\n"
     "這個 skill 會抽出幾十到上百張畫面。⛔ **一次只開一張圖看，看完就換下一張**，不要把整個 `frames/` 夾一次載進對話，"
     "也不要把圖片以 base64 貼進訊息，那會把桌面版的對話檔撐爆。剪片、抽幀這些長工用腳本跑，讓它輸出檔案與統計數字，圖本身不進對話。\n\n"
     "## 流程總覽"),
]
HEADER = ("\n> 這是 Codex 版，與 Claude 版同源（同一份 scripts／references／assets）。"
          "\n> 改動請改 Claude 版再用 `tools/build_codex.py` 重建，⛔ 不要只改這一邊。\n")

def main():
    if len(sys.argv) != 3: sys.exit(__doc__)
    src, dst = pathlib.Path(sys.argv[1]).expanduser(), pathlib.Path(sys.argv[2]).expanduser()
    dst.mkdir(parents=True, exist_ok=True)
    for sub in ("scripts", "references", "assets"):
        d = dst / sub
        if d.exists(): shutil.rmtree(d)
        shutil.copytree(src / sub, d, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    s = (src / "SKILL.md").read_text(encoding="utf-8")
    for a, b in PLATFORM:
        if a not in s: print(f"⚠️ 平台替換沒對中，Claude 版原文可能改過：{a[:40]}")
        s = s.replace(a, b)
    # 標題行之後插入來源說明
    lines = s.split("\n"); idx = next(i for i, l in enumerate(lines) if l.startswith("# "))
    lines.insert(idx + 1, HEADER)
    s = "\n".join(lines)
    (dst / "SKILL.md").write_text(s, encoding="utf-8")
    left = [w for w in ("Claude in Chrome", "AskUserQuestion", "SendUserFile") if w in s]
    print(f"Codex 版已產生 → {dst}"); print("殘留 Claude 專屬字樣:", left or "無")

if __name__ == "__main__":
    main()
