import unittest

from trading_helper.field_detection import Element, match_fields


BOUNDS = (0, 0, 1200, 800)


class FieldDetectionTests(unittest.TestCase):
    def test_direct_named_edit_controls(self):
        elements = [
            Element("Volume", "Edit", (200, 100, 330, 130)),
            Element("Stop Loss", "Edit", (200, 145, 330, 175)),
            Element("Take Profit", "Edit", (200, 190, 330, 220)),
        ]
        found, warnings = match_fields(elements, BOUNDS)
        self.assertEqual(set(found), {"lot_input", "sl_input", "tp_input"})
        self.assertEqual(warnings, ())

    def test_adjacent_label_can_identify_blank_edit(self):
        elements = [
            Element("Volume", "Text", (35, 100, 135, 130)),
            Element("", "Edit", (150, 100, 280, 130)),
        ]
        found, warnings = match_fields(elements, BOUNDS)
        self.assertEqual(found["lot_input"].source, "鄰近標籤")
        self.assertIn("sl_input: 尚未可靠找到輸入欄", warnings)

    def test_table_header_is_not_an_input(self):
        found, warnings = match_fields(
            [Element("Take Profit", "HeaderItem", (240, 100, 360, 130))],
            BOUNDS,
        )
        self.assertEqual(found, {})
        self.assertIn("tp_input: 尚未可靠找到輸入欄", warnings)

    def test_duplicate_fields_are_rejected(self):
        elements = [
            Element("Volume", "Edit", (200, 100, 330, 130)),
            Element("Volume", "Edit", (400, 100, 530, 130)),
        ]
        found, warnings = match_fields(elements, BOUNDS)
        self.assertNotIn("lot_input", found)
        self.assertTrue(any("有 2 個可能欄位" in warning for warning in warnings))

    def test_offscreen_and_disabled_controls_are_rejected(self):
        found, warnings = match_fields(
            [
                Element("Volume", "Edit", (-32000, -32000, -31800, -31970)),
                Element("Stop Loss", "Edit", (100, 100, 240, 130), False),
                Element("Take Profit", "Text", (100, 150, 240, 180)),
            ],
            BOUNDS,
        )
        self.assertEqual(found, {})
        self.assertEqual(len(warnings), 3)

    def test_two_fields_cannot_share_the_same_coordinates(self):
        found, warnings = match_fields(
            [
                Element("Volume", "Edit", (100, 100, 240, 130)),
                Element("Stop Loss", "Edit", (100, 100, 240, 130)),
            ],
            BOUNDS,
        )
        self.assertEqual(found, {})
        self.assertTrue(any("重疊" in warning for warning in warnings))

    def test_invalid_control_not_treated_as_input(self):
        found, _ = match_fields(
            [Element("Stop Loss", "Button", (200, 100, 330, 130))],
            BOUNDS,
        )
        self.assertNotIn("sl_input", found)

    def test_label_above_input(self):
        found, warnings = match_fields(
            [
                Element("Take Profit", "Text", (200, 90, 310, 110)),
                Element("", "Edit", (195, 120, 335, 150)),
            ],
            BOUNDS,
        )
        self.assertIn("tp_input", found)
        self.assertIn("lot_input: 尚未可靠找到輸入欄", warnings)


if __name__ == "__main__":
    unittest.main()
