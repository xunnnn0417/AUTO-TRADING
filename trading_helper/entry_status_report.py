"""Build a truthful, read-only receipt for an attempted dual-Demo entry.

Never query brokers, send an order, or reinterpret a missing position as a
rejection. A journal confirms events observed at a point in time, not an
ongoing guarantee that the position remains open.
"""
from __future__ import annotations


def build_entry_status_report(
    entry: dict | None, *, success: bool, sync_requested: bool,
    tv_requested: bool, reason: str = "",
    internal_platform: str = "場內",
    external_platform: str = "場外",
) -> dict[str, str]:
    entry = entry if isinstance(entry, dict) else {}
    confirmed = entry.get("confirmed_legs", {})
    if not isinstance(confirmed, dict):
        confirmed = {}
    both = bool(entry.get("confirmed_both"))
    internal = success or both or bool(confirmed.get("internal"))
    external = success or both or bool(confirmed.get("external"))
    sync_verified = bool(entry.get("sl_tp_synchronized"))
    protected = bool(entry.get("internal_protected"))

    if success and internal and external:
        title = (
            "雙邊開倉及 SL／TP 同步完成"
            if sync_requested and sync_verified else "雙邊開倉已確認"
        )
    elif internal or external:
        title = "開倉後續結果需要核對"
    else:
        title = "開倉未完成／結果待確認"

    def side(label: str, platform: str, verified: bool) -> str:
        return f"{label}（{platform}）：{'已有成交確認紀錄' if verified else '尚未證實成交'}"

    parts = [
        side("場內", internal_platform, internal),
        side("場外", external_platform, external),
    ]
    if sync_requested:
        parts.append(
            "場內止盈止損：" +
            ("已核對" if protected else "尚未證實已核對")
        )
        parts.append(
            "場外止盈止損同步：" +
            ("修改並讀回核對成功" if sync_verified else "未證實完成")
        )
    else:
        parts.append("場外 SL／TP 同步：本次沒有啟用")

    if tv_requested:
        parts.append(
            "TradingView 繪圖：" +
            ("流程已完成" if success else "尚未證實完成")
        )
    else:
        parts.append("TradingView 繪圖：本次沒有啟用")

    # Never imply a rescue order exists just because one side is missing.
    parts.append("自動補開：未執行（目前尚未啟用）")
    if not success:
        parts.append("後續：已停止自動送單，請核對兩側持倉及掛單。")
        if reason:
            parts.append("原因：" + str(reason)[:600])
    else:
        parts.append("提醒：此為開倉當下驗證，不代表兩側日後一定同步平倉。")
    return {"title": title, "message": "\n".join(parts), "success": success}