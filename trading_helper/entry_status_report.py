"""Build a truthful, read-only receipt for an attempted dual-Demo entry.

Never query brokers, send an order, or reinterpret a missing position as a
rejection. A journal confirms events observed at a point in time, not an
ongoing guarantee that the position remains open.
"""
from __future__ import annotations

import re


def summarize_interruption_reason(reason: str) -> str:
    """Keep action receipts short while retaining the useful order reference."""
    raw = str(reason or "").strip()
    if not raw:
        return ""
    if "cTrader" in raw and any(marker in raw for marker in (
        "持倉表資料列與原生列數不一致", "持倉讀取失敗", "欄沒有唯一原生讀值",
        "持倉表在讀取中更新",
    )):
        return "cTrader 持倉資料未讀完整，無法確認成交。請保持 Positions 清單展開並核對持倉，勿直接重複進場；完整原因見操作紀錄。"

    pending_match = re.search(
        r"MT5 唯讀 API 回報 (\d+) 筆仍有效委託[^\n]*", raw
    )
    if pending_match:
        order = re.search(r"(?:^|\n)\s*-\s*(.+)", raw)
        count = pending_match.group(1)
        message = [f"MT5 讀到 {count} 筆未完成訂單（不是持倉）。"]
        if order:
            detail = order.group(1).strip()
            simple_order = re.search(
                r"([^|]+)\|[^|]*(買入|賣出)[^|]*\|\s*單號\s*([^|]+)"
                r"\|\s*([\d.,]+)\s*手",
                detail,
            )
            if simple_order:
                symbol, side, ticket, volume = (
                    part.strip() for part in simple_order.groups()
                )
                message.append(
                    f"{symbol} {side} {volume} 手，單號 {ticket}。"
                )
            else:
                message.append(detail)
        message.append("請到 MT5「交易」核對單號；完整原因見操作記錄。")
        return "\n".join(message)

    reason_marker = "原因："
    if reason_marker in raw:
        raw = raw.split(reason_marker, 1)[1].strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    first = lines[0] if lines else raw
    if len(first) > 180:
        first = first[:177].rstrip() + "…"
    if len(lines) > 1 or len(raw) > len(first):
        return f"{first}\n詳細原因見操作記錄。"
    return first


def build_entry_status_report(
    entry: dict | None, *, success: bool, sync_requested: bool,
    tv_requested: bool, reason: str = "",
    internal_platform: str = "場內",
    external_platform: str = "場外",
) -> dict[str, object]:
    entry = entry if isinstance(entry, dict) else {}
    confirmed = entry.get("confirmed_legs", {})
    if not isinstance(confirmed, dict):
        confirmed = {}
    internal_ticket = str(confirmed.get("internal") or "").strip()
    external_ticket = str(confirmed.get("external") or "").strip()
    # Each leg is durably recorded as soon as its matching new position is
    # verified. A crash can occur after the second leg record but before the
    # combined ``confirmed_both`` milestone, so the two independent tickets
    # are also sufficient evidence that both entries were confirmed.
    both = bool(entry.get("confirmed_both")) or bool(
        internal_ticket and external_ticket
    )
    internal = success or both or bool(internal_ticket)
    external = success or both or bool(external_ticket)
    sync_verified = bool(entry.get("sl_tp_synchronized"))
    protected = bool(entry.get("internal_protected"))

    if success and internal and external:
        title = (
            "雙邊開倉及 SL／TP 同步完成"
            if sync_requested and sync_verified else "雙邊開倉已確認"
        )
    elif both and sync_requested and not protected:
        title = "雙邊開倉已確認，場內止盈止損尚未確認"
    elif both and sync_requested and not sync_verified:
        title = "雙邊開倉已確認，場外 SL／TP 同步未完成"
    elif both and tv_requested and not success:
        title = "雙邊開倉已確認，TradingView 繪圖未完成"
    elif both:
        title = "雙邊開倉已確認，後續處理未完成"
    elif internal or external:
        title = "開倉後續結果需要核對"
    else:
        title = "進場結果待確認"
    if "cTrader" in reason and any(marker in reason for marker in (
        "持倉表資料列與原生列數不一致", "持倉讀取失敗", "欄沒有唯一原生讀值",
        "持倉表在讀取中更新",
    )):
        title = "持倉讀取未完成，請核對兩邊"

    def side(label: str, platform: str, verified: bool) -> str:
        if (not verified and platform == "cTrader"
                and (f"{label}（cTrader）" in reason or f"{label} cTrader" in reason)
                and any(marker in reason for marker in ("持倉表", "持倉讀取", "原生讀值"))):
            return f"{label}（{platform}）：持倉讀取失敗，成交待核對"
        return f"{label}（{platform}）：{'已確認進場' if verified else '尚未確認進場'}"

    parts = [
        side("場內", internal_platform, internal),
        side("場外", external_platform, external),
    ]
    if sync_requested:
        parts.append(f"場內止盈止損：{'已核對' if protected else '未核對'}")
        parts.append(f"場外 SL／TP：{'已同步' if sync_verified else '未完成'}")

    if tv_requested:
        parts.append(f"TradingView：{'已完成' if success else '未完成'}")

    incident_role = (
        "internal" if internal and not external and not success
        else "external" if external and not internal and not success
        else None
    )
    # Only an actual rescue confirmation may be described as successful.
    rescued = str(entry.get("rescued_role", ""))
    if rescued in ("internal", "external"):
        parts.append(f"自動補進：{'場內' if rescued == 'internal' else '場外'}已確認")
    elif entry.get("rescue_attempted"):
        parts.append("自動補進：已嘗試，結果待核對；不會重試")
    elif incident_role:
        parts.append("未補進：還不能確認另一邊沒進場")
    if not success:
        parts.append("已停止，不會重送或自行平倉；請核對兩邊目前持倉。")
        if reason:
            parts.append("原因：" + summarize_interruption_reason(reason))
    return {
        "title": title, "message": "\n".join(parts), "success": success,
        "single_confirmed_role": incident_role,
        "internal_platform": internal_platform,
        "external_platform": external_platform,
    }
