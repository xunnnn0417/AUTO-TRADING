"""Stage-specific final-order and position-confirm UIA safety regression tests.

No real broker windows are touched; these are synthetic UIA records only.
"""
import unittest
from trading_helper.calibration_scan import Control, match_all
from trading_helper.post_entry_scan import classify_post_entry, POST_ENTRY_TARGETS
from trading_helper.gui import CALIBRATION_TARGETS

B = (0,0,2000,1200)

def c(kind,aid,rect=(400,360,550,398),name="",ancestors=()):
    return Control(kind,name,aid,rect,ancestors=ancestors)

def known_volume():
    return c("Edit","QuantityOrVolumeTextBox_AId",(1500,419,1566,441),
             ancestors=("userControl","Custom AspNewMarketOrderControl_AId"))

def known_submit(rect=(1471,720,1867,743), ancestors=(
    "Custom AspPlaceOrderButton_AId",
    "Custom PropertySectionView_AId",
)):
    return c(
        "Button",
        "Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId",
        rect, name="Place order", ancestors=ancestors,
    )

class SubmitCalibrationTests(unittest.TestCase):
    def test_stage_counts_and_meaningful_new_roles(self):
        ct=dict(CALIBRATION_TARGETS["cTrader"])
        mt=dict(CALIBRATION_TARGETS["MT5"])
        self.assertEqual(len(ct),15)
        self.assertEqual(len(mt),14)
        self.assertIn("order_submit_button",ct)
        self.assertIn("order_submit_buy",mt)
        self.assertIn("order_submit_sell",mt)
        self.assertIn("position_modify_confirm",ct)
        self.assertIn("position_modify_confirm",mt)
        self.assertIn("position_modify_confirm",dict(POST_ENTRY_TARGETS))
        self.assertNotEqual(ct["buy_button"],ct["order_submit_button"])

    def test_ctrader_real_submit_candidate_separate_from_direction_radio(self):
        controls=[
          known_volume(),
          c("RadioButton","AspNewMarketOrderBuyButton_AId",(1660,280,1860,337),
            ancestors=("Custom AspNewMarketOrderControl_AId",)),
          known_submit(),
        ]
        report=match_all("cTrader",(("order_submit_button","實際送單"),),controls,B)
        self.assertEqual(set(report.candidates),{"order_submit_button"})
        self.assertEqual(report.candidates["order_submit_button"].rect,(1471,720,1867,743))
        self.assertIn("未",report.as_text())

    def test_ctrader_direction_only_is_never_submit(self):
        report=match_all("cTrader",(("order_submit_button","實際送單"),),[
          c("RadioButton","AspNewMarketOrderBuyButton_AId",(500,280,590,310),
            ancestors=("Custom AspNewMarketOrderControl_AId",))
        ],B)
        self.assertFalse(report.candidates)

    def test_ctrader_new_order_launcher_is_not_submit(self):
        report=match_all("cTrader",(("order_submit_button","送單"),),[
          c("Button","CreateNewMarketOrderButton_AId",(500,300,580,340),
            name="New Order",ancestors=("Custom AspNewMarketOrderControl_AId",))
        ],B)
        self.assertFalse(report.candidates)

    def test_ctrader_unrelated_place_order_button_is_rejected(self):
        report=match_all("cTrader",(("order_submit_button","送單"),),[
          known_volume(),
          known_submit(ancestors=("Custom SymbolSelector_AId",)),
        ],B)
        self.assertFalse(report.candidates)

    def test_multiple_submit_buttons_fail_closed(self):
        report=match_all("cTrader",(("order_submit_button","送單"),),[
            known_volume(), known_submit(),
            known_submit(rect=(1471,760,1867,783)),
        ],B)
        self.assertFalse(report.candidates)

    def test_ctrader_submit_requires_the_real_volume_panel(self):
        report=match_all("cTrader",(("order_submit_button","送單"),),[
            known_submit(),
        ],B)
        self.assertFalse(report.candidates)

    def test_mt5_market_buy_and_sell_are_not_new_order_openers(self):
        controls=[
          c("Button","",(100,330,245,366),"Buy by Market",
            ("Window OrderDialog",)),
          c("Button","",(260,330,410,366),"Sell by Market",
            ("Window OrderDialog",)),
          c("Button","",(450,330,530,366),"New Order",()),
        ]
        report=match_all("MT5",(
            ("order_submit_buy","市價買入送單"),("order_submit_sell","市價賣出送單")
        ),controls,B)
        self.assertEqual(set(report.candidates),{"order_submit_buy","order_submit_sell"})

    def test_mt5_pending_order_and_no_order_dialog_fail(self):
        controls=[
          c("Button","",(100,330,245,366),"Buy Stop",("Window OrderDialog",)),
          c("Button","",(260,330,410,366),"Sell Limit",("Window OrderDialog",)),
          c("Button","",(500,330,630,366),"Buy by Market",("Window Home",))
        ]
        report=match_all("MT5",(
            ("order_submit_buy","買入送單"),("order_submit_sell","賣出送單")
        ),controls,B)
        self.assertFalse(report.candidates)

    def test_modify_confirmation_requires_dialog_and_no_cancel(self):
        good=c("Button","ApplyPositionChanges_AId",
               (700,680,800,716),"Apply",
               ("Custom PositionModifyPanel_AId",))
        cancel=c("Button","CancelChanges_AId",
               (810,680,920,716),"Cancel",
               ("Custom PositionModifyPanel_AId",))
        report=match_all("cTrader",(("position_modify_confirm","確認修改"),),
                         [good,cancel],B)
        self.assertIn("position_modify_confirm",report.candidates)
        wrong=match_all("cTrader",(("position_modify_confirm","確認修改"),),[
            c("Button","ApplyPositionChanges_AId",(700,680,800,716),
              "Apply",("Custom MainOrderPanel",))
        ],B)
        self.assertFalse(wrong.candidates)

    def test_mt5_modify_label_only_in_modify_dialog(self):
        good=c("Button","",(500,450,650,485),
               "Modify",("Window Modify Order",))
        scan=match_all("MT5",(("position_modify_confirm","修改確認"),),[good],B)
        self.assertIn("position_modify_confirm",scan.candidates)
        unrelated=c("Button","",(500,450,650,485),
                    "Modify",("Window Navigator",))
        rejected=match_all("MT5",(("position_modify_confirm","修改確認"),),[unrelated],B)
        self.assertNotIn("position_modify_confirm",rejected.candidates)

    def test_two_confirm_buttons_are_ambiguous(self):
        controls=[
          c("Button","ApplyPositionChanges_AId",(700,680,800,716),
            "Apply",("Custom PositionModifyPanel_AId",)),
          c("Button","ConfirmPositionChanges_AId",(820,680,940,716),
            "Confirm",("Custom PositionModifyPanel_AId",)),
        ]
        report=match_all("MT5",(("position_modify_confirm","修改確認"),),controls,B)
        self.assertFalse(report.candidates)

    def test_post_entry_confirm_only_when_exactly_one_position(self):
        grid=c("DataGrid","PositionListDataGrid_AId",(20,500,1700,1040))
        row=c("DataItem","PositionDataItem",(40,588,1600,622),
              ancestors=("DataGrid PositionListDataGrid_AId",))
        confirm=c("Button","ApplyPositionChanges_AId",(700,330,800,366),
                  "Apply",("Custom PositionModifyPanel_AId",))
        single=classify_post_entry([grid,row,confirm],B)
        self.assertEqual(single.state,"single")
        self.assertIn("position_modify_confirm",single.candidates)
        multiple=classify_post_entry([grid,row,
            c("DataItem","PositionDataItem",(40,628,1600,662),
              ancestors=("DataGrid PositionListDataGrid_AId",)),confirm],B)
        self.assertEqual(multiple.state,"multiple")
        self.assertFalse(multiple.candidates)
        empty=classify_post_entry([grid,confirm],B)
        self.assertEqual(empty.state,"empty")
        self.assertFalse(empty.candidates)

if __name__=="__main__":
    unittest.main()
