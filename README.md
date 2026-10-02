# 交通違規檢舉小精靈（traffic-violation-reporter）

給 Claude 與 Codex 用的技能包：把行車記錄器拍到的違規影片，變成一件填好的台灣交通違規檢舉案。

裝好之後，把影片丟給 AI，它會自己做完這些事：

1. 從影片的 GPS 找出違規發生在哪個縣市、哪個行政區、哪條路（離線判定，內建內政部縣市與鄉鎮界線）。
2. 看畫面判讀違規事實與車牌，對出道路交通管理處罰條例的條號。
3. 把影片剪成違規前後十幾秒，**裁切放大車牌**（保留號誌、停止線、左下的日期時間車速水印與路口環境，其餘裁掉；不縮小解析度），壓到該縣市檢舉網站收得下的大小。
4. 抽出證據截圖：違規那幾秒的截圖，**加上一張行進中車牌拍得最清楚的截圖**（違規那一秒車牌常常不清楚，審核員要能從一張圖讀出完整車號）。
5. 打開該縣市警察局的檢舉網站，把該填的欄位填好。
6. 停在「身分證字號」與「驗證碼」那一格，換你接手。

你只做三件事：核對它的判讀、自己輸入身分證字號與驗證碼、自己按送出。

## 內容

| 資料夾 | 用途 |
|---|---|
| `claude/traffic-violation-reporter/` | Claude 版技能包（Claude Code、Claude 桌面 App、claude.ai） |
| `codex/traffic-violation-reporter/` | Codex 版技能包（OpenAI Codex），由 Claude 版自動產生 |
| `dist/traffic-violation-reporter.skill` | Claude 版打包好的安裝檔，上傳 claude.ai 用 |
| `tools/build_codex.py` | 從 Claude 版重建 Codex 版的腳本 |

技能包裡面有：九支 Python 腳本（GPS 抽取、縣市與鄉鎮定位、座標轉路名、剪片裁切壓縮、抽畫面、找最清楚車牌、法條比對、整案打包）、22 縣市檢舉網站規格與操作小抄、48 項可檢舉項目與法條對照、內政部縣市與鄉鎮界線（簡化版）、警政署官方各機關檢舉網址總表。全部自帶，不需要網路以外的任何服務。

## 使用前要有的東西

| 需要 | 說明 |
|---|---|
| 付費版 Claude（Pro 以上）或 Codex | 免費版 Claude 沒有技能包功能，也不能用 Claude Code 與 Claude in Chrome。 |
| Claude Code、Claude 桌面 App 或 Codex 桌面 App | 剪片、讀 GPS 要在你的電腦上跑。 |
| Chrome 加 Claude in Chrome 擴充功能（Claude 版） | 自動填檢舉網站用。沒有的話，它會把該填的值整理成一張表讓你自己貼。 |
| ffmpeg、exiftool、numpy、Pillow | 免費開源。numpy 與 Pillow：`python3 -m pip install --user numpy pillow`（找最清楚車牌、裁切預覽用）。Mac：`brew install ffmpeg exiftool`。Windows：`winget install ffmpeg`，exiftool 到 exiftool.org 下載。第一次用時會自動檢查。 |

## 安裝

**Claude（claude.ai 或桌面 App）**：下載 `dist/traffic-violation-reporter.skill`，到 claude.ai 的設定 → Capabilities → Skills → Add → Upload a skill 上傳。

**Claude Code**：把 `claude/traffic-violation-reporter/` 整個資料夾放到 `~/.claude/skills/` 底下。

**Codex**：把 `codex/traffic-violation-reporter/` 整個資料夾放到 `~/.codex/skills/` 底下。

## 怎麼用

1. 把行車記錄器記憶卡裡的影片資料夾整個複製到電腦（整個資料夾，有些機種的 GPS 存在旁邊的小檔案裡）。
2. 對 AI 說：「檢舉這段影片，違規大概在第 40 秒」。說不出秒數也沒關係，它會逐秒看。
3. 它會給你一張核對表：縣市、時間、地點、車牌、違規事實、法條。逐項看過。
4. 你點頭之後，它才會打開該縣市的檢舉網站填表，填到身分證字號與驗證碼時停下來請你接手。
5. 你按送出。多數縣市會寄一封確認信，要在時限內點信裡的連結，案件才算成立。

## 幾件事先知道

- 違規發生當天算第一天，七天內要送出，過了不受理。
- 紅線、黃線、路口、公車站的路邊違停，2024 年 6 月 30 日起民眾不能檢舉，只能打 110。能檢舉的違停只剩三種：四輪汽車停在人行道或斑馬線上、占用身障車位、併排停車。
- 一案一車。同一輛車六分鐘內沒經過一個路口的連續違規只算一件。
- 檢舉是實名制。這個技能包不會儲存你的身分證字號與任何密碼，聯絡資料只存在你自己的電腦上。
- 民眾檢舉只罰錢不記點。
- 金門、連江沒有線上系統，只能寄 Email；國道上的違規要向國道公路警察局檢舉。

## 資料日期與限制

22 縣市網站規格與法條是 2026 年 9 月 26 日查證的（來源網址都寫在 `references/` 裡）。各縣市網站日後可能改版，填表時以現場頁面為準；`references/counties.json` 每個縣市的 `gaps` 欄位列出了當時查不到的項目（桃園第二步表單、新竹縣法條清單、嘉義市需 MyData 登入後的表單）。

行車記錄器 GPS 格式：Novatek 方案（Viofo、DOD、多數台灣白牌）、Garmin、70mai、BlackVue、Thinkware、Nextbase、GoPro 等由 exiftool 直接讀；Mio、PAPAGO 舊機、BlackVue 舊機讀記憶卡同名旁檔；Tesla 讀 event.json。不認得的機種可跑 `scripts/extract_gps.py 影片 --diagnose` 看 GPS 藏在哪。

## 授權

MIT。歡迎修改與分享。
