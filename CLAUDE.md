# 專案規則

## 行事曆規則
使用者說「寫進行事曆」「加入行事曆」時，一律優先寫進 Google 行事曆，並選使用者指定名稱的那個行事曆（例如「生活」「工作」「家庭」）。不要寫進手機或 Mac 本機行事曆。寫入時一律明確指定時區 Asia/Taipei，因為部分 Google 行事曆預設時區是 UTC。

## 改技能包的順序
改了 `claude/traffic-violation-reporter/` 之後，一定要做兩件事：

1. 跑 `python3 tools/build_codex.py claude/traffic-violation-reporter codex/traffic-violation-reporter` 重建 Codex 版，不要手改 Codex 版。
2. 重新打包 `dist/traffic-violation-reporter.skill`（zip，最上層資料夾是 `traffic-violation-reporter/`）。
