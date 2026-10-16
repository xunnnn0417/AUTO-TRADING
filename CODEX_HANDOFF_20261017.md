# Codex 交接包｜對沖小幫手 LAB｜2026-10-17

> **任務定位**：這是由 ChatGPT 移交給本機 Codex 的續作指示。主要目標是將 GitHub LAB 已完成的 P0 修正安全帶回 Windows 的 LAB 工作區，先測試並排除差異，再處理「快速雙邊」MT5 與 cTrader 兩次開倉仍約 4–5 秒的使用體驗。不要把 GitHub CI 成功誤當成使用者電腦已更新、已重啟或已真實成交驗收。

## 0. 最重要的三條路徑

| 用途 | 精確路徑／連結 |
| --- | --- |
| **唯一允許修改的本機 LAB 專案** | `C:\Users\User\Desktop\codex\AUTO-TRADING-lab` |
| 不可修改的正式版 | `C:\Users\User\Desktop\codex\trading-workflow-helper` |
| 已有 Python 解譯器（可唯讀借用執行測試；切勿修改正式版） | `C:\Users\User\Desktop\codex\trading-workflow-helper\.venv\Scripts\python.exe` |
| GitHub repo | https://github.com/xunnnn0417/AUTO-TRADING |
| **唯一允許提交的安全分支** | `lab/2026-10-16-safe-defaults-preflight` |
| 本文件 GitHub 位置 | https://github.com/xunnnn0417/AUTO-TRADING/blob/lab/2026-10-16-safe-defaults-preflight/CODEX_HANDOFF_20261017.md |
| 專案長期總進度 | `PROJECT_STATUS_20261016.md`（位於 LAB 根目錄及上述 GitHub branch） |
| 全專案 P0/P1/P2 稽核 | `AUDIT_20261017_FULL_PROJECT.md`（同上） |
| 測試工作流程 | `.github\workflows\lab-offline-windows.yml` |
| 測試使用者資料資料夾 | `%APPDATA%\TradingWorkflowHelper_TEST\` |
| 自動送單日誌 | `%APPDATA%\TradingWorkflowHelper_TEST\demo_auto_entry_journal.json` |
| LAB 安全備份 | `C:\Users\User\Desktop\codex\AUTO-TRADING-lab\.safety_backups\` |

**舊 PID 和舊帳戶 snapshot 都過時**，必須在本機重新讀取，不能以本文件假設目前無交易。

## 1. Codex 開始動手前的硬性限制

- 僅在 LAB 修改、測試、提交；絕不更改正式版資料夾、GitHub `main` 或任何真實／正式帳戶。
- 不覆寫 `config.json`、profile、UI 校準、儲存的方案、使用者交易歷史、`demo_auto_entry_journal.json`；保留全部備份與原始 diff。**本機 LAB 曾在遠端工具額度耗盡前進行部分寫入，因此工作樹可能含未提交修改**；先逐檔比對，不要盲目 `git pull` / `checkout` / `reset --hard` / `git clean` / `git add .`。
- **未經使用者對該次特定交易明確授權，不得實際按下任何 MT5/cTrader 下單、補單、平倉、改 SL/TP、取消掛單**。Demo 也不例外。測試先做純模擬與唯讀 UIA。
- 既有兩側可能有持倉，曾出現 `confirmed_both` 但外側 SL/TP 同步狀態 `attention_required`；**絕不自動再下單**。未知／讀不到／timeout 一律 fail closed，不把空白列表當成拒單證據。
- 程式可以用 Python 模擬 UIA 測試，但**不得用實際券商點擊作為速度 benchmark**。如果欲安全重啟 LAB，先核查有無正在執行的填值／送單／同步工作及 journal 最近寫入，僅關閉 LAB（不是 MT5/cTrader，也不是正式版），且要確定已完整測試。

## 2. GitHub LAB 程式目前做到了什麼

**2026-10-17 的 Windows GitHub Actions CI：525/525 unittest PASS、compileall PASS、git clean PASS。**

成功的 CI 連結：
https://github.com/xunnnn0417/AUTO-TRADING/actions/runs/38968709491

之後改動的 CI workflow 亦有成功紀錄：
https://github.com/xunnnn0417/AUTO-TRADING/actions/runs/38969138428

但以上都在 GitHub 獨立 Windows runner，**尚未更新本機**，也**尚未測量真實雙邊 click-to-click latency**。驗收報告必須區分「程式碼通過」、「本機測試通過」、「真實交易端對端通過」。

已修改的主要原始碼：

1. `trading_helper/windows.py`：新增 `WindowController.find_calibrated_main()`。使用 cTrader 原生主窗標題辨識唯一主交易 HWND，不用 1938×1038 這種硬編尺寸辨識身分；**點擊前仍由 `screen_point()` 嚴格校驗原始尺寸/像素座標**，主窗 resize 不可盲點。
2. `trading_helper/automation.py`：填值、欄位與場外同步路徑共用主窗 resolver。每側完成欄位三項實際讀回後，記下 `_last_verified_fills[(platform,role)]`（方向、商品、手數、SL/TP），新一輪填值清除舊資料；若填值未成功，不得留下可用的完成狀態。
3. `trading_helper/demo_broker_port.py`：cTrader 最後送單前**取得一次新的 UIA controls**，在同一快照核對 Demo 帳戶、商品、方向、手數、SL/TP、勾選和唯一 Place order 原生按鈕（包括父層），UIA error 轉 `AutomationError` 停止。SL/TP 不只非零，還要**精確等於本次填入並讀回的數值**；也覆蓋 MT5 absolute prices。
4. `trading_helper/auto_entry.py`：補充分段 timing，交易狀態 journal 暫存 JSON 先 `flush` + `os.fsync` 再 `os.replace`。這降低寫入風險，**不保證任意斷電完全耐久**。
5. `trading_helper/gui.py`：有 `PhysicalMouseGuard` 圈住相關 worker，並更正多處過時的 Demo 自動送單／同步提示文字。守衛保留 Esc/180 秒解除，但尚未完成實體滑鼠端對端驗收。
6. 新測試 `tests/test_generic_ctrader_final_snapshot.py`、`tests/test_journal_durability.py` 等；現有測試總量 525。

這些都是 **LAB 分支版本**；Codex 必須確認實際工作樹是否與此相符。

## 3. P0 待處理與驗收順序（請直接執行，無須重問已知背景）

### P0-A：本機安全對齊與回歸（最優先）

1. 在 LAB 根目錄讀 `git status --short`、`git branch --show-current`、`git remote -v`、`git diff`。保存日期/版本資訊，備份有修改的原始碼及設定，不執行破壞性 Git 指令。
2. 僅以 `git fetch origin lab/2026-10-16-safe-defaults-preflight` 取得 GitHub LAB 版本；檢查 `git diff HEAD FETCH_HEAD` 和工作樹修改。**先以人工／細部 diff 安全合併到現有 LAB 工作樹**，避免覆寫尚未備份的修改／個人設定。若 Git 分支與遠端有分岔，保留並報告，不要 reset。
3. 檢查 `windows.py` 的 main-title regex 能涵蓋使用者實際 cTrader title；以 Win32 唯讀列出 HWND/title/class/PID/window rect，主窗身份與座標有效性要分開。錯誤判斷時要顯示真正原因，不能只回報 0 個符合。
4. 同步且核查上述 source/fixtures 後跑本機 `compileall`、受影響定向測試、全部離線 unittest；不允許失敗還啟動交易工作。
5. 在沒有執行中的自動操作且經核實安全時，**只重啟 LAB**，確認載入的是最新 LAB source/commit、只有一個主 GUI；不得操作 broker 訂單。

### P0-B：真正縮短「快速雙邊」開倉間隔

原用戶錄影：MT5 持倉畫面到 cTrader 持倉畫面約 4.2–4.5 秒，**不等於兩次 OS send-click gap**。目前 fast_pair 是「不等待第一邊成交才準備第二邊」，但兩邊仍各有送單前驗證與 UIA 成本。已把 cTrader **多次**掃描合併成一次新鮮 inventory；尚需量測。

先在 `AutoEntryWorkflow.run` 及 `DemoUiBrokerPort.submit_once` 的各階段 monotonic timing 補透明診斷，顯示：
- 填入場內／場外每側耗時、填完到 MT5 click；
- MT5 click_started → cTrader click_started 毫秒；
- cTrader 取 UIA 一次清單、驗證帳戶／商品／表單／按鈕各段耗時；
- broker 委託回報與成交確認另列，禁止與 click gap 混為一談。

目標是把可提前完成、不影響安全的工作移到**第一邊按下送單以前**。任何關於第二側帳戶／商品／手數／方向／止盈止損與唯一按鈕的驗證，必須針對當次最新可證實狀態；**不能為了 <1 秒而盲點、跳過最後身份或按鈕核對**。如果需要改變保護模型，先跟使用者討論。

### P0-C：真實成交／同步結果的唯讀核對

- cTrader 曾回報「缺少唯一 `CTraderAccountNumberTextBlock_AId`」，實測同標題 popup 與主交易視窗混淆。主視窗新判斷仍需本機視窗截面實測。
- 對已存在的 MT5/cTrader Demo 倉位進行 **唯讀** 帳戶、ticket、方向、量、實際成交價、SL/TP、待處理掛單核對；不要更動交易、也不要因舊 journal 自動補單／恢復送單。
- TradingView 繪圖與反向角色、不同方案/DPI/尺寸/Decimal 模式仍需分開驗收。只有讀回成功才聲稱成功。

### P0-D：自動補單維持禁用

`DemoUiBrokerPort.prove_terminal_rejection()` 目前回傳 `None`，沒有伺服器最終 REJECTED、無成交、無掛單的可靠交叉證據。不得根據空白 UIA/等待超時直接補另一筆。請僅整理支援所需的唯讀證據方案，不要擅自上線自動補單。

## 4. 在 Windows Codex 的建議操作（PowerShell）

**把 Codex 開在以下 LAB 專案資料夾，不是正式版：**

```powershell
Set-Location 'C:\Users\User\Desktop\codex\AUTO-TRADING-lab'
git status --short
git branch --show-current
git remote -v
git diff --stat
# 非破壞性：只下載對照資料；下一步要先審查 diff 才能整合
git fetch origin lab/2026-10-16-safe-defaults-preflight
git log --oneline --left-right HEAD...FETCH_HEAD
git diff --stat HEAD FETCH_HEAD
```

唯讀／離線測試（**僅在完成備份與合併後**）：

```powershell
Set-Location 'C:\Users\User\Desktop\codex\AUTO-TRADING-lab'
$env:QT_QPA_PLATFORM = 'offscreen'
$py = 'C:\Users\User\Desktop\codex\trading-workflow-helper\.venv\Scripts\python.exe'
& $py -m compileall -q main.py trading_helper tests
& $py -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
```

若上述 Python 無法使用，請優先在 LAB 專案建立**獨立 LAB venv**；不得對正式版的 `.venv` 安裝、升級、刪套件。

**只有在完成同步、測試、確認沒有待執行交易自動化且僅會啟動 LAB 後**，才啟動 GUI：

```powershell
Set-Location 'C:\Users\User\Desktop\codex\AUTO-TRADING-lab'
& 'C:\Users\User\Desktop\codex\trading-workflow-helper\.venv\Scripts\python.exe' .\main.py
```

請勿直接複製執行上面的 GUI 啟動指令作為第一步：本機可能已有一個 LAB 實例，且其交易 journal 可能是未知狀態。

## 5. 本輪完成的明確驗收條件與回報格式

Codex 完成後請回報：修改了哪些檔案、哪些模組受影響、分支/commit、備份位置、測試數量與 PASS/FAIL、UIA 原生唯讀狀態、是否已安全重啟 LAB、量到的真實 click gap（若沒有權限實測就標「未知」）、已存在持倉的 SL/TP 同步證據、尚未完成/需要使用者決定的議題。

**不要宣稱「已重開／已修好／雙邊低於 1 秒／已同步 SL/TP」除非真的有對應的最新本機紀錄。**

後續 P1/P2 與取消的項目：詳見 `AUDIT_20261017_FULL_PROJECT.md`。右側可收合快捷列、重大經濟事件提醒、Telegram/手機遠端是待開發；**已取消的止盈情境預覽圖，不要自行恢復**。
