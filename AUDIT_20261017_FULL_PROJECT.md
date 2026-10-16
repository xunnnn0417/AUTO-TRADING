# 對沖小幫手｜2026-10-17 全專案程式審核與修正清單

> 審核範圍：GitHub `xunnnn0417/AUTO-TRADING` 的 `lab/2026-10-16-safe-defaults-preflight` 分支，**非正式版、非實機目前載入版本**。  
> 檢查方式：根目錄 11 檔／三資料夾；`trading_helper/` 全部 26 個程式檔；`tests/` 55 個測試檔，閱讀每份測試內容與名稱；主要交易入口、異常／安全路徑、GUI、Sheets、校準、進度尺、滑鼠守衛、待辦文件交叉追蹤。  
> **驗收限制：** Windows Desktop Commander 額度為零，不能執行實機／離線完整回歸、比對本機修改、同步或安全重啟。前次「497/497 PASS」是**更早版本**，不可套用至最新 GitHub 改動。本次僅修改 GitHub LAB 的 UI 說明文字及本清單。沒有交易或交易帳戶變更。

## 審核判準

依桌面 `更改前審核標準.txt`：真實問題重現→根因→affected set→最小安全改動→原案例和相鄰案例機器測試→實際入口與完整工作流驗收。下表的「程式已寫」不能等同「測試通過」或「實機部署成功」。

## P0：先修正／驗收，才可說快速雙邊完成

| ID | 缺口或風險 | 程式證據與原因 | 建議處理及最低驗收 |
|---|---|---|---|
| P0-01 | cTrader 主視窗「0 個符合」中止填入 | `windows.py::find_calibrated_main` 同時以標題前綴＋**視窗大小±2px**過濾；使用者 03:13 截圖出現 `1938x1038 未找到唯一符合者（0個）`。無法判斷究竟是視窗縮放／標題／Z-order／最小化／不同螢幕 | 先唯讀列出 HWND/title/PID/actual rect，分開「主視窗身份」和「校準點座標有效性」檢查；不要單純提高尺寸容忍度後盲點。測試最小化、彈窗、resize、最大化、DPI、多主窗與主窗唯一性 |
| P0-02 | 快速雙邊仍能感到約4–5秒等待 | `auto_entry.py` fast_pair 只不等待第一邊持倉核對，仍逐側 `journal.record` + `DemoUiBrokerPort.submit_once` 最終驗證；`windows.py` 的 UIA tree 取證可達秒級；錄影估算成交畫面間隔約 4.2–4.5 秒，非精確 OS click gap | 完整量測「提交呼叫／聚焦／取 UIA 清單／表單判讀／按鈕定位／OS click開始回返／券商成交回報」，以真實 click-to-click 毫秒為第一指標。先縮短/共用**不增加安全風險**的前置工作；禁止直接刪除當次必要身份/商品/表單核對 |
| P0-03 | 最新「共用單次 UIA」GitHub 改動未完成本機回歸／部署 | `demo_broker_port.py::submit_once` 新分支理論上共用最後一次的全新 UIA 清單：Demo 帳戶、商品、輸入欄位、native Place-order；`windows.read_fill_snapshot(_controls=...)`。新測試 `test_generic_ctrader_final_snapshot.py` 含 16 case，**尚未本機執行**。本機先前中途有部分改動 | 比對 GitHub vs 本機每個 changed file SHA／diff；備份後一次同步到 LAB；先編譯、定向及全套離線回歸，兼測 mock adapter 相容；零券商操作驗收；待獲授權後再雙 Demo 實機 |
| P0-04 | 最終送單前 SL/TP 僅驗證有效／非零，未重新比對該次預期數值 | `demo_broker_port.py::verify_order_form` 只接收 platform/role/direction/lot；讀回 SL/TP 後檢查正值/非零，沒有核對與本次 TradeInstruction 對應的**精確 SL/TP**。`automation.fill` 的早期讀回雖正確，但其後被修改成另一合法非零值時，最後一步未必擋得住 | 必須在最後當次讀值把 SL/TP 與預期值逐側核對，考慮 cTrader native/gooey 點數模式、MT5 市價導致的價格變動，明確容差/估價時點；測試「合法但錯誤數值」、「方向/位移」、「快雙邊」；未通過不能送單 |
| P0-05 | 已成交雙邊 SL/TP 同步失敗仍有未核對風險 | 曾有 `CTraderAccountNumberTextBlock_AId` 讀不到；先前雙邊持倉票據存在不代表場外同步成功；cTrader 同名彈窗 1199×772 可能先於主窗 1938×1038 被選中 | 可靠選擇真正主視窗後，逐票據取 position SL/TP，對照本單實際成交價計算值並 read-back。失敗只標記待人工核對，不補單、不假稱同步 |
| P0-06 | 單側拒單後「自動補一次」有契約、無實際證據來源 | `demo_broker_port.py::prove_terminal_rejection` 固定 `return None`；`recovery_policy.py` 規定須有唯一券商 order ID、最終 REJECTED、未成交無掛單、server proof。Fake broker 可以觸發，真實 GUI-only 無法 | 保持**禁用**，不可將空倉／UIA缺項／逾時當拒單；將券商唯讀成交、委託及歷史資訊證據接入後再另行審查。不自動平倉既有持倉 |
| P0-07 | Windows 崩潰與交易 journal 耐久性需核實 | `auto_entry.py::AutoEntryJournal._write` 以 temp write + `os.replace` 做原子替換，但未明顯作 `fsync`，崩潰與斷電時「durable」主張仍需實際壓力測試 | 做完整 crash-window/重啟中斷模擬、負向磁碟 I/O 案例，不得令不明送單狀態重新送單；明確區分 atomic replace 與真正斷電耐久性 |

## P1：有功能，但整合／體驗／驗收未完善

| ID | 項目 | 目前狀態及待補 |
|---|---|---|
| P1-01 | GUI 說明與實作不一致 | `gui.py` 多處仍宣稱「自動送單尚未接入」「同步/繪圖只預留」，但 `_fill_both_task → AutoEntryWorkflow.run` 已能在明確勾選/雙 Demo 驗證後送單或同步。已僅在 **GitHub LAB** 修正 8 處純文字文案；**未執行本機 UI 回歸或重啟**。不應讓使用者誤認按鍵一定只填值 |
| P1-02 | 滑鼠鎖定範圍與 UX | `gui.py::_start()` 以 `PhysicalMouseGuard` 包裹整個工作 task，而非逐次滑鼠動作，可能包含資料讀取等待；`mouse_guard.py` 有 Esc 解除、180 秒 watchdog。需 Windows 真實實體滑鼠／鍵盤緊急停止／多螢幕／hooks 錯誤實測，並決定是否縮至第一個滑鼠動作到最後一個之間 |
| P1-03 | 反向配置 MT5 內／cTrader 外 | 有 `test_reverse_fast_pair.py` 和狀態機離線回歸，**不等於反向雙 Demo 實機**通過 SL/TP 修正與最後 read-back |
| P1-04 | TradingView 圖形及順序後續工作 | `automation.py` 和 `AutoEntryWorkflow` 已連入「雙邊成交→內側保護→外側同步→TV」順序；在不同視窗、價格波動、反向平台及畫面變更後的 end-to-end 尚未全面驗收 |
| P1-05 | cTrader Decimal 輸入模式切換 | per-profile/per-sheet 的 native/gooey 選擇、兩次截斷才詢問的測試已存在；仍需真正不同欄位/Locale UIA readback、動態面板高度調整下的驗證 |
| P1-06 | 視窗及 DPI/校準改動 | 有 `position_calibration.py`、`calibration_confirm.py`、`post_entry_scan.py` 與相關測試，但需避免同名 modal 主窗混淆，且不應用過時 `x_px/y_px` 穿越 DPI/resize，應提供「須恢復視窗大小或重新校準」的明確提示 |
| P1-07 | 使用者可理解的速度診斷 | `submit_phase_timings` 有分段 telemetry，GUI log 也有文字；需要在紀錄頁有最小且可理解的本次「雙邊 click gap、預檢耗時、券商確認耗時」並避免暴露帳號；不能把 broker fills gap 當 click gap |
| P1-08 | 成交結果確認及異常處理入口 | `entry_status_report.py` 已顯示各場別／保護／同步是否成功，異常二選一目前**只提供人工操作說明**，沒有可驗證的 UI 按鈕安全平倉/補單執行；須維持不可擅自交易 |

## P2：已提出但未開發／尚未排期

| ID | 功能 | 已確認範圍 |
|---|---|---|
| P2-01 | 貼右邊緣、可收合的窄浮動快捷列 | `UI_FUTURE_FEATURES_BACKLOG_20261014.md` 和 `UX_FUTURE_RIGHT_EDGE_PANEL_AND_TEST_STATUS_20261016.md` 有需求，**未寫成完整功能**；未來需考慮誤觸、置頂、多螢幕、焦點以及「填入兩邊」的交易風險 |
| P2-02 | 當天重大事件／經濟數據提醒 | 尚在備忘；只在確有重大事件即將發布時顯示名稱／發布時間，沒有則完全不顯示；資料可靠性、時區及失聯要先設計 |
| P2-03 | 手機／Telegram 遠端指令 | 已在專案狀態列為 P1 構想，但尚未有可靠交付實作；如涉及觸發交易，必須另行設計授權、安全與避免重複送單 |

**明確排除：** 使用者已取消「場內／場外止盈情境預覽圖」，**不得**恢復為待辦項目。

## 已存在、應保留的功能與保護

- 試算表讀取／寫回／計算、兩邊數值填入、cTrader/MT5/TradingView 校準及編輯；相關 `sheets.py`、`models.py`、`progress_ruler.py` 和測試已覆蓋。
- 主畫面／編輯／紀錄三工作區、精簡深色 UI、警示／提示、視窗綁定、輸入草稿確認、進度尺、儲存多方案，依 `gui.py`、`ui_theme.py`、`config.py`及 UI tests 實作。
- 雙 Demo 身份保護、相同帳戶拒絕、已存在持倉拒絕盲開、避免送出第三筆、獨立成交票號及結果視窗、交易指紋 journal、Esc 緊急停止。
- MT5 唯讀持倉與掛單、cTrader UIA 唯讀持倉、未知狀態 fail-closed；不把拒單推測成事實。
- 已存在 55 個 `test_*.py` 測試檔，含使用者介面、校準、數值模式、快速雙邊、反向組合、危險單邊、回復、遠端無關的 GUI 鎖定、速度/表單、MT5 native、報表、DPI 等；**只有檔案存在及測試內容審查，不代表這次執行 PASS**。

## 下一次 Windows 操作恢復時的驗收操作單

1. 對照最新 GitHub LAB 分支和本機 LAB，備份本機 repo 改動／設定／journal，檢查雙 Demo 現有持倉、掛單及目前 worker；絕不對正式版或 main 快速覆蓋。
2. 只同步經過逐檔 diff 審核的 source/fixture 至 LAB；先修 P0-01 zero-match，區分標題／HWND身份／size／座標，保留 fail-closed。
3. 審核並補上 P0-04 的最後一刻 SL/TP 精確語意比較；不可用「非零即可」代替，需兼容 MT5/cTrader 模式與價位波動。
4. 驗證一次全新 UIA 取證修正是否真的減少第二側掃描；使用 instrumented mock + 可得的 Windows read-only timing 先評估延遲。
5. 執行 `compileall`、所有受影響定向 unittest、全部 55 檔離線 unittest、UI startup smoke、Git diff/check、各 changed file readback；任何 fail 立即不部署。
6. 若本機沒有待執行交易工作，才安全重啟**僅 LAB**；正式版、MT5、cTrader 不關閉。
7. 實機雙 Demo 的任何新建持倉測試，都要得到使用者對當次具體交易的明確授權；不能拿既有持倉重送。重點驗證 click-to-click latency、兩側 tickets、SL/TP 最終數值一致及 TV readback；操作未證實則保持 UNKNOWN，不可宣稱 DONE。

## 本輪具體產出與未完成

- **GitHub LAB 已修正** `trading_helper/gui.py` 8 處過時的 Demo 自動進場/後續選項文案（純文字，不修改送單演算法）。
- **本文件新增**，把全 repo 的 P0 / P1 / P2、受影響模組與驗收前提統一收斂。
- **尚未完成：** 本機部署、全部回歸、實際 click-gap 性能、P0-01/04 修正、真實端到端驗收。

## 2026-10-17 P0 修復進度更新（以 Windows CI 為準）

- **P0-01（程式修正完成／實機未驗）**：`WindowController.find_calibrated_main` 用符合版本型態的 cTrader 原生主窗標題辨識唯一視窗，不再以 1938×1038 等舊校準大小當作主窗身份；`PlatformAutomation.fill` 在任何 UIA 掃描或輸入前，以只讀 `screen_point` 提早核對當前視窗的點擊座標。尺寸/DPI 失效依舊拒絕點擊，避免「0 個主窗」模糊錯誤。不同 cTrader 真實版本標題仍需本機驗收。
- **P0-02（程式原型已測／實機延遲未知）**：先前 GitHub LAB 已把 cTrader 最終送單前的帳戶、商品、表單、原生 Place order 按鈕取證共用同一個全新的 UIA inventory；CI 有模擬快照回歸。尚未同步使用者電腦，不能聲稱兩次 OS 點擊 <1 秒或實際成交改善。
- **P0-03（離線驗收完成／實機部署未完成）**：新增 LAB Windows GitHub Actions CI；2026-10-17 編譯及 `525/525` 離線 unittest PASS，`git diff --exit-code` PASS，約 81.340 秒。[成功執行證據](https://github.com/xunnnn0417/AUTO-TRADING/actions/runs/38968709491)，測試程式 commit `11aeed38fcb82f3025b0f09d0174e6a91ed8ea37`。GitHub LAB 通過不代表 Windows 本機 LAB 已更新。
- **P0-04（程式修正完成／實機未驗）**：`PlatformAutomation.fill` 只在每側三欄**實際讀回成功後**保存本次預期方向、商品、手數、SL/TP 值；下一次新 fill 先清掉舊值。最後 `DemoUiBrokerPort.verify_order_form` 對同筆數值作精確 Decimal 比對。cTrader native/Gooey 點數及 MT5 填入時計價都以本次**已驗證填值**為準；錯誤的非零 SL/TP、沒有本次驗證記錄都禁止送單。新增 cTrader 與 MT5 正反例，CI 已通過。
- **P0-05（待實機）**：cTrader account/modal 選窗改善，但原有持倉 SL/TP **沒有**真實重新核對或修正；繼續標示未證實，不能在未知時自動下單、補單、平倉。
- **P0-06（有意安全禁用）**：無券商伺服器最終拒單及無掛單可核對證據，GUI adapter `prove_terminal_rejection` 繼續回傳 None，不允許危險猜測補單。
- **P0-07（程式改善／斷電證明仍需實機）**：`AutoEntryJournal._write` 在同目錄暫存 JSON 呼叫 `flush` + `os.fsync` 後才 `os.replace`；I/O 失敗不得覆寫已確認紀錄，新增兩項測試通過。這改善資料寫入耐久性，但 **不保證** Windows NTFS 任意瞬間斷電後目錄資訊完整，仍需 crash/fault 實機測試。
- 額外：cTrader UIA traversal 失敗現一律轉成 `AutomationError` 安全停止；已修正舊 synthetic UIA fixture。**本次沒有操作任何券商訂單或本機持倉**；正式版與 GitHub `main` 均未修改。
- GitHub 參考：Microsoft UI Automation 的 CacheRequest 能降低跨行程反覆讀取多個屬性的成本；pywinauto 社群也有將 repeated selectors 轉為單次 descendants inventory 的效能案例。現階段只採納**本次新鮮 inventory 可共用**的架構概念，不在未驗證情況下引入整套外部交易機器人或替換 native automation provider。
