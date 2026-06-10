from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class ValidationError(ValueError):
    pass


def _decimal(
    value: object,
    label: str,
    *,
    allow_zero: bool = False,
    absolute: bool = False,
    allow_negative: bool = False,
) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError(f"{label} 必須是數字。") from None
    if absolute:
        number = abs(number)
    if (number < 0 and not allow_negative) or (number == 0 and not allow_zero):
        raise ValidationError(f"{label} 必須大於零。")
    return number


@dataclass(frozen=True)
class SideValues:
    lot: Decimal
    sl_points: Decimal
    tp_points: Decimal


@dataclass(frozen=True)
class TradeInstruction:
    source_row: int
    status: str
    symbol: str
    sheet_direction: str
    internal: SideValues
    external: SideValues
    estimated_price: Decimal | None
    point_size: Decimal
    price_digits: int
    internal_entry_price: Decimal | None = None
    final_external_sl_price: Decimal | None = None
    final_external_tp_price: Decimal | None = None

    @property
    def internal_direction(self) -> str:
        return self.sheet_direction

    @property
    def external_direction(self) -> str:
        return "SELL" if self.sheet_direction == "BUY" else "BUY"

    @classmethod
    def from_mapping(cls, row_number: int, values: dict[str, object]) -> "TradeInstruction":
        raw_direction = str(values.get("direction", "")).strip()
        direction_aliases = {
            "BUY": "BUY",
            "LONG": "BUY",
            "多": "BUY",
            "做多": "BUY",
            "買": "BUY",
            "買入": "BUY",
            "SELL": "SELL",
            "SHORT": "SELL",
            "空": "SELL",
            "做空": "SELL",
            "賣": "SELL",
            "賣出": "SELL",
        }
        direction = direction_aliases.get(raw_direction.upper())
        if direction is None:
            raise ValidationError(
                "方向必須是 BUY／SELL、多／空，或做多／做空。"
            )
        symbol = str(values.get("symbol", "")).strip()
        if not symbol:
            raise ValidationError("商品代碼不可空白。")

        estimated_raw = str(values.get("estimated_price", "")).strip()
        entry_raw = str(values.get("internal_entry_price", "")).strip()
        final_sl_raw = str(values.get("final_external_sl_price", "")).strip()
        final_tp_raw = str(values.get("final_external_tp_price", "")).strip()
        point_size_raw = values.get("point_size", "0.0001")
        digits_raw = str(values.get("price_digits", "5")).strip() or "5"

        return cls(
            source_row=row_number,
            status=str(values.get("status", "")).strip(),
            symbol=symbol,
            sheet_direction=direction,
            internal=SideValues(
                _decimal(values.get("internal_lot"), "場內手數"),
                _decimal(
                    values.get("internal_sl_points"),
                    "場內止損點數",
                    allow_negative=True,
                ),
                _decimal(values.get("internal_tp_points"), "場內止盈點數"),
            ),
            external=SideValues(
                _decimal(values.get("external_lot"), "場外手數"),
                _decimal(
                    values.get("external_sl_points"),
                    "場外止損點數",
                    allow_negative=True,
                ),
                _decimal(values.get("external_tp_points"), "場外止盈點數"),
            ),
            estimated_price=_decimal(estimated_raw, "估算價格") if estimated_raw else None,
            point_size=_decimal(point_size_raw, "每點價格"),
            price_digits=int(digits_raw),
            internal_entry_price=_decimal(entry_raw, "Internal Entry Price") if entry_raw else None,
            final_external_sl_price=_decimal(final_sl_raw, "Final External SL price") if final_sl_raw else None,
            final_external_tp_price=_decimal(final_tp_raw, "Final External TP price") if final_tp_raw else None,
        )

    def estimated_prices(
        self,
        direction: str,
        side: SideValues,
        base_price: Decimal | None = None,
    ) -> tuple[Decimal, Decimal]:
        price = base_price if base_price is not None else self.estimated_price
        if price is None:
            raise ValidationError(
                "無法取得 MT5 目前價格，也沒有設定備用估算價格。"
            )
        # Sheet SL/TP values are price distances. cTrader converts them to
        # platform points separately; MT5 adds/subtracts them from Ask directly.
        sl_distance = abs(side.sl_points)
        tp_distance = side.tp_points
        if direction == "BUY":
            return price - sl_distance, price + tp_distance
        return price + sl_distance, price - tp_distance

    def format_price(self, value: Decimal) -> str:
        return f"{value:.{self.price_digits}f}"
