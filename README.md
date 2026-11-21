# LAB development snapshot

This branch contains the LAB cTrader/MT5 UI automation and tests. Program changes are reviewed through PRs into the safe LAB branch; the repository `main` branch is separate. Account type is not used as an authorization gate. Order submission requires user-enabled options; an unconfirmed fill is not treated as proof of rejection.

For native **read-only** MT5 position verification on Windows, install `MetaTrader5` into the LAB's `vendor/mt5_readonly` directory using pip; vendor binaries and personal account settings are intentionally excluded from the repository.

---

# 對沖小幫手

Windows desktop helper for reading a user-owned Google Sheet and assisting with cTrader, MT5, and TradingView workflows.

This tool reads your sheet and fills calibrated broker fields. When enabled by the user, it can submit orders, verify positions, synchronize SL/TP and draw in TradingView. Offline tests do not replace platform workflow acceptance.

## What Is Included

- Python / PySide6 desktop app
- Google Sheet reader
- Optional Google Sheet write-back through a service account
- cTrader and MT5 window binding
- cTrader, MT5, and TradingView calibration
- Fill Internal, Fill External, and Fill Both helpers
- Right-edge quick panel (enabled by default; toggle in 顯示設定), sharing the main window's inputs, warnings and account-progress ruler. Starting Fill Both from this panel collapses it and leaves it collapsed after completion, without reopening the main window. The home button opens the main window and collapses the panel.
- The event flyout opens to the left without stretching the quick panel. It includes the public Forex Factory weekly calendar (high-impact events and medium-impact USD events), official BEA GDP/PCE schedules, relevant Fed/ECB announcements, and Chinese finance/world headlines from RTHK's public RSS. Two tabs separate upcoming events from recent news and published releases. The quick panel shows the next known event's countdown within the configured trading day, or the next known date/time. A missing, stale or wrong-week calendar never becomes a claim that no events exist. Source details reset to collapsed whenever the flyout opens; coverage remains incomplete and feeds can be delayed.
- The account ruler keeps its original monetary scale and calculations. Initial/current balance labels use separate quarter-width slots even at equal balances, then move together by up to five percent of the view width toward the applicable loss/goal boundary. Losses swap the two labels; all label movement is clipped without moving the plotted monetary markers. The same renderer serves the main and side panels.
- English public headlines are translated in the background using the documented anonymous MyMemory GET API, with cached results and a local 4,000-character daily cap. Only public titles are sent; no account, spreadsheet or trading data is shared. Machine translations are labeled, numeric changes are rejected, and the original title remains available when translation fails or reaches its limit. News refreshes and translation do not block trading controls.
- 「消息」頁與側欄重大事件共用同一份資料。手動重整會重新抓取所有來源，更新中不能重複送出；失敗保留舊消息與原成功時間，並標示待更新。
- 側欄餘額／預期 SL 驚嘆號使用旁邊的非阻擋式說明卡；不喚回主畫面，其他控制仍可操作。重按、Esc、點外部或收起側欄即可關閉；交易前確認仍沿用原流程。
- 校準結果儲存或關閉後，保留同一個平台校準視窗及頁籤，方便接續校準。
- 校準尋找或預覽結束後會恢復已開啟的側邊快捷，維持原收合狀態；顯示設定使用與自動化區相同的白色勾勾。
- 已移除產品內的假日／單邊故障／延遲測試選項及啟動入口；一般進場、異常恢復及離線回歸測試保留。
- Public news/central-bank RSS currently uses a **30-second observation trial**, while Forex Factory schedules remain at 30 minutes and BEA at six hours. Conditional requests reuse unchanged content; failures back off and respect Retry-After, including manual refresh. Polling frequency does not guarantee publication latency, complete coverage or permission for that rate. Official RSS descriptions do not publish a numeric per-minute allowance: [RTHK](https://news.rthk.hk/rthk/ch/rss.htm), [Fed](https://www.federalreserve.gov/feeds/feeds.htm), [ECB](https://www.ecb.europa.eu/home/html/rss.en.html).
- Each attempted source request writes local `diagnostics/news-poll.jsonl` evidence: start/end times, source, automatic/manual trigger, HTTP status, duration, bytes, parsed count, content-change flag and outcome. HTTP 304 is an unchanged success; HTTP 200 with invalid content is a parse failure. Logs rotate at 2 MiB with four backups (about 10 MiB total), and contain no account, sheet or news-body content. They are not uploaded.
- 新取得、近 15 分鐘內發布且含具體潛在事件的消息會顯示簡短非阻擋式提醒，並在「消息」亮紅點。標題規則區分政策宣布、重要發言／人事、地緣事件、金融風險與經濟數據；單純價格漲跌回顧仍列出但不彈窗。重要人物的突發標題若資訊不足或屬人事傳聞，標示「待確認」。判斷只依已取得的標題，不確認新聞真實性、不預測漲跌，也不保證涵蓋所有可能影響黃金的事件。
- 主畫面與側欄共用分類色條、左側時間及重點標題；關鍵字上色，原文可展開查看。來源文字一律轉義，不能開啟外部連結或載入資源。首次載入不彈歷史消息，同則不重複；交易、校準或其他確認視窗進行中延後提醒，查看消息清除紅點。
- 側欄消息使用較小字級、較窄時間欄與較短列間距，保留完整標題及原文入口；主畫面維持原字級與間距。
- 消息頁與側欄消息窗提供「測試重大消息」按鈕，注入明確標示的暫存測試消息，走相同提醒、紅點與操作中延後流程。測試不發出額外網路請求、不操作交易，也不寫入來源快取或抓取結果記錄；重啟後移除。
- TradingView position helper
- 餘額及預期 SL 的警示以更新後讀回的數值為準；輸入途中不新增警示，既有警示也不會僅因修改文字而解除。場內餘額超出帳號獲利目標／最大虧損範圍時，主畫面與側欄都會阻止填入。
- 餘額、每日盈虧、預期 SL 與進場價更新後，即使表格出現警示或交易計算無效，仍保留已確認寫入的新值，以淡色顯示並阻止交易，不自動還原。未確認寫入／讀回時保留可編輯草稿，不冒充更新完成；其他已讀數值繼續顯示。
- ESC emergency stop

## What Is Not Included

- No private Google Sheet URL
- No Google API key or service-account JSON
- No personal profile, calibration, or account configuration
- No spreadsheet template
- No trading strategy or market judgment

The default settings already include non-private cell mappings and platform defaults. Each user only needs to provide their own sheet URL, optional service-account JSON, window bindings, and calibration data.

## Download And Run

一般使用者：到 [GitHub 版本下載區](https://github.com/xunnnn0417/AUTO-TRADING/releases)，下載附件中名稱以 `AUTO-TRADING-Windows-x64` 開頭的 ZIP，完整解壓縮後雙擊「啟動對沖小幫手.vbs」。包內已包含 Python 與所需套件，不用另外安裝。

第一次會顯示「預設方案」，需設定自己的試算表、服務帳戶、交易視窗及校準；未完成項目以紅點提醒。請保留 `AUTO-TRADING-lab-unified` 資料夾名稱，讓程式能直接更新。一般更新沿用包內 Python；執行環境有變更時會自動下載對應版本的完整包、核對後安裝獨立環境，啟動失敗時還原。原有捷徑、設定及交易紀錄保留。

此下載包會在安全 LAB 分支每次有程式修改合併後自動產生：**測試通過 → 準備／沿用執行環境 → 打包並檢查 → 發布下載附件**。只改 Markdown 文件時略過。尚未看到 ZIP 附件時，可到 Actions 查看該次打包是否仍在執行或失敗；原始碼的「Source code」ZIP 不含 Python。

打包在 GitHub 背景執行，不需要每次由 AI 手動操作。執行環境依 Python 版本、套件需求及打包程式快取；內容有變才重新準備。下載包不會包含開發電腦上的試算表金鑰、帳戶、設定、校準或交易紀錄。

For Python users:

1. Install Python 3.11 or newer.
2. Clone or download this repository.
3. Run `install.bat`.
4. Run `run.bat`.

## Google Sheet Setup

Minimum setup:

1. Create or open your own Google Sheet.
2. Open the app and click `試算表設定`.
3. Paste your spreadsheet URL.
4. Set the worksheet name or GID.
5. Keep the default cell mappings if your sheet uses the same layout, or edit only the cells that differ.
6. Leave optional fields blank if you do not use them.

The app does not require a fixed spreadsheet format. If your layout changes, update the mappings.

The packaged default keeps non-private values such as `GOLD`, `C4`, `E8`, `0.01`, and `2`. It does not include any private sheet URL, API key, JSON path, profile, or calibration data.

## Google API Setup

CSV mode can read a publicly accessible sheet, but write-back features require `service_account` mode.

To use `service_account` mode:

1. Open Google Cloud Console.
2. Enable Google Sheets API.
3. Create a Service Account.
4. Download the JSON key file.
5. Share your Google Sheet with the Service Account email.
6. In the app, set read mode to `service_account`.
7. Select the JSON file path in `試算表設定`.

Do not commit the JSON key file to GitHub.

## Platform Setup

1. Open your cTrader / MT5 / TradingView windows.
2. In the app, choose Internal Platform and External Platform.
3. Click `綁定場內視窗` and `綁定場外視窗`.
4. Confirm that the app selected the correct windows.
5. Use `校準 cTrader`, `校準 MT5`, and `校準 TradingView` to capture required input fields and buttons.

Calibration is saved per user on the local machine. If monitor scaling, platform layout, or window size changes, recalibrate.

During calibration, click the calibration window once while waiting for the countdown to make sure it stays on top.

## Daily Use

1. Click `讀取試算表`.
2. Confirm symbol, direction, lot size, and SL/TP values.
3. Click `填入場內`, `填入場外`, or `填入兩邊`.
4. Confirm the platform fields and the enabled automation switches. With auto-entry **off**, you enter manually; with auto-entry explicitly **on**, a guarded **Demo-only** order workflow may submit orders when every preflight passes.
5. After manual entry, use the entry-price and SL/TP helper actions when needed.
6. Press `ESC` at any time to stop pending mouse and keyboard actions.

## Manual Trade Parameters

The lower trade-parameter fields can write values back to the sheet.

For `每日獲利/虧損`:

- `30` overwrites the current value with `30`.
- `=+30` adds `30` to the current sheet value.
- `=-30` subtracts `30` from the current sheet value.

If the sheet returns a warning/check message after an update, the app shows it and restores the previous values.

## Sharing Safely

When publishing this project:

- Commit source code and public documentation only.
- Use `config.example.json` for non-private examples.
- Put packaged builds in GitHub Releases, not personal configuration.
- Never upload service-account JSON files, real sheet URLs, API keys, profiles, or calibration data.

## Local Config

Runtime configuration is stored locally, normally at:

`%APPDATA%\TradingWorkflowHelper\config.json`

This file may contain private sheet URLs, local file paths, profile names, window bindings, and calibration data. It should not be shared.
