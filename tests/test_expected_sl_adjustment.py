from decimal import Decimal
import unittest

from trading_helper.expected_sl_adjustment import (
    choose_repeat_adjustment, random_repeat_adjustment_range,
)


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
