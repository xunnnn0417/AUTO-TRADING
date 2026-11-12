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
- TradingView position helper
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

第一次仍需設定自己的試算表、綁定交易視窗與校準。請保留 `AUTO-TRADING-lab-unified` 資料夾名稱，讓程式能直接更新。一般更新會沿用包內的 Python；執行環境有變更時，程式會引導下載新版完整包。

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
