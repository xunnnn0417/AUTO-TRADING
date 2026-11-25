"""Desktop bar for the live hedge P/L (display only) - the chosen 「I1」 design.

  [場外] SL -$5.47                                        TP +$2.31
  [1,705.00] |▬▬▬▬▬▬▬▬▬▬▬▬|▬▬◆▬▬▬▬▬| [1,672.58]   (◆ = now, | at 0 and ends)
             進場 1,681.00     現價 1,677.60
                               -$3.53 估
  [場內] TP +$8.80                                          SL -$5.79
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

GAIN, LOSS = "#7fe0a8", "#ff8f8f"
FILL_GAIN, FILL_LOSS = "#4fb37f", "#d4677a"
TRACK_LOSS, TRACK_GAIN = "#3a2328", "#1f3a2c"
TICK, PRICE, MUTED, TAG_BG = "#d8d2e6", "#e7e2f0", "#8d879b", "#2b2735"
FONT = "Microsoft JhengHei UI"


def money(value: float) -> str:
    return f"{'+' if value > 0 else '-' if value < 0 else ''}${abs(value):,.2f}"


def price_text(value) -> str:
    return "—" if value is None else f"{value:,.2f}"


class LivePnlBar(QWidget):
    def __init__(self, parent=None, *, compact=False):
        super().__init__(parent)
        self.compact = compact
        self.state = None
        self.setMinimumHeight(128)
        self.setAccessibleName("目前持倉")

    def set_state(self, state) -> None:
        self.state = state
        self.update()

    # -- small drawing helpers ------------------------------------------------
    def _tag(self, p, x, y, text, size=8):
        font = QFont(FONT, size)
        p.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(text) + 10
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TAG_BG))
        p.drawRoundedRect(QRectF(x, y, width, 16 if size >= 8 else 14), 5, 5)
        p.setPen(QColor("#d8d2e6"))
        p.drawText(QRectF(x, y, width, 16 if size >= 8 else 14), Qt.AlignCenter, text)
        return width

    def _text(self, p, rect, text, color, *, size=9, bold=False, align=Qt.AlignLeft | Qt.AlignVCenter):
        p.setFont(QFont(FONT, size, QFont.DemiBold if bold else QFont.Normal))
        p.setPen(QColor(color))
        p.drawText(rect, align, text)

    def _price_box(self, p, x, y, text, *, right=False):
        font = QFont(FONT, 8)
        p.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(text) + 2
        rect = QRectF(x - width if right else x, y, width, 18)
        p.setPen(QColor(PRICE))  # plain text, no box
        p.drawText(rect, Qt.AlignCenter, text)
        return width

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        s = self.state
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not s:
            self._text(p, QRectF(self.rect()), "目前沒有持倉", MUTED, size=9, align=Qt.AlignCenter)
            p.end()
            return
        w = self.width()
        ext, inn = s["external"], s["internal"]
        est_ext = "  估" if s.get("estimated") == "external" else ""

        # Top row: [場外] SL ...  /  TP ...
        # When the bar is taller than needed the middle block is centred and
        # the four corners move a little toward it (not all the way).
        extra = max(0.0, (self.height() - 128) / 2)
        inset = extra * 0.85
        tag_w = self._tag(p, 0, inset, "場外")
        self._text(p, QRectF(tag_w + 5, inset, w / 2, 16), f"SL {money(ext['sl'])}", LOSS, bold=True)
        self._text(p, QRectF(w / 2, inset, w / 2, 16), f"TP {money(ext['tp'])}", GAIN, bold=True,
                   align=Qt.AlignRight | Qt.AlignVCenter)

        # Middle: price boxes at both ends, the track between them. When the
        # bar is taller than needed, the middle block sits centred between
        # the top row and the bottom corners.
        axis = 50 + extra
        left_w = self._price_box(p, 0, axis - 9, price_text(s.get("sl_price")))
        right_w = self._price_box(p, w, axis - 9, price_text(s.get("tp_price")), right=True)
        x0, x1 = left_w + 8, w - right_w - 8
        span = max(1.0, x1 - x0)
        zero = x0 + span * s["zero"]
        now = x0 + span * s["x"]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK_LOSS))
        p.drawRect(QRectF(x0, axis - 3, zero - x0, 6))
        p.setBrush(QColor(TRACK_GAIN))
        p.drawRect(QRectF(zero, axis - 3, x1 - zero, 6))
        gain = now >= zero
        p.setBrush(QColor(FILL_GAIN if gain else FILL_LOSS))
        p.drawRect(QRectF(min(zero, now), axis - 3, abs(now - zero), 6))
        # Ticks: both ends and the entry (0) - same height.
        p.setPen(QPen(QColor(TICK), 2, Qt.SolidLine, Qt.RoundCap))
        for x in (x0, x1, zero):
            p.drawLine(QPointF(x, axis - 7), QPointF(x, axis + 7))
        # Now: a small, narrow diamond.
        diamond = QPainterPath()
        diamond.moveTo(now, axis - 5)
        diamond.lineTo(now + 3, axis)
        diamond.lineTo(now, axis + 5)
        diamond.lineTo(now - 3, axis)
        diamond.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ece8f4"))
        p.drawPath(diamond)

        # 場外 P/L above the diamond.
        label_w = 120

        def centered(center, width=label_w):
            return max(0.0, min(w - width, center - width / 2))

        self._text(p, QRectF(centered(now), axis - 30, label_w, 16), money(ext["pnl"]) + est_ext,
                   GAIN if ext["pnl"] >= 0 else LOSS, bold=True, align=Qt.AlignCenter)

        # 進場 / 現價 on one row below; pushed apart when they would overlap.
        font = QFont(FONT, 8)
        metrics = QFontMetrics(font)
        entry_text = f"進場 {price_text(s.get('entry_price'))}"
        now_text = f"現價 {price_text(s.get('price'))}"
        entry_w = metrics.horizontalAdvance(entry_text) + 4
        now_w = metrics.horizontalAdvance(now_text) + 10  # bold number is wider
        entry_x, now_x = zero - entry_w / 2, now - now_w / 2
        if now >= zero and entry_x + entry_w + 6 > now_x:
            shift = (entry_x + entry_w + 6 - now_x) / 2
            entry_x, now_x = entry_x - shift, now_x + shift
        elif now < zero and now_x + now_w + 6 > entry_x:
            shift = (now_x + now_w + 6 - entry_x) / 2
            now_x, entry_x = now_x - shift, entry_x + shift
        entry_x = max(0.0, min(w - entry_w, entry_x))
        now_x = max(0.0, min(w - now_w, now_x))
        bold = QFont(FONT, 8, QFont.Bold)
        for x, label, value, width, strong in (
                (entry_x, "進場 ", price_text(s.get("entry_price")), entry_w, False),
                (now_x, "現價 ", price_text(s.get("price")), now_w, True)):
            p.setFont(font)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(x, axis + 9, width, 15), Qt.AlignLeft | Qt.AlignVCenter, label)
            # 現價: white and bold so it stands out from the other prices.
            p.setFont(bold if strong else font)
            p.setPen(QColor("#ffffff" if strong else PRICE))
            p.drawText(QRectF(x + metrics.horizontalAdvance(label), axis + 9, width + 12, 15),
                       Qt.AlignLeft | Qt.AlignVCenter, value)

        # 場內 P/L: small, under the diamond.
        self._text(p, QRectF(centered(now), axis + 24, label_w, 14), money(inn["pnl"]),
                   GAIN if inn["pnl"] >= 0 else LOSS, size=7, align=Qt.AlignCenter)

        # Bottom corners: [場內] TP ...  /  SL ...  (small)
        bottom = self.height() - 15 - inset
        tag_w = self._tag(p, 0, bottom, "場內", size=7)
        self._text(p, QRectF(tag_w + 4, bottom, w / 2, 14), f"TP {money(inn['tp'])}", GAIN, size=7)
        self._text(p, QRectF(w / 2, bottom, w / 2, 14), f"SL {money(inn['sl'])}", LOSS, size=7,
                   align=Qt.AlignRight | Qt.AlignVCenter)
        p.end()
