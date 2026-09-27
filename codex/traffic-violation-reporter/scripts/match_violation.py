#!/usr/bin/env python3
"""把判讀出的違規類型，對到「該縣市檢舉表單的法條選單」裡的那一項，並印出填表小抄。

用法：
  python3 match_violation.py --list                          # 列出所有可判讀的違規類型（id、名稱、條號、可否檢舉）
  python3 match_violation.py --county 新竹縣 --violation red_light
  python3 match_violation.py --county 臺南市 --violation no_signal_lane_change --json

資料來源：assets/violations.json（法條與各縣市選單常見關鍵字）、references/counties.json（各縣市選單原文）。
比對方式：先用 option_keywords 逐字找該縣市選單裡包含關鍵字的選項，再用條號簡碼（如 53、42、44-2）比對，
兩者都找不到就回報「請人工在選單裡挑」並列出該縣市全部選項讓人挑。
"""
import argparse, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
VIOL = HERE.parent / "assets" / "violations.json"
COUNTIES = HERE.parent / "references" / "counties.json"

def load(p, what):
    if not p.exists(): sys.exit(f"找不到 {what}：{p}")
    return json.loads(p.read_text(encoding="utf-8"))

def norm(s):
    return re.sub(r"[\s（）()【】\[\]、，,／/。．\.:：－—\-_「」『』]", "", str(s)).replace("臺", "台").replace("佔", "占").replace("暸", "了")

def article_tokens(article_short):
    """'53-1' → ['53-1','53']；'44-2' → ['44-2','44']；'56-1-10' → ['56-1-10','56-1','56']"""
    parts = str(article_short).split("-")
    return ["-".join(parts[:i]) for i in range(len(parts), 0, -1)]

CN_NUM = {str(i): c for i, c in enumerate("零一二三四五六七八九")}
def to_cn(n):
    n = int(n)
    if n < 10: return CN_NUM[str(n)]
    if n < 20: return "十" + (CN_NUM[str(n % 10)] if n % 10 else "")
    if n < 100: return CN_NUM[str(n // 10)] + "十" + (CN_NUM[str(n % 10)] if n % 10 else "")
    return str(n)

def chinese_forms(article_short):
    """'56-1-1' → ['第56條第1項第1款', '第五十六條第一項第一款']；'31之1-1' → ['第31條之1第1項', ...]"""
    m = re.match(r"^(\d+)(?:之(\d+))?(?:-(\d+))?(?:-(\d+))?$", str(article_short).replace(" ", ""))
    if not m: return []
    a, zhi, item, sub = m.groups()
    forms = []
    for conv in (lambda x: str(int(x)), to_cn):
        t = f"第{conv(a)}條" + (f"之{conv(zhi)}" if zhi else "") + (f"第{conv(item)}項" if item else "") + (f"第{conv(sub)}款" if sub else "")
        forms.append(t)
    return forms

def score(v, opt):
    """一個選項對某違規類型的相似分數：關鍵字命中數（長關鍵字加權）＋條號命中。"""
    o = norm(opt); sc = 0.0
    compact = re.sub(r"\s+", "", opt)
    for f in chinese_forms(v.get("article_short", "")):
        if f and f in compact:
            # 完整條項款命中；若選項在命中處之後還接著別的項款（例如多寫一個「第10款」）就不算
            tail = compact.split(f, 1)[1][:3]
            if not re.match(r"第[\d一二三四五六七八九十]+[項款]", tail): sc += 3
            break
    for k in v.get("option_keywords", []):
        nk = norm(k)
        if nk and nk in o: sc += 1 + len(nk) / 10
    for i, tok in enumerate(article_tokens(v.get("article_short", ""))):
        if not tok: continue
        pat = re.compile(r"(?<!\d)" + re.escape(tok) + r"(?!\d)")
        if pat.search(opt) or f"第{tok}條" in opt.replace(" ", ""): sc += 2 - i * 0.5; break
    # 「臨時停車」與「停車」是不同條，選項寫臨時而違規名稱沒有臨時（或反過來）就扣分
    if ("臨時" in opt) != ("臨時" in v.get("name", "")): sc -= 1.5
    return sc

def match(v, options, all_items=None):
    """回傳依分數排序的 [(選項, 說明)]。若某選項對「另一個違規類型」的分數更高，就當它是別人的，剔除。"""
    ranked, unfiltered = [], []
    for opt in options:
        sc = score(v, opt)
        if sc <= 0: continue
        unfiltered.append((sc, opt))
        if all_items:
            best_other = max((score(x, opt) for x in all_items if x["id"] != v["id"]), default=0)
            if best_other > sc: continue
        ranked.append((sc, opt))
    if not ranked and unfiltered:
        # 選項同時涵蓋另一個違規類型（例如「闖紅燈/紅燈右轉」合併成一項）：退回用未過濾的結果
        ranked = unfiltered
    ranked.sort(key=lambda t: -t[0])
    if not ranked: return []
    top = ranked[0][0]
    # 分數明顯領先（差 1 分以上）就只回第一個；否則回所有接近的當候選
    close = [(o, f"分數 {sc:.1f}") for sc, o in ranked if top - sc < 1.0]
    return close

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true"); ap.add_argument("--county"); ap.add_argument("--violation"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    viols = load(VIOL, "violations.json")
    items = viols if isinstance(viols, list) else viols.get("violations", [])
    if a.list:
        for v in items:
            print(f"{v['id']:32s} {v['name']:18s} {v.get('article',''):20s} {'✅ 可檢舉' if v.get('reportable') else '❌ 不可檢舉'}")
        return
    if not (a.county and a.violation): ap.print_help(); return
    v = next((x for x in items if x["id"] == a.violation), None)
    if not v: sys.exit(f"沒有這個違規類型 id：{a.violation}（用 --list 看清單）")
    counties = load(COUNTIES, "counties.json")
    c = counties.get(a.county) or counties.get(a.county.replace("台", "臺"))
    if not c: sys.exit(f"counties.json 裡沒有「{a.county}」")
    ls = c.get("law_select") or {}
    options = ls.get("options") or []
    res = {"county": a.county, "violation": v["name"], "article": v.get("article"), "reportable": v.get("reportable"),
           "channel": c.get("channel"), "url": c.get("url"), "form_url": c.get("form_url"),
           "law_select_type": ls.get("type"), "shows_article": ls.get("shows_article"), "grouped_by": ls.get("grouped_by")}
    if not v.get("reportable"):
        res["verdict"] = "這項現在民眾不能檢舉，不要送；改打 110 或放棄"
    elif c.get("channel") == "email":
        res["verdict"] = f"此縣市用 Email 檢舉（{c.get('email')}），信裡直接寫條號與事實：{v.get('article')} {v['name']}"
    elif not options:
        res["verdict"] = "此縣市的選單選項沒有事先抓到（可能要登入或動態載入），到頁面上依條號人工挑"
    else:
        hits = match(v, options, items)
        if len(hits) == 1:
            res["verdict"] = "選這一項"; res["pick"] = hits[0][0]; res["matched_by"] = hits[0][1]
        elif hits:
            res["verdict"] = "有多個相近選項，請人工從 candidates 挑一個"; res["candidates"] = [h[0] for h in hits]
        else:
            res["verdict"] = "選單裡找不到對應項，請人工挑；下面是該縣市全部選項"; res["all_options"] = options
    res["evidence_needed"] = v.get("evidence"); res["common_rejections"] = v.get("common_rejections")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"【{a.county}】{v['name']}（{v.get('article')}）")
        print("判定：", res["verdict"])
        if res.get("pick"): print("選單選項：", res["pick"], f"（{res['matched_by']}）")
        if res.get("candidates"): print("候選：", " ／ ".join(res["candidates"]))
        if res.get("all_options"):
            for o in res["all_options"]: print("  -", o)
        print("入口：", res["url"]); print("填表頁：", res["form_url"] or "（由入口勾同意後進入）")
        print("影片要拍到：", "；".join(res.get("evidence_needed") or []))
        print("常見退件：", "；".join(res.get("common_rejections") or []))

if __name__ == "__main__":
    main()
