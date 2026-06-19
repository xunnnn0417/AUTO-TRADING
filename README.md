# 對沖小幫手

Windows desktop helper for reading a user-owned Google Sheet and assisting with cTrader, MT5, and TradingView workflows.

This tool does not decide market direction, calculate risk, or click live entry buttons. It only moves data from your sheet into calibrated UI fields and helps draw or update related position information.

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

For non-technical users, use the packaged Windows exe from GitHub Releases if one is provided.

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
4. Confirm the platform fields manually before entry.
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
