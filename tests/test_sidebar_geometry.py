"""Physical sidebar parking; never touches a broker window."""
import unittest
from trading_helper.sidebar_geometry import parked_rect


class SidebarGeometryTests(unittest.TestCase):
    def test_expanded_window_left_at_handle_location_is_recovered(self):
        self.assertEqual(parked_rect((1885,123,2310,818), (0,0,1920,1020), 123),
                         (1495,123,1920,818))

    def test_negative_monitor_origin_and_bottom_clamp(self):
        self.assertEqual(parked_rect((-25,1000,400,1695), (-1920,-100,0,980), 1000),
                         (-425,285,0,980))

    def test_collapsed_handle_is_flush_and_oversize_window_keeps_top_visible(self):
        self.assertEqual(parked_rect((1885,70,1920,123), (0,0,1920,1020), 70),
                         (1885,70,1920,123))
        self.assertEqual(parked_rect((10,0,435,1200), (0,0,1920,1020), 500),
                         (1495,0,1920,1200))
