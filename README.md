# Trading Workflow Helper MVP

Windows always-on-top helper for reading a Google Sheet and filling cTrader or
MT5 order panels. This version never clicks Buy or Sell.

## 功能

- 中文 Windows 桌面介面
- 從 Google 試算表讀取指定儲存格
- 自動反轉場內／場外方向
- cTrader 倉位、止損點數、止盈點數填入
- cTrader 止損／止盈勾選框狀態偵測與自動啟用
- MT5 新訂單視窗、Bid／Ask OCR、交易量與止盈止損價格填入
- MT5 訂單視窗就緒偵測，視窗出現後立即填入
- 所有 MT5 第一次止盈止損一律以 Ask 作為預估進場價，再依方向加減點數
- 主控制視窗預設置頂並停靠在螢幕正上方
- 每個平台獨立校準，支援視窗相對座標
- `ESC` 緊急停止
- 第一版不會點擊買入或賣出按鈕

個人的 `config.json` 包含試算表網址、視窗名稱與校準座標，已由
`.gitignore` 排除。分享專案時請使用 `config.example.json` 作為範例。

## Safety boundary

- `Execute Entry` is a dry-run confirmation.
- `Run Full Flow` stops before entry.
- `Simultaneous Entry` is displayed and saved, but does not submit orders.
- Press `ESC` at any time to set the app to `STOPPED`.
- Every mouse or keyboard action checks the emergency-stop flag.

## Install

1. Install Python 3.11 or newer from python.org and enable `Add Python to PATH`.
2. Run `install.bat`.
3. Run `run.bat`.

## Google Sheet

Open `Sheet Settings` and choose one mode:

- `csv`: paste the Google Sheet URL, enter its `gid`, and share the sheet for
  link access.
- `service_account`: install requirements, provide the service-account JSON
  path, and share the sheet with the service-account email.

Column mappings accept an exact header, an Excel column letter, or a 1-based
column number. The app selects the first row whose Status matches
`Status value to select`. Clear that setting to use the configured row number.

Set `Data layout` to `cells` to read values from independent cells on an
existing worksheet. In Column Mapping, enter cell references such as `B5`,
`D8`, and `F12`. Status filtering and the fallback row are ignored in this
mode.

MT5 needs `Estimated Price`, `Point Size`, and `Price Digits` so the app can
convert the sheet-provided SL/TP points into estimated prices. It does not
recalculate lot size or risk.

## Calibration

1. Open the relevant order panel.
2. Click `Calibrate cTrader` or `Calibrate MT5`.
3. Select a target and click `Capture`.
4. Move the mouse over that exact control in the platform window.
5. Keep it there until the 3-second countdown finishes.

Coordinates are stored as a ratio of the target window size, not as fixed
screen coordinates. Configuration is saved at:

`%APPDATA%\TradingWorkflowHelper\config.json`

If AppData is not writable, the app falls back to `config.json` beside
`main.py`.

If Internal and External use two instances of the same platform, set distinct
window-title regex patterns in `Sheet Settings > Window Titles`.

If an order panel is normally closed, calibrate `New Order button` and enable
`Click calibrated New Order target before filling` in Window Titles. Leave it
off when the panel is already open.

## MVP workflow

1. `Read Sheet`
2. Verify the displayed directions and values.
3. `Fill Internal`, `Fill External`, or `Fill Both`
4. Verify both order panels manually.
5. `Execute Entry` only displays a dry-run summary.

The entry-price reader, Google Sheet write-back, final MT5 SL/TP sync,
TradingView position drawing, and real simultaneous entry are reserved for V2.
