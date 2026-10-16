# 對沖小幫手｜最新工程進度與待驗收｜2026-10-16

範圍：僅 LAB，正式版 main 不變。本紀錄不是交易授權；任何實機 Demo 送單仍由使用者明確操作。

## 最新修正：平台互換不應被快速雙邊阻擋
- 使用者於 MT5 場內 + cTrader 場外測試時被原先 fast_pair 白名單擋住。
- 已擴充快速雙邊的有效排列：cTrader 場內／MT5 場外、MT5 場內／cTrader 場外；其他未驗證平台組合仍不開放。
- 兩組都先完成雙側表單預檢、快速各送一次，再逐邊核對成交；反向配置在兩邊都確認後，按 MT5 場內**實際成交價格**修改場內 SL／TP，必須從持倉讀回並驗證，再視勾選同步 cTrader 場外 SL／TP。
- 快速模式仍可能在場內 MT5 完成修改前產生暫時不對等的風險；與逐邊等待場內核對／修正再送場外的方式不同，GUI 啟用提示明示此風險。
- 遇任一不明或驗證失敗，不假稱完成；不因空白持倉列表盲目重送。嚴格的 Demo 帳戶、預檢、成交 ticket 及一次補單證據閘門保留。
- 修正「延遲看見持倉」二次唯讀補讀後未登記其平台／場別的問題，確保後續 SL／TP 修改使用已確認的場別；同時區分不同券商相同 ticket。
- 反向快速模式的成功、同步關閉、保護修正失敗、單邊成交不明、缺少 MT5 校準、帳戶非 Demo 等皆有獨立假券商測試。**實際反向雙 Demo、快速實際速度及券商成交回報仍待使用者自行驗收。**

## 已實作並已執行程式模擬驗證
- 主畫面填入場內／場外／兩邊與預檢；自動進場選項、一般逐邊及快速雙邊流程。
- 使用者回報：成交後 SL／TP 同步在既有配置中實際測試可用；反向組合尚未實際驗收。
- 場內／場外視窗綁定：Windows 最前景視窗取代滑鼠所在視窗，成功／失敗彈出置頂通知，重新綁定／確認。
- 自動進場後置頂核對結果，展示已驗證雙邊、SL／TP、未明確結果。
- 嚴格 P0：只有券商最終拒單、確認無成交與無掛單的可關聯證明，且另一邊仍唯一有效才允許補一次；預先 journal 鎖定避免重啟後第二次補。
- 讀取 cTrader 原生持倉列表、MT5 唯讀原生持倉查詢；第一次成交確認不明時最多再唯讀補讀兩次。
- 單邊持倉不明：結果視窗有人工平已開側或處理另一側的指引入口，不會直接執行平倉／補單。
- LAB GitHub 分支與正式 main 隔離，桌面捷徑目前顯示「對沖小幫手」，但仍指向 LAB。

## P0 尚未完成的實機層
- 券商最終拒單可關聯原始訂單證據未取得；GUI-only 的 DemoUiBrokerPort.prove_terminal_rejection() 仍回 None。因此**實機自動補單並未真正啟用**。
- 單邊情況不明時的自動化完整復原／一鍵明確確認平倉仍未實作，現階段只有人工指引。
- 雙 Demo 端對端反向組合，尤其 MT5 場內成交價修正、cTrader 場外修改持倉的實機操作，尚需校準與使用者手動啟動測試。
- 快速雙邊真實點擊間隔、雙邊成交時間、滑點、實際異常狀況與重新啟動中斷恢復仍未做完整現場驗收。

## 2026-10-16 速度與最新實際開倉紀錄（新增）
- 使用者在 MT5 場內 + cTrader 場外、已勾快速雙邊時觀察：場外填值後有停頓，兩次點擊／下單顯示相隔約 3 秒。這是使用者目測值，**不是經程式量測的券商成交間隔**。
- 根據實際呼叫路徑，兩側表單在初次預檢後，快速雙邊迴圈還會再做一輪 verify_order_form；接著 DemoUiBrokerPort.submit_once 又對同一側重新執行 inspect_account 與 verify_order_form（後者內部已再檢查帳戶）。已移除這兩處多餘的重複掃描，但**保留預檢及各次點擊前的最新訂單表單／帳戶核對**。
- 已新增性能耗時診斷：填值場內、填值場外、交易前預檢、快速雙邊送單函式起始間隔，以及兩次實際 Windows 點擊函式起始時間、兩側 pre-click 表單核對、場外按鈕 UIA 辨識耗時；沒有任何新增實機送單。
- 最新 LAB Demo journal 於 2026-10-16 16:32:46 記錄 confirmed_both=True、internal_protected=True、sl_tp_synchronized=False、status=attention_required。依 MT5 場內的流程，internal_protected 是場內依成交價修改／重新讀回及安全驗證完成後才記錄；然而**場外 SL／TP 未被紀錄為同步完成**。
- 最新異常原因指向 cTrader 無法唯一找到帳戶 UIA 控制項 CTraderAccountNumberTextBlock_AId。這是下一輪唯讀調查及實機驗收的具體 blocker；不可因畫面顯示似乎已同步就把 journal 標成 complete。
- 尚須使用者下一次人工授權的雙 Demo 實測觀察診斷 log：若兩次 Windows 點擊開始間隔仍高於預期，再精準縮短 slow UIA readback；當前只知道離線假券商基準，無法承諾真實低於某毫秒。不得為速度移除必要的最終校驗。

## P0 單邊異常／補單 — 統一追蹤，不要拆漏
- 首次開倉真正拒單後、另一側成功：一次性自動補缺側邏輯已完成並通過 fake broker；實機需能關聯原券商訂單的最終拒單、無掛單與未成交證據，目前 GUI-only 尚未提供，故**實際自動補單仍未開啟**。
- 若結果不明：使用者明確希望置頂彈窗**讓本人二選一**：「手動核對並補另一側」或「手動核對並把已開側平倉」。需先做兩側最新持倉／掛單核對；現在按鈕只是顯示風險說明與人工操作指引，**並不會代替使用者開／平倉**。後續要考慮把二選一介面整理得更明顯，但不能自己進行交易。
- 使用者取消『持倉期間自動補』；此 P0 僅涵蓋首次開倉的確定拒單、結果不明與異常人工處理。

## P1 與後續（不要當成 P0）
- TV 自動繪圖、警報及反向平台的實際價格與座標驗收。
- 不同方案／重開程式後的 GUI 設定維持與 cTrader 校準清單回歸；有些 cTrader 校準點曾刻意清空，實機送單前要人工校正。
- 真正的全流程毫秒分段測速與 UIA 額外優化。
- 右側可吸附的收合快捷面板；安全的遠端／手機操作。
- 當天重大事件時間提醒、最後 UI 收尾及跨電腦安裝包。
- **使用者已取消場內／場外止盈情境預覽圖，不能再列為待辦。**

最新 LAB 全套回歸：472／472 PASS（2026-10-16，速度診斷與重複掃描精簡後）；compileall 與 git diff --check 均 PASS。此數字僅代表離線與模擬測試，**不代表反向快速雙 Demo 實際成交驗收完成**。

## 2026-10-17 P0 更新：cTrader Positions 空白占位列
- 新的異常通知顯示「cTrader symbol 欄沒有唯一原生讀值（0）」，源自 `DemoUiBrokerPort._ctrader_positions()` 的持倉讀取，不是下單商品欄位一定填錯。
- Windows 唯讀實測：可見的 Positions DataGrid 唯一，UIA GridPattern.CurrentRowCount=0，卻回報一個不可見、不可操作、矩形 (0,0,0,0)、沒有 Text 子節點的 DataItem 占位列。先前程式誤將其當作真實持倉列解析。
- LAB 已新增嚴格的空白占位列分支：要求節點皆不可見且無尺寸、原生列數兩次相隔約 100ms 均為 0、且沒有原生文字，才視為空持倉表；如列數非 0、文字存在或讀值衝突，繼續 fail-closed。
- 已新增 7 項離線測試；全套 479/479 PASS（114.720 秒），編譯及 git diff --check PASS。這不是實際送單驗收。
- 修正後重新唯讀執行 cTrader 場外 snapshot_positions：成功，Positions 筆數 0（約 3617ms）；MT5 場內唯讀 snapshot_positions：成功，Positions 筆數 0（約 2036ms）。僅為當時持倉快照，未檢查所有掛單、歷史成交，也不保證之後狀態不變。
- 無任何交易、補單、平倉、Google Sheets 寫入或 LAB 重啟；正式版與 GitHub main 未修改。LAB 執行中舊程序若未重新啟動，仍可能使用先前載入的舊版本。
- 原有 P0 不變：快速雙邊真實點擊計時與雙 Demo 端對端驗收、cTrader 場外同步核對、可信拒單證據後才可首次補單、單邊未知時人工安全應變；P1 遠端手機/Telegram 控制及右側快捷面板仍待開發。已取消的情境預覽圖不恢復。

## 2026-10-17 00:27 cTrader 帳戶控制項間歇缺失（第二次發生）
- 最新 Demo journal 紀錄：00:27:41，兩側 confirmed_both、MT5 internal_protected=true，但未紀錄 cTrader 場外 SL/TP synchronized，status=attention_required；cTrader 缺少唯一的 CTraderAccountNumberTextBlock_AId 控制項。不得重新開倉，也不得將兩邊已成交誤說成單邊。
- 後續三次原生 UIA 唯讀全樹掃描，每次帳號、Demo 類型、券商名稱控制項各唯一且可見，整樹掃描耗時約 1592/1723/2071ms；支持暫時缺失可能，尚未證明發生當下的 UIA 狀態。
- LAB 修正 inspect_account：**只有帳號控制項數量為 0** 時，最多增加兩次唯讀掃描，每次間隔約 120ms；任何重複 ID、非 Demo、帳號變化或最後仍缺失均禁止繼續送單，不跳過驗證；正常成功時不增加額外全樹掃描。
- 新增 5 個離線測試，完整回歸 484/484 PASS（108.560 秒），compileall 與 git diff --check PASS。這不代表 cTrader 修改場外 SL/TP 已實際驗收。
- 唯讀當時查詢 MT5 場內與 cTrader 場外各 1 筆持倉，兩者 SL/TP 欄位皆非空，但**尚未確認 cTrader 場外 SL/TP 數值等於預期值**，也未讀證掛單與最新成交歷史。未執行任何送單、補單、平倉、同步修改或試算表寫入。
- 偵測到兩個同時執行的 LAB main.py Python 行程，可能造成工作階段混淆；未確認交易流程完全安全之前禁止盲目關閉其中任一個，尚未重啟 LAB。GUI 已載入版本不一定包含這次修正。
- P0 自動補單、單邊結果不明的人工二選一處理及雙 Demo 端對端實際驗收仍未完成；P1 手機／Telegram 遠端控制及右側快捷面板保留。已取消的情境預覽圖仍不製作。

## 2026-10-17 P0：滑鼠防干擾與最新雙邊延遲追蹤
- 使用者要求：每個「填入場內／填入場外／填入兩邊／重新確認進場」流程，自動操控滑鼠期間阻止本人實體滑鼠誤操作；從 worker 的 task 開始前保護，包含填數值、場內／場外送單與啟用的後續同步，完成或異常時解除。獨立繪製 TradingView／同步場外也適用。
- LAB 新增 `trading_helper/mouse_guard.py`：Windows WH_MOUSE_LL 低階 hook **只攔實體滑鼠事件**，允許程式注入的滑鼠事件及所有鍵盤；Esc 緊急停止有效；context-manager try/finally 解除；啟動不成功則 fail closed；180s 看門狗解除並停止自動化。禁止 Windows BlockInput 或 ClipCursor 造成 Escape／程式移動失效。
- `trading_helper/gui.py::_start()` 接入。新增 8 個離線測試；全套 492/492 PASS（111.951 秒），compileall + git diff --check PASS；原生 hook 在「停用攔截」的安全煙霧測試成功安裝／退出，尚未證明真實物理滑鼠被攔截與交易 GUI 同步相容，勿宣稱端對端驗收。
- 使用者新回報：填完兩側數值到首次送單仍慢，MT5 按送單到 cTrader 按送單也慢。現有 fast-pair instrumentation 已分記場內／場外填入與預檢時間、兩個 click_started 的函式級間隔、分別核對耗時；尚未取得當次耗時數值，不能把延遲說成券商成交或斷言某一檢查是唯一瓶頸。實測 cTrader 完整帳戶 UIA 樹讀取每次約 1.6～2.1s，可能貢獻多秒延遲；未取消送單前獨立必要核對。
- 最新 journal 01:09:06（在 00:54 安全重啟新版 LAB 之後）：confirmed_both 和 internal_protected 已確認，再次因缺少唯一 CTraderAccountNumberTextBlock_AId 而 attention_required；先前兩次讀不到時的限次重查仍未根治，不能宣稱同步完成、也不能自動重下單／平倉。下次需要現場 UIA 隱藏原因／modal／前景狀態診斷與可驗收的安全修復。
- 不動正式版與 GitHub main，不覆蓋 config/profiles/calibration，不在此開倉、補單、平倉或寫入 Sheets。GitHub 只推 LAB 分支。本次 GUI 需要安全重啟才能載入滑鼠保護；重啟前必須確認自動交易任務停止，保護實機持倉。

## 2026-10-17 P0：證實 cTrader 同標題視窗碰撞，安全選主視窗
- 唯讀實測 `WindowController.find_all(cTrader window_title)` 同時返回兩個 Windows top-level HWND：彈出／對話視窗 1199x772 只有 52 UIA 節點且沒有帳戶及持倉表控制項；主交易視窗 1938x1038 有 730 UIA 節點，包含唯一 CTraderAccountNumberTextBlock_AId、CTraderAccountTypeTextBlock_AId、PositionListDataGrid_AId。舊實作 `find()` 直接選第一個相同標題視窗，因 Z-order 變動會抓到 1199x772 彈窗，正是「帳號控制項不唯一（0）」的直接可重現原因之一。切到彈窗前景仍無帳戶項，不是單純焦點問題。
- 已修改 LAB `DemoUiBrokerPort._bound()`：當 cTrader 第一個標題相符視窗和已保存的 `lot_input` 主視窗校準尺寸不符時，透過廉價的 Windows EnumWindows `find_all` 篩選唯一尺寸一致的主 HWND；若 0 或多筆皆 fail-closed。正常第一個符合尺寸時沒有額外掃描。保留所有唯一帳戶／Demo／持倉／SLTP 與送單前核對。
- 校準資料為 1938x1038，兩側 window candidates 確實可用尺寸區分。UIA 窗口狀態會波動：隨後另一次僅找到 1938x1038 主窗，而其中間一次唯讀嘗試因視窗候選切換未通過。**尚未用新 GUI 完整端對端驗證**，不可宣稱 cTrader SL/TP 已同步或所有 UIA 問題徹底修復。
- 新增 `tests/test_ctrader_main_window_choice.py` 共 5 項測試，含 popup-first／main-first／無尺寸匹配／多個匹配／MT5 保留原行為；與先前滑鼠保護 8 項測試合計整套 **497/497 PASS**，111.292s，compileall 及 diff check PASS。
- LAB 滑鼠保護及 cTrader 視窗修正已寫入原始碼、只允許更新 LAB GitHub 分支。正在執行的 LAB GUI 必須安全重啟後才會載入修正；不得觸及正式版或 GitHub main，重啟前確認無自動工作進行中。未自動下單、平倉、補單或寫表格。
- 雙邊真實點擊間隔仍未完成數值驗收；先前 cTrader UIA 整樹掃描約 1.6~2.1 秒，多次帳戶／表單／按鈕辨識容易拖慢第二側按鈕。先使用已存在的快速雙邊診斷日志歸因，再做不削弱安全核對的效能優化，不能假稱滑鼠鎖定已加速。

- 安全重啟驗證完成：在 journal 逾 1595 秒未更新、備份 3 份 APPDATA 原始檔後，透過 WM_CLOSE 正常關閉舊 LAB GUI／父子行程 33988/31724；新 LAB 行程 25956/26152 正常啟動，僅有一個 GUI，原始碼存在兩項修正。未操作任何券商、持倉、下單或試算表。正式版不變。最新 LAB GitHub 進度與本機文件需保持一致。

## 2026-10-17 01:57 錄影逐格分析：雙 Demo 送單間隔仍慢
- User 上傳 45.4 秒、30fps、1920x1020 的 Windows 錄影 `20261016-1757-44.0484426.mp4`（錄影檔 metadata creation UTC 2026-10-16T17:57:48，約台灣 2026-10-17 01:57）。
- 錄影逐格目視估計：確認「仍要繼續進場」約 16 秒結束後，MT5 下單視窗約 24 秒出現，約 25–26 秒持倉列出現；約 28 秒轉回 cTrader，約 29–30 秒出現第二側持倉列。**MT5 持倉可見至 cTrader 持倉可見約 4 秒；GUI 轉換不等於滑鼠 OS Click 的精確時間，更不能全歸因券商成交。**
- 現有 LAB `gui.py::_fill_both_task` 先填場內與場外才進 `AutoEntryWorkflow.run`；`auto_entry.py` 預檢會掃描帳戶／持倉／表單，快速雙邊分支先送 MT5 再送 cTrader，不等待 MT5 成交回報，但 `DemoUiBrokerPort.submit_once` 兩側各自又執行完整 freshly-verified readback。尤其 cTrader 的 `inspect_account`、`_verify_instrument`、`read_fill_snapshot`、Place order 按鈕 UIA 定位四類操作，當前為數個獨立 UIA tree scans；前次 cTrader 全樹掃描約 1.6–2.1 秒，屬延遲嫌疑點，尚無錄影同次的精確 timings 或逐掃描 benchmark，不可宣稱已確認瓶頸比例。
- 安全優化方向：將第二側「唯一帳戶＋Demo＋商品＋表單 Lot/SL/TP＋方向／勾選＋唯一原生 Place order 按鈕」合併進同一份**點擊前立即取得的全新 cTrader UIA snapshot**，重用樹節點做不同語意驗證，不重用上一個交易週期的舊表單值；任何缺失／歧義依舊 fail-closed，不改變一次單、帳戶一致性及不補單限制。切勿直接跳過最後送單核對。另將每項 precheck、form scan、button localization、OS click 前後分開記錄 monotonic timing，以區分 UI delay 和 broker fill。
- 遠端 Windows Desktop Commander 此時 remote_calls_left_pct=0；因此**未修改本機 LAB 任何交易流程程式、未執行新回歸、未重啟，也未實際送單**。可繼續 GitHub 唯讀研究；待遠端額度恢復才能安全實作／測試／驗收。既有 cTrader 主視窗 1938x1038 安全選擇修正及滑鼠保護仍保留。

## 2026-10-17 通用視窗入口＋cTrader 最終核對共用快照（僅 GitHub LAB 研發版）
- 已依使用者桌面《更改前審核標準.txt》盤點 affected set：交易前填值 \`PlatformAutomation.fill\`、逐欄欄位定位 \`_window_for_point\`、獨立場外修改 \`sync_external...\`、Demo position/order adapter \`DemoUiBrokerPort._bound\`，以及送單前 \`inspect_account → _verify_instrument → read_fill_snapshot → Place order button\` 四種 UIA 取證。
- LAB GitHub 分支 \`lab/2026-10-16-safe-defaults-preflight\` 已改：\`WindowController.find_calibrated_main\` 作為 cTrader/GooeyTrade 按方案尺寸、唯一同名主視窗選擇的共通入口（不硬編目前電腦 1938×1038）；上述交易入口使用這個共用 resolver，遇多個/零個/尺寸不符 fail-closed，保留 mock 相容分支。MT5 原有 order-dialog ownership/geometry 不改。
- LAB GitHub \`DemoUiBrokerPort.submit_once\` cTrader 最後一刻在 focus 完成後僅取 **一份全新 UIA tree**，供 Demo account+broker binding、商品描述、手數/SL/TP/方向/勾選、唯一 native Place-order Button ID＋父層＋位置核對共用。空白/未知/變帳號/非 Demo/重複/不符仍拒絕點擊，沒有新增 order retries。正常早期 preflight 仍保持獨立 fresh checks，未移除交易必備 guard。
- \`Windows.read_fill_snapshot\`、\`DemoUiBrokerPort.inspect_account\`、\`_verify_instrument\`、\`verify_order_form\` 新增只給當次最後核對使用的可選 \`_controls\` 參數；未傳入時保留原本讀值行為。快速雙邊 log 補充分段 UIA timing。
- 新增 \`tests/test_generic_ctrader_final_snapshot.py\` **16 項尚未執行**的合約/防誤送單測試，並更新既有 timing mock 使其能表示最新的一份 UIA tree。原先 497/497 通過屬於**修正前**測試數據，**不代表本批程式碼通過**。
- Windows Desktop Commander 在修改途中回報 \`You've reached this month's Desktop Commander usage\`，因此**本機 LAB 有少量部分編輯，但未完整同步 GitHub 新版、未完整回歸、未重啟 LAB，也未實際進行 Broker 操作**。不要將 GitHub 改動視為已部署在電腦上的版本；需要能使用 Windows 後先備份、核對 staged diff、同步完成的檔案到 LAB，再跑定向＋全套離線測試與不碰交易的靜態驗證，確認沒有任何作業執行才可安全重啟。不得碰正式版或 GitHub main。
- 尚未達到 desktop 審核標準的 runtime operational PASS / true click-gap performance benchmark；未完成以前不能宣稱加速秒數或雙邊真實交易全情境安全。現有 MT5/cTrader 持倉不自動重下、補單或平倉。

## 2026-10-17 03:13 cTrader 主視窗尺寸零匹配新回歸（阻塞中，未修復）
- 使用者新截圖：按「寫入兩邊」後彈窗 \`cTrader 主視窗校準尺寸 1938x1038 未找到唯一符合者（0 個），不操作。\` 底部 log 03:13:43 相同。流程在 \`PlatformAutomation.fill\` 首次 \`WindowController.find_calibrated_main\` 即 fail-closed；未見證本次有送單，不能假稱整個交易帳戶狀態正常。
- 新版 resolver 同時要求 WindowController.find_all(title_pattern)、\`^cTrader(?:\s|$)\` 語意標題、主 HWND 寬高相較 lot_input 的舊 \`window_width/window_height\` 誤差 <=2 像素；**0 匹配不等於 cTrader 沒啟動或帳戶錯誤**，也可能是視窗大小／標題／是否列舉的變化。此錯誤不能直接以加大尺寸 tolerance 解決：\`WindowController.screen_point\` 仍嚴格依舊尺寸的 x_px/y_px 點擊；任意放寬主 HWND 辨識會把後面的填值或送單按到錯位。
- 修復前必需在本機 READ-ONLY 取得所有 title rule 匹配的 HWND、實際 title、PID、窗口 class、window rect、最小化狀態、各角色原校準尺寸；確認唯一主 terminal 與彈出視窗的不同身分。依桌面《更改前審核標準》修復 canonical resolver 的「**主窗口身分辨識**」與「**每個點位座標有效性**」不同責任：辨識不能單靠尺寸；必要時提示恢復舊窗口大小或重新校準，未具證據不能猜比例座標、盲點或繞過重讀校驗。
- 回歸矩陣應含：固定尺寸／移動位置不縮放、最大化切換尺寸、DPI 變化、多 cTrader 主窗、同名修改彈窗、主窗未顯示、GooeyTrade 與 MT5、不符合座標校準時無訂單點擊；也不能忘記原有滑鼠攔截緊急釋放。
- Desktop Commander 工具仍正式回覆當月額度用盡、remote_calls_left_pct=0；**無法觀測 live windows、無法修改本機、無法測試或安全重啟**，不得說 bug 已解。GitHub LAB only，勿動 production/main 或創建新訂單。短期使用者可嘗試讓 cTrader 主交易窗口恢復原校準的最大化/大小，但在確認舊成交持倉與掛單、測試模式關閉自動進場前，勿重複按寫入兩邊。

## 2026-10-17 全專案審核（GitHub LAB，未部署）
- 已建立 [完整 P0/P1/P2 稽核與驗收清單](AUDIT_20261017_FULL_PROJECT.md)：覆核 26 個程式模組、55 個測試檔、啟動／設定、UI 與功能待辦，區分程式已有但未部署、未通過實機、規則仍缺口、未實作。
- 最新 GitHub LAB `gui.py` 純說明文字 8 處與 README 說明更新，修正「自動送單尚未實作」等過時訊息；尚未本機執行或重啟，沒有交易、補單、平倉或覆蓋正式版。
- P0：cTrader 主窗尺寸 zero-match、快速雙邊 click-to-click timing、最後 SL/TP 語意核對、未部署／未跑全套 regression、同步狀態 readback、缺少可信最終拒單證明。P1：滑鼠鎖定全 task UX、反向組合與 TV 實機驗收等。P2：右側快捷列、重大事件提醒、手機/Telegram。取消的止盈情境預覽圖不恢復。
- 目前 Desktop Commander 月額度仍為 0；不得把 GitHub 內容當成使用者 Windows 已更新版本，需待工具恢復後先完成備份、diff、測試、再決定是否安全重啟 LAB。
