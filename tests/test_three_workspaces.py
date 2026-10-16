"""Three-workspace UX regressions using an isolated offline helper instance."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QScrollArea, QStackedWidget

from trading_helper import gui

EDIT_BUTTONS=(
    "試算表設定","綁定場內視窗","綁定場外視窗",
    "校準 cTrader","校準 MT5","校準 TradingView",
)
TRADE_BUTTONS=(
    "重新讀取","填入場內","填入場外","填入兩邊",
    "更新","查看止盈/損","手動同步場外 SL/TP",
    "手動繪製 TV",
)


class ThreeWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp=QApplication.instance() or QApplication([])

    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder=Path(tmp.name)
        config,profiles=gui.ConfigStore,gui.ProfileStore
        with patch.object(gui,"ConfigStore",side_effect=lambda:config(path=folder/"config.json")),\
             patch.object(gui,"ProfileStore",side_effect=lambda x:profiles(x,path=folder/"profiles.json")),\
             patch.object(gui.WindowController,"warm_ocr",return_value=None),\
             patch.object(gui.TradingHelperApp,"read_sheet",lambda _:None):
            self.win=gui.TradingHelperApp()
        self.win.show()
        self.qtapp.processEvents()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def page(self,name):
        self.win.switch_workspace(name)
        self.qtapp.processEvents()

    def test_only_three_workspaces_and_one_active(self):
        w=self.win
        self.assertIsInstance(w.main_pages,QStackedWidget)
        self.assertEqual(w.main_pages.count(),3)
        self.assertEqual(w.main_pages.currentIndex(),0)
        self.assertEqual(set(w.page_nav),{"交易","編輯","紀錄"})
        for index,name in enumerate(("交易","編輯","紀錄")):
            self.page(name)
            self.assertEqual(w.main_pages.currentIndex(),index)
            self.assertTrue(w.page_nav[name].isChecked())
            self.assertEqual(sum(bool(b.isChecked()) for b in w.page_nav.values()),1)
        self.page("交易")

    def test_trade_is_non_scrolling_and_every_core_trade_control_is_visible(self):
        self.page("交易")
        w=self.win
        self.assertFalse(w.trade_page.findChildren(QScrollArea))
        self.assertFalse(w.main_pages.findChildren(QScrollArea))
        self.assertTrue(w.auto_entry_on_fill_both.isVisible())
        self.assertFalse(w.auto_entry_on_fill_both.isChecked())
        self.assertTrue(w.internal_platform.isVisible())
        self.assertTrue(w.external_platform.isVisible())
        self.assertEqual(len(w.data_labels),11)
        self.assertEqual(len(w.parameter_inputs),4)
        for label in TRADE_BUTTONS:
            with self.subTest(label=label):
                targets=[b for b in w.findChildren(QPushButton) if b.text()==label]
                self.assertEqual(len(targets),1)
                self.assertTrue(targets[0].isVisible())
        for label in EDIT_BUTTONS:
            self.assertFalse(w.action_buttons[label].isVisible())
        self.assertFalse(w.log_text.isVisible())
        self.assertTrue(w.recent_status.isVisible())

    def test_edit_page_holds_original_actions_not_recreated(self):
        self.page("編輯")
        w=self.win
        self.assertTrue(w.edit_page.isVisible())
        for label in EDIT_BUTTONS:
            with self.subTest(label=label):
                self.assertIsInstance(w.action_buttons[label],QPushButton)
                self.assertTrue(w.action_buttons[label].isVisible())
                self.assertTrue(w.action_buttons[label].isEnabled())
        self.assertFalse(w.action_buttons["填入兩邊"].isVisible())
        self.assertFalse(w.log_text.isVisible())
        self.assertEqual(
            {c.objectName() for c in w.edit_page.findChildren(QGroupBox)},
            {"editSheetGroup","editWindowGroup","editCalibrationGroup","editManualEntryGroup"}
        )

    def test_records_page_reuses_original_log_and_pnl_button(self):
        self.page("紀錄")
        w=self.win
        self.assertTrue(w.records_page.isVisible())
        self.assertFalse(w.daily_pnl_history_button.isVisible())
        self.assertTrue(w.log_text.isVisible())
        self.assertTrue(w.log_text.isReadOnly())
        w._append_log("Offline QA record")
        self.assertIn("Offline QA record",w.log_text.toPlainText())
        self.assertIn("Offline QA record",w.recent_status.text())
        self.page("交易")
        self.assertTrue(w.recent_status.isVisible())

    def test_edit_actions_have_compact_horizontal_tool_groups(self):
        from PySide6.QtCore import QPoint
        w=self.win
        self.page("編輯")
        groups=[
            w.edit_page.findChild(QGroupBox,name)
            for name in ("editSheetGroup","editWindowGroup","editCalibrationGroup")
        ]
        points=[group.mapTo(w.edit_page,QPoint(0,0)) for group in groups]
        self.assertTrue(all(g.isVisible() for g in groups))
        self.assertLessEqual(max(p.y() for p in points)-min(p.y() for p in points),4)
        self.assertLess(points[0].x()+groups[0].width(),points[1].x())
        self.assertLess(points[1].x()+groups[1].width(),points[2].x())
        for label in EDIT_BUTTONS:
            self.assertLessEqual(w.action_buttons[label].width(),170)
        manual=w.edit_page.findChild(QGroupBox,"editManualEntryGroup")
        self.assertLessEqual(manual.width(),690)
        self.assertFalse(manual.isVisible())
        self.page("交易")
        self.assertTrue(w.parameter_inputs["internal_entry_price"].isVisible())

    def test_record_history_is_an_inline_action_not_a_full_width_bar(self):
        w=self.win
        self.page("紀錄")
        self.assertLessEqual(w.daily_pnl_history_button.width(),145)
        self.assertGreaterEqual(w.log_text.minimumHeight(),140)
        self.assertLessEqual(w.log_text.maximumHeight(),166)
        # History is preserved as a callable feature but hidden until redesign.
        self.assertFalse(w.daily_pnl_history_button.isVisible())
        self.assertTrue(callable(w.show_daily_pnl_history))
        log_box=w.records_page.findChild(QGroupBox,"activityCard")
        self.assertLessEqual(log_box.height(),235)
        self.assertGreaterEqual(log_box.height(),160)

    def test_trade_two_column_geometry_preserves_all_existing_values(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QGroupBox
        w=self.win
        self.page("交易")
        w.resize(1150,630)
        self.qtapp.processEvents()

        def in_trade(widget):
            p=widget.mapTo(w.trade_page,QPoint(0,0))
            return (p.x(),p.y(),widget.width(),widget.height())

        info=w.trade_page.findChild(QGroupBox,"dataCard")
        params=w.trade_page.findChild(QGroupBox,"parameterCard")
        actions=w.trade_page.findChild(QGroupBox,"actionsCard")
        manual=w.trade_page.findChild(QGroupBox,"afterEntryCard")
        ix,iy,iw,ih=in_trade(info)
        px,py,pw,ph=in_trade(params)
        ax,ay,aw,ah=in_trade(actions)
        mx,my,mw,mh=in_trade(manual)
        self.assertGreater(px,ix+iw)
        self.assertLessEqual(abs(py-iy),24)
        self.assertGreaterEqual(ax,px)
        self.assertGreater(ay,py+ph-2)
        self.assertGreaterEqual(mx,px)
        self.assertGreater(my,ay+ah-2)
        self.assertLessEqual(ax+aw,w.trade_page.width())
        self.assertLessEqual(py+ph,w.trade_page.height())
        self.assertEqual(len(w.data_labels),11)
        for key,label in w.data_labels.items():
            with self.subTest(key=key):
                self.assertTrue(label.isVisible())
                x,y,width,height=in_trade(label)
                self.assertGreater(width,0)
                self.assertGreater(height,0)
                self.assertGreaterEqual(x,ix)
                self.assertLessEqual(x+width,ix+iw+1)
                self.assertLessEqual(y+height,iy+ih+1)
        for key,edit in w.parameter_inputs.items():
            with self.subTest(key=key):
                self.assertTrue(edit.isVisible())
                x,y,width,height=in_trade(edit)
                self.assertLessEqual(y+height,py+ph+1)
        self.assertFalse(w.trade_page.findChildren(QScrollArea))

    def test_centered_summary_aligned_platforms_and_inline_actions(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtWidgets import QWidget, QGroupBox
        for width,height in ((1150,630),(1020,580)):
            with self.subTest(width=width,height=height):
                w=self.win
                self.page("交易")
                w.resize(width,height)
                self.qtapp.processEvents()
                info=w.trade_page.findChild(QGroupBox,"dataCard")
                platform_row=w.trade_page.findChild(QWidget,"platformSelectorRow")
                reload_row=w.trade_page.findChild(QWidget,"reloadToolbar")
                inline=w.trade_page.findChild(QWidget,"parameterInlineActions")
                self.assertIsNotNone(info)
                self.assertIsNotNone(platform_row)
                self.assertIsNotNone(reload_row)
                self.assertIsNotNone(inline)
                self.assertTrue(w.reload_sheet_button.isVisible())
                self.assertEqual(w.preview_sl_tp_button.objectName(),"paramPreviewAction")
                self.assertEqual(w.parameter_update_button.objectName(),"paramUpdateAction")
                self.assertEqual(inline.parentWidget().objectName(),"parameterCard")
                self.assertLessEqual(w.preview_sl_tp_button.height(),36)
                self.assertLessEqual(w.parameter_update_button.height(),36)
                self.assertEqual(w.preview_sl_tp_button.parentWidget(),inline)
                self.assertEqual(w.parameter_update_button.parentWidget(),inline)

                def pos(obj):
                    return obj.mapTo(w.trade_page,QPoint(0,0))
                entry=w.parameter_inputs["internal_entry_price"]
                self.assertLessEqual(
                    abs(pos(entry).y()+entry.height()/2 -
                        (pos(w.preview_sl_tp_button).y()+
                         w.preview_sl_tp_button.height()/2)),8
                )
                self.assertLess(pos(reload_row).y(),pos(platform_row).y())
                heading=w.trade_page.findChild(QWidget,"tradeDataHeading")
                self.assertIsNotNone(heading)
                self.assertLessEqual(abs(pos(heading).y()-pos(w.reload_sheet_button).y()),12)
                self.assertGreater(w.internal_platform.width(),150)
                self.assertGreater(w.external_platform.width(),150)
                summary=w.trade_page.findChildren(QWidget,"centeredSummaryCell")
                self.assertEqual(len(summary),3)
                self.assertLess(pos(platform_row).y(),pos(summary[0]).y())
                self.assertLess(pos(entry).x()+entry.width(),pos(w.preview_sl_tp_button).x())
                right_edge=pos(w.parameter_update_button).x()+w.parameter_update_button.width()
                right_card=w.trade_page.findChild(QGroupBox,"parameterCard")
                self.assertLessEqual(abs(right_edge-(pos(right_card).x()+right_card.width()-14)),26)
                centers=[]
                for key,cell in zip(
                    ("symbol","sheet_direction","original_sl_points"),summary
                ):
                    label=w.data_labels[key]
                    self.assertTrue(label.alignment() & Qt.AlignHCenter)
                    cell_left=pos(cell).x()
                    label_center=pos(label).x()+label.width()/2
                    self.assertAlmostEqual(
                        label_center,cell_left+cell.width()/2,delta=3
                    )
                    centers.append(label_center)
                self.assertLess(centers[0],centers[1])
                self.assertLess(centers[1],centers[2])
                headers=w.trade_page.findChildren(QWidget,"tradePlatformCell")
                self.assertEqual(len(headers),2)
                for key,header in zip(
                    ("internal_direction","external_direction"),headers
                ):
                    first_row=w.data_labels[key].parentWidget()
                    self.assertAlmostEqual(
                        pos(header).x(),pos(first_row).x(),delta=4
                    )
                self.assertFalse(w.trade_page.findChildren(QScrollArea))

    def test_right_side_actions_are_ordered_and_not_clipped(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QGroupBox, QWidget
        w = self.win
        self.page("交易")
        for width, height in ((1150, 630), (1020, 580)):
            with self.subTest(width=width, height=height):
                w.resize(width, height)
                self.qtapp.processEvents()
                info = w.trade_page.findChild(QGroupBox, "dataCard")
                actions = w.trade_page.findChild(QGroupBox, "actionsCard")
                manual = w.trade_page.findChild(QGroupBox, "afterEntryCard")
                options = w.trade_page.findChild(QWidget, "automationOptionRow")
                fill_internal = w.action_buttons["填入場內"]
                fill_external = w.action_buttons["填入場外"]
                fill_both = w.action_buttons["填入兩邊"]

                def pos(widget):
                    return widget.mapTo(w.trade_page, QPoint(0, 0))

                params = w.trade_page.findChild(QGroupBox, "parameterCard")
                self.assertLessEqual(abs(pos(params).y()-pos(info).y()), 24)
                self.assertGreater(pos(actions).y(), pos(params).y()+params.height()-2)
                self.assertLessEqual(abs(pos(fill_internal).y()-pos(fill_external).y()), 3)
                self.assertLess(pos(fill_internal).y()+fill_internal.height(), pos(fill_both).y())
                self.assertLess(pos(fill_both).y()+fill_both.height(), pos(options).y())
                self.assertLess(pos(options).y()+options.height(), pos(manual).y())
                self.assertLessEqual(pos(manual).y()+manual.height(), w.trade_page.height())
                for button in (fill_internal, fill_external, fill_both,
                               w.findChild(QPushButton, "manualSyncSlTp"),
                               w.findChild(QPushButton, "manualDrawTv")):
                    self.assertTrue(button.isVisible())
                    self.assertGreater(button.width(), 90)
                    self.assertLessEqual(pos(button).x()+button.width(), w.trade_page.width())
                    self.assertLessEqual(pos(button).y()+button.height(), w.trade_page.height())

    def test_chrome_and_config_remain_unchanged(self):
        w=self.win
        self.assertTrue(w.chrome_minimize.isVisible())
        self.assertTrue(w.chrome_maximize.isVisible())
        self.assertTrue(w.chrome_close.isVisible())
        self.assertTrue(w.profile_combo.isVisible())
        self.assertTrue(w.sheet_note_indicator.isVisible())
        self.assertEqual(w.auto_entry_on_fill_both.isChecked(),False)
        self.assertEqual(
            [a.text() for a in w.profile_manage_menu.actions() if not a.isSeparator()],
            ["建立新方案","儲存目前方案","重新命名目前方案","刪除目前方案"]
        )
        # Page navigation never writes a trading config or triggers a trade.
        w.store.data["ui"]["test_marker"]="not modified"
        for name in ("編輯","紀錄","交易"):
            self.page(name)
        self.assertEqual(w.store.data["ui"]["test_marker"],"not modified")

if __name__=="__main__":
    unittest.main()
