#!/usr/bin/env python3
"""檢舉人基本資料檔：第一次使用建立，之後每次檢舉自動帶入，不必重打。

存放位置：~/.traffic-reporter/profile.json（使用者自己的電腦，不在 skill 資料夾內，換 skill 版本也不會丟）。

⛔ 這個檔「絕對不存」身分證字號、密碼、任何憑證。
   身分證字號是政府核發的身分識別碼，各縣市系統雖然要填，但一律由使用者本人在瀏覽器裡親自輸入。
   小精靈只帶入姓名、電話、電子郵件、通訊地址這些聯絡資料。

用法：
  python3 profile.py show
  python3 profile.py set --name 王小明 --phone 0912345678 --email me@example.com --address "新竹縣竹北市○○路1號"
  python3 profile.py set --phone 0987654321         # 只改一欄
  python3 profile.py clear
"""
import argparse, json, pathlib, sys

PROFILE = pathlib.Path.home() / ".traffic-reporter" / "profile.json"
FIELDS = ["name", "phone", "email", "address"]
LABELS = {"name": "姓名", "phone": "手機", "email": "電子郵件", "address": "通訊地址"}
FORBIDDEN = ["id", "id_no", "national_id", "idcard", "password", "pwd", "身分證", "密碼"]

def load():
    if PROFILE.exists():
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    return {}

def save(d):
    for k in d:
        if any(f in k.lower() for f in FORBIDDEN):
            sys.exit(f"拒絕儲存欄位「{k}」：身分證字號與密碼一律不落地。")
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    PROFILE.chmod(0o600)

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    s = sub.add_parser("set")
    for f in FIELDS: s.add_argument(f"--{f}")
    sub.add_parser("clear")
    a = ap.parse_args()
    if a.cmd == "show":
        d = load()
        if not d:
            print(json.dumps({"exists": False, "hint": "尚未建立，請用 set 建立"}, ensure_ascii=False)); return
        missing = [LABELS[f] for f in FIELDS if not d.get(f)]
        print(json.dumps({"exists": True, "profile": d, "missing": missing, "path": str(PROFILE)}, ensure_ascii=False, indent=2))
    elif a.cmd == "set":
        d = load()
        for f in FIELDS:
            v = getattr(a, f)
            if v: d[f] = v.strip()
        save(d)
        print(json.dumps({"saved": True, "profile": d, "path": str(PROFILE)}, ensure_ascii=False, indent=2))
    elif a.cmd == "clear":
        if PROFILE.exists(): PROFILE.unlink()
        print(json.dumps({"cleared": True}, ensure_ascii=False))

if __name__ == "__main__":
    main()
