"""Read-only P2 calibration inventory safety and matching tests."""
import unittest

from trading_helper.calibration_scan import Control, match_all, inspect_all_targets
from trading_helper.gui import CALIBRATION_TARGETS

WINDOW = (0, 0, 1200, 900)
def c(kind, name, automation_id, rect, ancestors=()):
    return Control(kind, name, automation_id, rect, ancestors=ancestors)

class CalibrationScanTests(unittest.TestCase):
    def test_all_original_targets_present(self):
        for platform, count in [("cTrader", 16), ("MT5", 16)]:
            report = match_all(platform, CALIBRATION_TARGETS[platform], [], WINDOW)
            self.assertEqual(len(report.targets), count)
            self.assertEqual(len(report.reasons), count)
            self.assertFalse(report.candidates)
            self.assertIn("不會覆寫既有校準", report.as_text())

    def test_confirmed_uia_identity_only_produces_candidate_not_saved(self):
        controls = [c("Edit", "", "QuantityOrVolumeTextBox_Ald", (220, 110, 310, 140))]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, WINDOW)
        self.assertEqual(set(report.candidates), {"lot_input"})
        self.assertIn("未確認", report.as_text())
        self.assertIn("AutomationId=QuantityOrVolumeTextBox_Ald", report.as_text())

    def test_reject_two_volumes(self):
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], [
            c("Edit", "Volume", "", (200, 100, 300, 130)),
            c("Edit", "Volume", "", (200, 200, 300, 230)),
        ], WINDOW)
        self.assertNotIn("lot_input", report.candidates)
        self.assertIn("2 個候選", report.reasons["lot_input"])

    def test_mt5_order_buttons_require_paired_same_row_real_buttons(self):
        controls=[
            c("Button","Sell by Market 3921.13","",(110,380,240,422)),
            c("Button","Buy by Market 3921.45","",(260,380,400,422)),
            c("Text","Buy by Market","",(250,350,340,378)),
            c("Text","Ask 3921.45","",(220,278,340,305)),
        ]
        keys=(("order_submit_buy","買入"),("order_submit_sell","賣出"),
              ("ask_price","目前價格"))
        report=match_all("MT5",keys,controls,(0,0,700,550))
        self.assertEqual(set(report.candidates),set(k for k,_ in keys))
        self.assertTrue(all("低信度" in item.evidence
                            for item in report.candidates.values()))
        controls[1]=c("Text","Buy by Market 3921.45","",(260,380,400,422))
        fail=match_all("MT5",keys,controls,(0,0,700,550))
        self.assertNotIn("order_submit_buy",fail.candidates)
        self.assertNotIn("order_submit_sell",fail.candidates)

    def test_mt5_price_without_numeric_quote_is_not_assumed(self):
        keys=(("ask_price","目前價格"),)
        result=match_all("MT5",keys,[
            c("Text","Ask:","",(100,150,180,175)),
            c("Text","Price:","",(100,190,180,215)),
        ],(0,0,700,500))
        self.assertFalse(result.candidates)

    def test_mt5_bid_and_ask_are_distinct_numeric_candidates(self):
        keys=(
            ("bid_price_left","左側 Bid"),
            ("ask_price_right","右側 Ask"),
        )
        controls=[
            c("Text","Bid 81428.52","bidPriceText",(120,200,230,230)),
            c("Text","Ask 81436.02","askPriceText",(250,200,360,230)),
        ]
        report=match_all("MT5",keys,controls,WINDOW)
        self.assertEqual(set(report.candidates),{key for key,_ in keys})
        self.assertEqual(report.candidates["bid_price_left"].rect,controls[0].rect)
        self.assertEqual(report.candidates["ask_price_right"].rect,controls[1].rect)

    def test_mt5_main_toolbar_new_order_is_menu_item_in_actual_uia(self):
        controls = [
            c("MenuItem", "新訂單", "", (517,56,605,93)),
            c("TabItem", "交易", "", (20,945,105,965)),
        ]
        report = match_all("MT5",(
            ("new_order_button","新訂單"),("trade_tab","交易分頁"),
        ),controls,(0,0,1600,1000))
        self.assertIn("new_order_button",report.candidates)
        self.assertEqual(report.candidates["new_order_button"].rect,(517,56,605,93))
        self.assertIn("MenuItem",report.candidates["new_order_button"].evidence)

    def test_mt5_labeled_unidentified_order_fields_remain_low_confidence(self):
        controls=[
            c("Text","Volume:","",(110,160,205,187)),
            c("Edit","","",(220,161,360,187)),
            c("Text","Stop Loss:","",(110,203,205,229)),
            c("Edit","","",(220,204,360,229)),
            c("Text","Take Profit:","",(110,248,205,274)),
            c("Edit","","",(220,248,360,274)),
        ]
        targets=(("lot_input","交易量"),("sl_input","止損"),("tp_input","止盈"))
        report=match_all("MT5",targets,controls,(0,0,700,500))
        self.assertEqual(set(report.candidates),{t[0] for t in targets})
        self.assertTrue(all("低信度" in c.evidence
                            for c in report.candidates.values()))
        controls.append(c("Edit","","",(370,203,490,229)))
        ambiguous=match_all("MT5",targets,controls,(0,0,700,500))
        self.assertNotIn("sl_input",ambiguous.candidates)

    def test_mt5_new_order_scan_ignores_text_and_duplicate_toolbar_items(self):
        targets=(("new_order_button","新訂單"),)
        report=match_all("MT5",targets,[
            c("Text","新訂單","",(100,70,190,94)),
            c("MenuItem","新訂單","",(700,650,850,685)),
        ],(0,0,1600,1000))
        self.assertNotIn("new_order_button",report.candidates)
        duplicates=match_all("MT5",targets,[
            c("MenuItem","新訂單","",(100,70,190,94)),
            c("Button","New Order","",(330,70,425,94)),
        ],(0,0,1600,1000))
        self.assertNotIn("new_order_button",duplicates.candidates)
        self.assertIn("2 個",duplicates.reasons["new_order_button"])

    def test_readonly_type_restrictions_prevent_click_target_guess(self):
        controls = [
            c("Text", "Buy", "buy_text", (20, 20, 140, 80)),
            c("Text", "Sell", "sell_text", (20, 130, 140, 160)),
            c("Text", "Stop Loss", "SLLabel", (50, 400, 160, 430)),
            c("Button", "Buy", "buy_button", (30, 300, 120, 340)),
        ]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, WINDOW)
        self.assertEqual(set(report.candidates), {"buy_button"})
        self.assertNotIn("sell_button", report.candidates)
        self.assertNotIn("sl_input", report.candidates)

    def test_modify_dialog_sl_and_tp_do_not_merge_into_main_inputs(self):
        controls = [
            c("Edit", "Stop Loss", "stopLossMain", (400, 100, 500, 130)),
            c("Edit", "Take Profit", "tpMain", (400, 140, 500, 170)),
            c("Edit", "Stop Loss", "positionStopLoss", (400, 200, 500, 230), ("Modify Position",)),
            c("Edit", "Take Profit", "positionTakeProfit", (400, 240, 500, 270), ("Modify Position",)),
        ]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, WINDOW)
        self.assertEqual(set(report.candidates), {"sl_input", "tp_input", "position_sl_input", "position_tp_input"})

    def test_fails_closed_on_missing_or_hidden_controls(self):
        controls = [
            c("Edit", "Volume", "", (100, 100, 170, 120)),
            Control("Edit","Stop Loss","SL", (180,100,260,120), visible=False),
            Control("Edit","Take Profit","TP", (180,100,260,120), enabled=False),
            c("Button", "Buy", "buy", (-200, 100, -100, 150)),
        ]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, WINDOW)
        self.assertEqual(set(report.candidates), {"lot_input"})

    def test_does_not_reuse_one_rectangle_for_two_targets(self):
        controls = [c("Edit", "SL TP", "", (100,100,220,130))]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, WINDOW)
        self.assertFalse(report.candidates)
        self.assertIn("共用相同", report.reasons["sl_input"])

    def test_manual_ocr_positions_remain_unverified(self):
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], [
            c("Text", "123456", "AccountNumber", (20,20,200,50)),
            c("Edit","Volume","QuantityOrVolumeTextBox_Ald",(100,100,180,130)),
        ],WINDOW)
        for key in ("account_number", "positions_entry_price", "position_order_lot", "position_order_row"):
            self.assertNotIn(key, report.candidates)
            self.assertIn(key, report.reasons)
        self.assertNotIn("123456", report.as_text())

    def test_ctrader_real_order_panel_id_and_relative_geometry(self):
        controls = [
            c("Edit", "", "QuantityOrVolumeTextBox_AId", (614, 431, 702, 447),
              ("Custom:OrderQuantity", "Custom:AspNewMarketOrderControl_AId")),
            c("RadioButton", "", "AspNewMarketOrderBuyButton_AId",
              (800, 290, 992, 347), ("Custom:AspNewMarketOrderControl_AId",)),
            c("RadioButton", "", "AspNewMarketOrderSellButton_AId",
              (596, 290, 788, 347), ("Custom:AspNewMarketOrderControl_AId",)),
            c("CheckBox", "Stop loss", "CheckBoxStopLoss_AId", (596, 475, 706, 492)),
            c("CheckBox", "Take profit 1", "CheckBoxTakeProfit_AId", (861, 475, 992, 492)),
            c("CheckBox", "Take profit 2", "CheckBoxTakeProfit_AId", (861, 633, 992, 650)),
            c("Edit", "", "SpinnerContent_AId", (596, 502, 711, 525)),
            c("Edit", "", "SpinnerContent_AId", (861, 502, 976, 525)),
            c("Edit", "", "SpinnerContent_AId", (596, 532, 711, 555)),
            c("Edit", "", "SpinnerContent_AId", (861, 532, 976, 555)),
            c("Edit", "", "SpinnerContent_AId", (596, 560, 711, 584)),
            c("Edit", "", "SpinnerContent_AId", (861, 560, 976, 584)),
        ]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"],
                           controls, (0, 0, 1050, 1000))
        wanted = {"lot_input", "sl_checkbox", "tp_checkbox",
                  "sl_input", "tp_input", "buy_button", "sell_button"}
        self.assertEqual(set(report.candidates), wanted)
        self.assertEqual(report.candidates["sl_input"].rect, (596, 502, 711, 525))
        self.assertEqual(report.candidates["tp_input"].rect, (861, 502, 976, 525))
        self.assertIn("低信度", report.candidates["sl_input"].evidence)
        self.assertIn("未儲存", report.as_text())

    def test_ctrader_duplicate_stop_boxes_do_not_guess(self):
        controls = [
            c("Edit", "", "QuantityOrVolumeTextBox_AId", (614, 431, 702, 447)),
            c("CheckBox", "Stop loss", "CheckBoxStopLoss_AId", (596, 475, 706, 492)),
            c("CheckBox", "Stop loss", "CheckBoxStopLoss_AId", (596, 476, 706, 493)),
            c("CheckBox", "Take profit 1", "CheckBoxTakeProfit_AId", (861, 475, 992, 492)),
        ]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, (0,0,1100,900))
        self.assertNotIn("sl_checkbox", report.candidates)
        self.assertNotIn("tp_checkbox", report.candidates)

    def test_ctrader_unrelated_chart_buy_buttons_do_not_match(self):
        controls = [
            c("Edit", "", "QuantityOrVolumeTextBox_AId", (614,431,702,447)),
            c("Button", "", "BuyButton_AId", (278,130,367,184)),
            c("Button", "", "SellButton_AId", (183,130,272,184)),
            c("RadioButton", "", "AspNewMarketOrderBuyButton_AId",
              (800,290,992,347), ("Custom:ChartView_AId",)),
        ]
        report = match_all("cTrader", CALIBRATION_TARGETS["cTrader"], controls, (0,0,1100,900))
        self.assertNotIn("buy_button", report.candidates)
        self.assertNotIn("sell_button", report.candidates)

    def test_bad_handle_and_unknown_platform_rejected(self):
        with self.assertRaises(ValueError):
            inspect_all_targets(0, "cTrader", [])
        with self.assertRaises(ValueError):
            inspect_all_targets(42, "TradingView", [])

if __name__=="__main__":
    unittest.main()
