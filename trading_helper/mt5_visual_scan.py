"""Read-only, low-confidence visual suggestions for a visible MT5 order dialog.

The custom-drawn bid/ask caption and submit buttons may have no UIA controls.
Nothing here moves the mouse, clicks, types, stores coordinates or reads accounts.
Every suggestion REQUIRES the existing yellow-outline preview and manual check.
"""
from __future__ import annotations

from PIL import Image


def _runs(row):
    import numpy as np
    indices = np.flatnonzero(row)
    if len(indices) == 0:
        return []
    gaps = np.flatnonzero(np.diff(indices) != 1) + 1
    groups = np.split(indices, gaps)
    return [(int(group[0]), int(group[-1]) + 1) for group in groups]


def detect_order_dialog_regions(image: Image.Image) -> dict[str, tuple[int,int,int,int]]:
    """Return relative rectangles for a unique red Sell / blue Buy quote pair.

    Bid and Ask candidates are located above their matching Sell and Buy
    controls. Empty output means visual identification failed. No price number
    is asserted or OCR'd here; each candidate remains a manual preview only.
    """
    import numpy as np
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    if pixels.ndim != 3:
        return {}
    h,w = pixels.shape[:2]
    if w < 430 or h < 320:
        return {}
    red,green,blue = pixels[:,:,0],pixels[:,:,1],pixels[:,:,2]
    sell = ((red > 155)&(green > 30)&(green < 165)&(blue < 165)&
            (red > green*1.55)&(red > blue*1.45))
    buy = ((blue > 155)&(green > 45)&
           (blue > red*1.5)&(blue > green*1.15))
    min_width = max(56, int(w*.12))
    max_width = int(w*.36)
    matches=[]
    for y in range(int(h*.36), min(int(h*.92),h)):
        reds = [(a,b) for a,b in _runs(sell[y])
                if min_width <= b-a <= max_width]
        blues = [(a,b) for a,b in _runs(buy[y])
                 if min_width <= b-a <= max_width]
        for a,b in reds:
            for c,e in blues:
                width_a,width_b=b-a,e-c
                gap=c-b
                if (a >= int(w*.08) and e <= int(w*.88)
                    and 4 <= gap <= max(48,int(w*.08))
                    and .78 <= width_a/width_b <= 1.25):
                    matches.append((y,a,b,c,e))
    if len(matches) < 8:
        return {}
    # Require a stable pair of same-sized bars across several scan lines,
    # not two thin market-chart curves with coincidental red/blue pixels.
    clusters={}
    for y,a,b,c,e in matches:
        key=(round(a/12), round(b/12), round(c/12),round(e/12))
        clusters.setdefault(key,[]).append((y,a,b,c,e))
    ordered=sorted(clusters.values(),key=len,reverse=True)
    if len(ordered[0]) < 8:
        return {}
    if len(ordered)>1 and len(ordered[1]) >= len(ordered[0])*.85:
        return {}
    group=sorted(ordered[0])
    ys=[row[0] for row in group]
    if len(set(ys)) < 8 or ys[-1]-ys[0] > 70:
        return {}
    row=group[len(group)//2]
    _,a,b,c,e=row
    # Color-run samples from rows where text does not interrupt the bar.
    y0=min(ys); y1=max(ys)+1
    bw=e-c
    # Keep each preview near the numerals over its matching order side.
    def quote_rect(
        left: int, right: int, start: float, end: float,
    ) -> tuple[int,int,int,int]:
        width = right - left
        return (
            max(0,round(left+width*start)),
            max(0,round(y0-width*.50)),
            min(w,round(left+width*end)),
            min(h,round(y0-width*.30)),
        )

    # MT5 centers the two large quote numbers around the slash between them:
    # Bid sits toward the right edge of the Sell button; Ask starts near the
    # left edge of the Buy button. Symmetric rectangles clipped the Bid tail.
    bid_quote = quote_rect(a, b, .25, 1.00)
    ask_quote = quote_rect(c, e, .00, .70)
    for quote in (bid_quote, ask_quote):
        if quote[2]-quote[0] < 55 or quote[3]-quote[1] < 25:
            return {}
        text_region=pixels[quote[1]:quote[3],quote[0]:quote[2]]
        # Both sides must visibly contain white quote digits. Otherwise do
        # not infer either price location from button colors alone.
        white=(text_region.min(axis=2)>185)
        if int(white.sum()) < 45:
            return {}
    # Yellow calibration outlines should surround the FULL clickable
    # colored bars, not float inside/above them. All rects are still only
    # preview candidates, never click commands.
    sell_rect=(max(0,a-2),max(0,y0-2),min(w,b+2),min(h,y1+2))
    buy_rect=(max(0,c-2),max(0,y0-2),min(w,e+2),min(h,y1+2))
    if any(v2<=v1 for (v1,v2) in (
        (sell_rect[0],sell_rect[2]),(buy_rect[0],buy_rect[2]),
        (sell_rect[1],sell_rect[3]))):
        return {}
    return {
        "order_submit_sell":sell_rect,
        "order_submit_buy":buy_rect,
        "bid_price_left":bid_quote,
        "ask_price_right":ask_quote,
    }
