"""Safe point-range calculations for repeated expected stop distances."""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import random


CENT = Decimal("0.01")
ONE = Decimal("1")


def random_repeat_adjustment_range(
    original: Decimal | None,
    previous: Decimal | None,
) -> tuple[Decimal, Decimal] | None:
    """Return the cent-aligned bounds requested for a repeated stop value.

    The previous expected stop value is reduced by one full point. Mixed
    signs, zero, crossing zero, invalid/non-finite values, or a range without
    a new two-decimal choice are declined instead of inventing a risky value.
    """
    if original is None or previous is None:
        return None
    if not original.is_finite() or not previous.is_finite():
        return None
    if original == 0 or previous == 0:
        return None
    if (original < 0) != (previous < 0):
        return None

    adjusted_previous = previous - ONE
    if adjusted_previous == 0 or (adjusted_previous < 0) != (previous < 0):
        return None

    low, high = sorted((original, adjusted_previous))
    low_cent = int((low / CENT).to_integral_value(rounding=ROUND_CEILING))
    high_cent = int((high / CENT).to_integral_value(rounding=ROUND_FLOOR))
    if high_cent - low_cent < 1:
        return None

    # Do not offer a random choice identical to the prior value.
    previous_cent = previous.quantize(CENT)
    candidate_count = high_cent - low_cent + 1
    if low_cent <= int(previous_cent / CENT) <= high_cent:
        candidate_count -= 1
    if candidate_count <= 0:
        return None

    return Decimal(low_cent) * CENT, Decimal(high_cent) * CENT


def choose_repeat_adjustment(
    original: Decimal | None,
    previous: Decimal | None,
    *,
    rng=None,
) -> Decimal | None:
    """Choose a uniform two-decimal point value, excluding the prior value."""
    bounds = random_repeat_adjustment_range(original, previous)
    if bounds is None:
        return None
    low_cent = int(bounds[0] / CENT)
    high_cent = int(bounds[1] / CENT)
    previous_cent = previous.quantize(CENT)
    excluded = (
        int(previous_cent / CENT)
        if bounds[0] <= previous_cent <= bounds[1]
        else None
    )
    count = high_cent - low_cent + 1 - (excluded is not None)
    if count <= 0:
        return None
    chooser = rng or random.SystemRandom()
    slot = chooser.randrange(count)
    if excluded is not None and low_cent + slot >= excluded:
        slot += 1
    return Decimal(low_cent + slot) * CENT


WIDEN = Decimal("1.5")


def widened_sl_range(original: Decimal | None) -> tuple[Decimal, Decimal] | None:
    """The 預期止損 warning's suggestion range: from the original stop to
    1.5 points farther (e.g. -6.70 -> -8.20 ~ -6.70), cent-aligned."""
    if original is None or not original.is_finite() or original == 0:
        return None
    far = original - WIDEN  # 「原始 SL 再 -1.5」, same direction as the repeat rule
    if far == 0 or (far < 0) != (original < 0):
        return None
    low, high = sorted((original, far))
    low_cent = int((low / CENT).to_integral_value(rounding=ROUND_CEILING))
    high_cent = int((high / CENT).to_integral_value(rounding=ROUND_FLOOR))
    if high_cent - low_cent < 1:
        return None
    return Decimal(low_cent) * CENT, Decimal(high_cent) * CENT


def choose_widened_sl(original: Decimal | None, *, rng=None) -> Decimal | None:
    """A uniform two-decimal value in widened_sl_range()."""
    bounds = widened_sl_range(original)
    if bounds is None:
        return None
    low_cent, high_cent = int(bounds[0] / CENT), int(bounds[1] / CENT)
    chooser = rng or random.SystemRandom()
    return Decimal(low_cent + chooser.randrange(high_cent - low_cent + 1)) * CENT
