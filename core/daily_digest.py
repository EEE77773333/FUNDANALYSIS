"""
每日简报
========
汇总持仓/监控/未读预警/AI 用量，可通过通知通道推送。
默认偏「盘后」：北京时间 15:05 后才自动推送；手动发送不受限。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from .user_workspace import get_prefs, save_prefs, workbench_snapshot


_CN_TZ = timezone(timedelta(hours=8))


def _now_cn() -> datetime:
    return datetime.now(_CN_TZ)


def _today_cn() -> str:
    return _now_cn().strftime("%Y-%m-%d")


def is_after_market_close(minute_offset: int = 5) -> bool:
    """A 股收盘 15:00 后再过 minute_offset 分钟视为盘后。"""
    n = _now_cn()
    return (n.hour > 15) or (n.hour == 15 and n.minute >= minute_offset)


def build_digest_text(display_name: str = "") -> Tuple[str, str]:
    """返回 (title, markdown_body)。"""
    snap = workbench_snapshot()
    usage = snap.get("usage") or {}
    used = usage.get("api_calls_today", 0)
    limit = usage.get("api_calls_limit", 0)
    name = display_name or "用户"
    today = _today_cn()
    title = f"📬 基金分析日报 · {today}"
    lines = [
        f"**{name}** 的盘后摘要（北京时间 {_now_cn().strftime('%H:%M')}）",
        "",
        f"- 组合数：{snap.get('portfolio_count', 0)}（持仓 {snap.get('holding_count', 0)} 只）",
        f"- 监控列表：{snap.get('watch_count', 0)} 只",
        f"- 今日预警：{snap.get('today_alerts', 0)} 条（未确认 {snap.get('unack_alerts', 0)}）",
        f"- AI 用量：{used}/{limit}",
        f"- 分析历史：{snap.get('history_count', 0)} 条",
        "",
    ]

    # 未确认预警明细（最多 5 条，合并组）
    try:
        from .alert_engine import get_alert_engine
        groups = get_alert_engine().get_triggers_grouped(
            acknowledged=False, today_only=True, limit=5
        )
        if groups:
            lines.append("**今日待处理预警**")
            for g in groups:
                cnt = f" ×{g['count']}" if g["count"] > 1 else ""
                lines.append(f"- [{g['fund_code']}]{cnt} {g['message'][:80]}")
            lines.append("")
    except Exception:
        pass

    favs = snap.get("favorites") or []
    if favs:
        lines.append("**收藏**")
        for f in favs[:5]:
            lines.append(f"- {f.get('fund_code')} {f.get('fund_name') or ''}".rstrip())
        lines.append("")

    recent = snap.get("recent_funds") or []
    if recent:
        lines.append("**最近查看**")
        for r in recent[:5]:
            lines.append(f"- {r.get('ref_key')} {r.get('title') or ''}".rstrip())
        lines.append("")

    if snap.get("unack_alerts", 0):
        lines.append("⚠️ 有未确认预警，请打开「预警规则 → 触发历史」处理。")
    else:
        lines.append("✅ 暂无待处理预警。")
    lines.append("")
    lines.append("_本简报由基金智能分析系统自动生成，仅供参考。_")
    return title, "\n".join(lines)


def send_digest(display_name: str = "", force: bool = False) -> dict:
    """
    推送每日简报。
    Returns: {ok, skipped, reason, channels}
    """
    prefs = get_prefs().get("prefs") or {}
    today = _today_cn()
    last = prefs.get("digest_last_sent")
    if not force and last == today:
        return {"ok": False, "skipped": True, "reason": "今日已发送", "channels": 0}

    if not force and not is_after_market_close():
        return {"ok": False, "skipped": True, "reason": "未到盘后（15:05 后自动推送）", "channels": 0}

    title, body = build_digest_text(display_name)
    try:
        from .notifications import get_notification_manager
        nm = get_notification_manager()
        channels = nm.get_channels() or {}
        enabled = [n for n, cfg in channels.items() if cfg.get("enabled", True)]
        if not enabled:
            return {"ok": False, "skipped": True, "reason": "未配置通知通道", "channels": 0}
        result = nm.broadcast(title, body)
        sent = sum(1 for v in (result or {}).values() if v)
        save_prefs(prefs_patch={"digest_last_sent": today})
        return {"ok": bool(sent), "skipped": False, "reason": "" if sent else "推送失败", "channels": sent}
    except Exception as e:
        return {"ok": False, "skipped": False, "reason": str(e)[:120], "channels": 0}


def maybe_auto_digest(display_name: str = "") -> Optional[dict]:
    """登录后首页调用：盘后 + 未发送 + 已配置通道时自动推送。"""
    prefs = get_prefs().get("prefs") or {}
    if not prefs.get("digest_auto", True):
        return None
    return send_digest(display_name=display_name, force=False)
