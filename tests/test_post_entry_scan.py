"""P2 v5 post-entry position safety: never choose an arbitrary trade."""
import unittest

from trading_helper.calibration_scan import Control, match_all
from trading_helper.gui import CALIBRATION_TARGETS
from trading_helper.post_entry_scan import classify_post_entry, POST_ENTRY_TARGETS

B=(0,0,1920,1080)
def control(kind,aid,rect,name="",ancestors=()):
    return Control(kind,name,aid,rect,ancestors=ancestors)

def base_grid():
    return [control("DataGrid","PositionListDataGrid_AId",(40,500,1420,1020))]

def row(y=590):
    return control("DataItem","PositionDataItem",(50,y,1400,y+34),
                   ancestors=("DataGrid PositionListDataGrid_AId",))

def header(name,rect):
    return control("HeaderItem","",rect,name,
                   ancestors=("Header PART_ColumnHeadersPresenter",
                              "DataGrid PositionListDataGrid_AId"))

class PostEntrySafetyTests(unittest.TestCase):
    def test_empty_positions_waits_with_no_candidates(self):
        report=classify_post_entry(base_grid(),B)
        self.assertEqual(report.state,"empty")
        self.assertEqual(report.count,0)
        self.assertFalse(report.candidates)
        self.assertIn("不下單",report.as_text())

    def test_two_positions_block_even_if_headers_exist(self):
        controls=base_grid()+[row(590),row(625),header("Entry Price",(340,560,440,585))]
        report=classify_post_entry(controls,B)
        self.assertEqual(report.state,"multiple")
        self.assertEqual(report.count,2)
        self.assertEqual(report.candidates,{})
        self.assertIn("停止自動挑選",report.as_text())

    def test_unique_position_can_propose_only_matching_columns(self):
        controls=base_grid()+[
            row(),header("Entry Price",(340,560,440,585)),
            header("Volume",(175,560,285,585)),
            header("Take Profit",(610,560,750,585)),
        ]
        report=classify_post_entry(controls,B)
        self.assertEqual(report.state,"single")
        self.assertEqual(report.count,1)
        self.assertEqual(set(report.candidates),
                         {"positions_entry_price","position_order_lot","position_order_row"})
        self.assertEqual(report.candidates["position_order_row"].rect,(610,590,750,624))
        self.assertNotIn("position_sl_input",report.candidates)
        self.assertNotIn("position_tp_input",report.candidates)

    def test_modify_prices_require_open_modify_pane_and_unique_edits(self):
        baseline=base_grid()+[row()]
        boxes=[
            control("Edit","ModifyPositionStopLossPriceInput_AId",
                    (800,330,950,355),ancestors=("Custom PositionModifyPanel",)),
            control("Edit","ModifyPositionTakeProfitPriceInput_AId",
                    (800,365,950,390),ancestors=("Custom PositionModifyPanel",)),
        ]
        safe=classify_post_entry(baseline+boxes,B)
        self.assertEqual(safe.state,"single")
        self.assertEqual(
            set(safe.candidates),{"position_sl_input","position_tp_input"}
        )
        absent=classify_post_entry(baseline+[
            control("Edit","SpinnerContent_AId",(800,330,950,355),
                    ancestors=("Custom MainOrderPanel",)),
        ],B)
        self.assertFalse(absent.candidates)
        duplicated=classify_post_entry(baseline+boxes+[boxes[0]],B)
        self.assertNotIn("position_sl_input",duplicated.candidates)
        self.assertIn("position_tp_input",duplicated.candidates)

    def test_multiple_similar_headers_rejected(self):
        controls=base_grid()+[
            row(),header("Entry Price",(340,560,440,585)),
            header("Entry Price",(455,560,555,585)),
        ]
        report=classify_post_entry(controls,B)
        self.assertEqual(report.state,"single")
        self.assertNotIn("positions_entry_price",report.candidates)

    def test_unverified_grid_never_picks_first_position(self):
        report=classify_post_entry([row()],B)
        self.assertEqual(report.state,"unknown")
        self.assertIsNone(report.count)
        self.assertFalse(report.candidates)

    def test_account_number_selector_uia_was_identified_without_reading_value(self):
        rect=(1702,45,1758,61)
        controls=[control(
            "Text","CTraderAccountNumberTextBlock_AId",rect,
            name="123456789",
            ancestors=("Button CTraderAccountSelectorButton_AId",
                       "Custom CTraderTopRightMenuAccountSelector_AId",
                       "Custom TopRightMenuView_AId")),
        ]
        report=match_all("cTrader",CALIBRATION_TARGETS["cTrader"],controls,
                         (-9,-9,1929,1029))
        self.assertIn("account_number",report.candidates)
        self.assertEqual(report.candidates["account_number"].rect,rect)
        self.assertNotIn("123456789",report.as_text())

    def test_account_number_rejects_duplicate_or_unbound_label(self):
        control_data=control("Text","CTraderAccountNumberTextBlock_AId",
                             (1702,45,1758,61),
                             ancestors=("Custom OtherMenu",))
        report=match_all("cTrader",CALIBRATION_TARGETS["cTrader"],
                         [control_data],(-9,-9,1929,1029))
        self.assertNotIn("account_number",report.candidates)

if __name__=="__main__":
    unittest.main()
