from decimal import Decimal
import unittest

from trading_helper.expected_sl_adjustment import (
    choose_repeat_adjustment, choose_widened_sl, random_repeat_adjustment_range, widened_sl_range,
)


class WidenedSlSuggestionTests(unittest.TestCase):
    def test_range_is_original_to_one_and_a_half_points_farther(self):
        self.assertEqual(widened_sl_range(Decimal("-6.70")), (Decimal("-8.20"), Decimal("-6.70")))
        self.assertIsNone(widened_sl_range(Decimal("1.2")))   # would cross zero
        self.assertIsNone(widened_sl_range(None))

    def test_choice_is_two_decimals_inside_the_range(self):
        class Last:
            def randrange(self, n):
                return n - 1
        self.assertEqual(choose_widened_sl(Decimal("-6.70"), rng=Last()), Decimal("-6.70"))
        for _ in range(50):
            value = choose_widened_sl(Decimal("-6.70"))
            self.assertTrue(Decimal("-8.20") <= value <= Decimal("-6.70"))
            self.assertEqual(value, value.quantize(Decimal("0.01")))


class ExpectedSlAdjustmentTests(unittest.TestCase):
    def test_subtracts_one_from_previous_negative_stop(self):
        bounds = random_repeat_adjustment_range(
            Decimal("-8.35"), Decimal("-8.59")
        )
        self.assertEqual(bounds, (Decimal("-9.59"), Decimal("-8.35")))

    def test_subtracts_one_from_previous_positive_stop(self):
        bounds = random_repeat_adjustment_range(
            Decimal("8.35"), Decimal("8.59")
        )
        self.assertEqual(bounds, (Decimal("7.59"), Decimal("8.35")))

    def test_rejects_missing_or_opposite_sign_inputs(self):
        self.assertIsNone(random_repeat_adjustment_range(None, Decimal("-8.59")))
        self.assertIsNone(random_repeat_adjustment_range(
            Decimal("-8.35"), Decimal("8.59")
        ))

    def test_rejects_adjustment_that_crosses_zero_or_has_no_new_value(self):
        self.assertIsNone(random_repeat_adjustment_range(
            Decimal("0.25"), Decimal("0.50")
        ))
        self.assertIsNone(random_repeat_adjustment_range(
            Decimal("-8.35"), Decimal("-7.35")
        ))

    def test_random_value_has_two_decimals_and_stays_inside_range(self):
        class FirstChoice:
            def randrange(self, count):
                return 0

        value = choose_repeat_adjustment(
            Decimal("-8.35"), Decimal("-8.59"), rng=FirstChoice()
        )
        self.assertEqual(value, Decimal("-9.59"))
        self.assertEqual(value.as_tuple().exponent, -2)

    def test_random_value_never_repeats_previous_value(self):
        class LastChoice:
            def randrange(self, count):
                return count - 1

        value = choose_repeat_adjustment(
            Decimal("-8.35"), Decimal("-8.59"), rng=LastChoice()
        )
        self.assertNotEqual(value, Decimal("-8.59"))
        self.assertGreaterEqual(value, Decimal("-9.59"))
        self.assertLessEqual(value, Decimal("-8.35"))


if __name__ == "__main__":
    unittest.main()
