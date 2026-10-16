"""MT5 screenshot fallback is visual PREVIEW only; mock RGB frames, no broker."""
import unittest
from PIL import Image, ImageDraw
from types import SimpleNamespace
from unittest.mock import patch
from trading_helper.mt5_visual_scan import detect_order_dialog_regions
from trading_helper.calibration_scan import inspect_all_targets
from trading_helper.calibration_scan import _resolve_mt5_capture_origin


def frame():
    img=Image.new("RGB",(1126,603),(46,46,46))
    g=ImageDraw.Draw(img)
    # Relative layout from user-provided MT5 screenshot, but only synthetic
    # color blocks and a white pseudo quote; no user/account pixels.
    g.rectangle((250,468,477,495),fill=(227,65,65))
    g.rectangle((495,468,722,495),fill=(63,121,250))
    g.text((515,374),"4104.60",fill="white",stroke_width=1)
    return img


class VisualMT5OrderScanTests(unittest.TestCase):
    def test_finds_three_distinct_preview_regions(self):
        areas=detect_order_dialog_regions(frame())
        self.assertEqual(set(areas),{
            "order_submit_sell","order_submit_buy","ask_price"
        })
        red=areas["order_submit_sell"]
        blue=areas["order_submit_buy"]
        price=areas["ask_price"]
        self.assertLess(red[2],blue[0])
        self.assertLess(price[3],red[1])
        self.assertGreater((price[0]+price[2])/2,blue[0])
    def test_real_scan_low_confidence_is_previews_not_blocking_warning(self):
        # Regression: visual fallback used to append an advisory to
        # ScanReport.warnings, which disabled ALL checkboxes after preview.
        # No broker window, mouse, account, or order used by this test.
        fake_info=SimpleNamespace(
            rectangle=SimpleNamespace(left=0,top=0,right=1126,bottom=603),
            name="Order: XAUUSD",automation_id="",control_type="Window",
            enabled=True,visible=True,children=lambda:[],
        )
        fake_window=SimpleNamespace(
            element_info=fake_info,window_text=lambda:"Order: XAUUSD",
        )
        fake_desktop=SimpleNamespace(window=lambda handle:fake_window)
        targets=(
            ("ask_price","目前價格"),
            ("order_submit_sell","Sell 按市價"),
            ("order_submit_buy","Buy 按市價"),
        )
        with patch("pywinauto.Desktop",return_value=fake_desktop), \
             patch("PIL.ImageGrab.grab",return_value=frame()), \
             patch("trading_helper.calibration_scan._mt5_client_geometry",
                   return_value=((1126,603),(0,0))):
            result=inspect_all_targets(
                912, "MT5", targets, scan_related=False
            )
        self.assertEqual(set(result.candidates),{k for k,_ in targets})
        self.assertFalse(result.warnings, result.warnings)
        self.assertTrue(all(
            "低信度" in item.evidence for item in result.candidates.values()
        ))

    def test_preview_surrounds_actual_button_bars_and_quote_text(self):
        areas=detect_order_dialog_regions(frame())
        sell=areas["order_submit_sell"]
        buy=areas["order_submit_buy"]
        quote=areas["ask_price"]
        # The dark-background outline must go AROUND each colored bar,
        # not inside the bar or 36 pixels above the clickable region.
        self.assertLessEqual(sell[0],250)
        self.assertLessEqual(sell[1],468)
        self.assertGreaterEqual(sell[2],478)
        self.assertGreaterEqual(sell[3],496)
        self.assertLessEqual(buy[0],495)
        self.assertLessEqual(buy[1],468)
        self.assertGreaterEqual(buy[2],723)
        self.assertGreaterEqual(buy[3],496)
        self.assertLess(quote[1],374)
        self.assertGreater(quote[3],385)
        self.assertLess(quote[0],515)
        self.assertGreater(quote[2],575)

    def test_screenshot_client_vs_full_window_origin(self):
        bounds=(100,100,1226,703)
        client_size=(1126,565)
        client_origin=(100,138)
        full=frame()
        client=full.crop((0,38,1126,603))
        self.assertEqual(
            _resolve_mt5_capture_origin(full.size,bounds,client_size,client_origin),
            (100,100))
        self.assertEqual(
            _resolve_mt5_capture_origin(client.size,bounds,client_size,client_origin),
            (100,138))
        # Before fix this rect was 38px too high due to window/client mix.
        quote=detect_order_dialog_regions(client)["ask_price"]
        price_screen_y=(quote[1]+quote[3])/2+client_origin[1]
        self.assertGreater(price_screen_y,100+357)
        self.assertLess(price_screen_y,100+397)
        sell=detect_order_dialog_regions(client)["order_submit_sell"]
        self.assertLessEqual(sell[1]+client_origin[1],100+468)
        self.assertGreaterEqual(sell[3]+client_origin[1],100+496)
        self.assertIsNone(
            _resolve_mt5_capture_origin((1100,532),bounds,client_size,client_origin)
        )

    def test_no_quote_rejects_all(self):
        img=frame()
        ImageDraw.Draw(img).rectangle((490,335,665,440),fill=(46,46,46))
        self.assertEqual(detect_order_dialog_regions(img),{})
    def test_chart_lines_do_not_qualify(self):
        img=Image.new("RGB",(1126,603),(46,46,46))
        g=ImageDraw.Draw(img)
        for i in range(100,800,35):
            g.line((i,80,i+20,390),fill=(230,30,40),width=1)
            g.line((i+10,110,i+30,380),fill=(50,110,240),width=1)
        self.assertFalse(detect_order_dialog_regions(img))
    def test_only_sell_bar_is_rejected(self):
        img=frame()
        ImageDraw.Draw(img).rectangle((495,468,722,495),fill=(46,46,46))
        self.assertEqual(detect_order_dialog_regions(img),{})
    def test_two_button_pairs_are_ambiguous(self):
        img=frame()
        g=ImageDraw.Draw(img)
        g.rectangle((250,330,477,357),fill=(227,65,65))
        g.rectangle((495,330,722,357),fill=(63,121,250))
        g.text((515,240),"4104.60",fill="white",stroke_width=1)
        self.assertEqual(detect_order_dialog_regions(img),{})


if __name__=="__main__":
    unittest.main()
