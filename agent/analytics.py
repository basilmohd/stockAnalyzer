"""Performance analytics — turns the closed Trade ledger into edge statistics.

Three layers:
  • compute_performance_stats(): the full stats engine — win rate, expectancy,
    per-strategy and per-exit-reason breakdowns, weekly P&L, open-position
    mark-to-market — computed entirely from journal reads.
  • format_weekly_report() / send_weekly_report(): the Sunday 9 AM Telegram report,
    with paper-mode watermark and a data-driven go/no-go nudge.
  • get_best_strategy() / should_go_live(): comparison + readiness helpers the
    signal pipeline and the human use to decide paper → live.

Convention: every ratio is a FRACTION (0.0–1.0), matching Trade.pnl_pct as stored —
win_rate, avg_win_pct, avg_loss_pct, expectancy, avg_pnl_pct, total_return_pct, and the
best/worst trade pnl_pct. Telegram formatting renders them with percent format
specifiers (e.g. 0.024 → "+2.40%").
"""
from datetime import date, datetime, timedelta

import config
from agent.journal import get_closed_trades, get_open_trades
from core.logger import get_logger
from core.redis_client import RedisClient

logger = get_logger(__name__)
_redis = RedisClient(config.REDIS_URL)

# Strategies we report on, in display order.
_STRATEGIES = ["SWING_TRADE", "MEAN_REVERSION", "TREND_FOLLOW"]
# Exit reasons we always surface (zero-filled when none occurred).
_EXIT_REASONS = ["TARGET", "STOPLOSS", "TIME_STOP", "MANUAL"]


# ── small numeric helpers ──────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    """Arithmetic mean, or 0.0 for an empty list."""
    return sum(values) / len(values) if values else 0.0


def _iso_week_label(d: date) -> str:
    """Return the ISO week label for *d*, e.g. '2025-W22'."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _hold_days(trade) -> int:
    """Calendar days a trade was held (exit_date − entry_date). 0 if dates missing."""
    if trade.entry_date is None or trade.exit_date is None:
        return 0
    return (trade.exit_date.date() - trade.entry_date.date()).days


# ── live price for open-position mark-to-market ─────────────────────────────────

def _cached_price(symbol: str) -> float | None:
    """Latest cached price for *symbol* from Redis key 'quote:{symbol}'.

    The cache may hold a bare number or a JSON quote blob with a 'last_price'
    field; both are handled. Returns None when nothing usable is cached.
    """
    raw = _redis.get(f"quote:{symbol}")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        import json
        data = json.loads(raw)
        lp = data.get("last_price") if isinstance(data, dict) else None
        return float(lp) if lp else None
    except Exception:
        return None


def _open_positions_block() -> dict:
    """Mark-to-market the open book using cached prices (fallback: entry price).

    Returns a dict with count, unrealized_pnl (total), and a per-position list
    (symbol, entry, current, quantity, unrealized, unrealized_pct).
    """
    open_trades = get_open_trades()
    positions: list[dict] = []
    unrealized_total = 0.0

    for t in open_trades:
        current = _cached_price(t.symbol)
        if current is None:
            current = t.entry_price
        unrealized = (current - t.entry_price) * t.quantity
        unrealized_pct = (
            (current - t.entry_price) / t.entry_price if t.entry_price else 0.0
        )
        unrealized_total += unrealized
        positions.append({
            "symbol": t.symbol,
            "entry": round(t.entry_price, 2),
            "current": round(current, 2),
            "quantity": t.quantity,
            "unrealized": round(unrealized, 2),
            "unrealized_pct": round(unrealized_pct, 4),
        })

    return {
        "count": len(open_trades),
        "unrealized_pnl": round(unrealized_total, 2),
        "positions": positions,
    }


# ── stats engine ────────────────────────────────────────────────────────────────

def _empty_stats(since: date | None) -> dict:
    """Zeroed stats dict for the no-closed-trades case (open book still valued)."""
    open_block = _open_positions_block()
    unrealized = open_block["unrealized_pnl"]
    starting = config.TOTAL_CAPITAL
    current_value = round(starting + unrealized, 2)
    return {
        "generated_at": datetime.now().isoformat(),
        "period": "all_time" if since is None else since.isoformat(),
        "is_paper": config.PAPER_TRADE_MODE,
        "summary": {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "expectancy": 0.0,
            "total_pnl": 0.0,
            "avg_hold_days": 0.0,
            "best_trade": None,
            "worst_trade": None,
        },
        "by_strategy": {s: _empty_strategy() for s in _STRATEGIES},
        "by_exit_reason": {r: {"count": 0, "total_pnl": 0.0} for r in _EXIT_REASONS},
        "weekly_pnl": [],
        "open_positions": open_block,
        "capital": {
            "starting": starting,
            "current_value": current_value,
            "total_return_pct": round((unrealized / starting) if starting else 0.0, 4),
        },
    }


def _empty_strategy() -> dict:
    """Zeroed per-strategy stats block."""
    return {
        "trades": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "avg_pnl_pct": 0.0,
        "avg_hold_days": 0.0,
    }


def _trade_brief(trade) -> dict:
    """Compact {symbol, pnl, pnl_pct, strategy, exit_reason} for best/worst trade."""
    return {
        "symbol": trade.symbol,
        "pnl": round(trade.pnl or 0.0, 2),
        "pnl_pct": round(trade.pnl_pct or 0.0, 4),
        "strategy": trade.strategy_type,
        "exit_reason": trade.exit_reason,
    }


def _strategy_stats(trades: list) -> dict:
    """Per-strategy block (count, win_rate, total_pnl, avg_pnl_pct, avg_hold_days)."""
    if not trades:
        return _empty_strategy()
    wins = [t for t in trades if (t.pnl or 0.0) > 0]
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4),
        "total_pnl": round(sum(t.pnl or 0.0 for t in trades), 2),
        "avg_pnl_pct": round(_mean([t.pnl_pct or 0.0 for t in trades]), 4),
        "avg_hold_days": round(_mean([_hold_days(t) for t in trades]), 1),
    }


def _weekly_pnl(closed: list, limit: int = 8) -> list[dict]:
    """Group closed trades by ISO week → [{week, pnl, trades}], newest first, last *limit*."""
    buckets: dict[str, dict] = {}
    for t in closed:
        if t.exit_date is None:
            continue
        label = _iso_week_label(t.exit_date.date())
        bucket = buckets.setdefault(label, {"week": label, "pnl": 0.0, "trades": 0})
        bucket["pnl"] += t.pnl or 0.0
        bucket["trades"] += 1
    ordered = sorted(buckets.values(), key=lambda b: b["week"], reverse=True)
    for b in ordered:
        b["pnl"] = round(b["pnl"], 2)
    return ordered[:limit]


def compute_performance_stats(since: date | None = None) -> dict:
    """Compute full performance statistics from the closed Trade ledger.

    Args:
        since: if given, only trades exited on/after this date are counted; open
            positions are always valued at the current cached price regardless.

    Returns:
        A nested dict (summary, by_strategy, by_exit_reason, weekly_pnl,
        open_positions, capital). With no closed trades, a zeroed dict that still
        reflects the open book and capital.
    """
    closed = get_closed_trades(since)
    if not closed:
        return _empty_stats(since)

    total_trades = len(closed)
    winning = [t for t in closed if (t.pnl or 0.0) > 0]
    losing = [t for t in closed if (t.pnl or 0.0) <= 0]

    win_rate = len(winning) / total_trades
    avg_win_pct = _mean([t.pnl_pct or 0.0 for t in winning])
    avg_loss_pct = _mean([t.pnl_pct or 0.0 for t in losing])
    total_pnl = sum(t.pnl or 0.0 for t in closed)
    expectancy = (win_rate * avg_win_pct) + ((1 - win_rate) * avg_loss_pct)

    best = max(closed, key=lambda t: t.pnl or 0.0)
    worst = min(closed, key=lambda t: t.pnl or 0.0)
    avg_hold_days = _mean([_hold_days(t) for t in closed])

    by_strategy = {
        s: _strategy_stats([t for t in closed if t.strategy_type == s])
        for s in _STRATEGIES
    }

    by_exit_reason = {r: {"count": 0, "total_pnl": 0.0} for r in _EXIT_REASONS}
    for t in closed:
        reason = t.exit_reason or "MANUAL"
        bucket = by_exit_reason.setdefault(reason, {"count": 0, "total_pnl": 0.0})
        bucket["count"] += 1
        bucket["total_pnl"] += t.pnl or 0.0
    for bucket in by_exit_reason.values():
        bucket["total_pnl"] = round(bucket["total_pnl"], 2)

    weekly_pnl = _weekly_pnl(closed)
    open_block = _open_positions_block()
    unrealized = open_block["unrealized_pnl"]

    starting = config.TOTAL_CAPITAL
    current_value = round(starting + total_pnl + unrealized, 2)
    total_return_pct = (
        (total_pnl + unrealized) / starting if starting else 0.0
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "period": "all_time" if since is None else since.isoformat(),
        "is_paper": config.PAPER_TRADE_MODE,
        "summary": {
            "total_trades": total_trades,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win_pct, 4),
            "avg_loss_pct": round(avg_loss_pct, 4),
            "expectancy": round(expectancy, 4),
            "total_pnl": round(total_pnl, 2),
            "avg_hold_days": round(avg_hold_days, 1),
            "best_trade": _trade_brief(best),
            "worst_trade": _trade_brief(worst),
        },
        "by_strategy": by_strategy,
        "by_exit_reason": by_exit_reason,
        "weekly_pnl": weekly_pnl,
        "open_positions": open_block,
        "capital": {
            "starting": starting,
            "current_value": current_value,
            "total_return_pct": round(total_return_pct, 4),
        },
    }


# ── Telegram weekly report ──────────────────────────────────────────────────────

def _current_week_range() -> str:
    """Return 'dd Mon – dd Mon' for the current Mon–Sun ISO week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b')}"


def _this_week_figures(stats: dict) -> tuple[float, int]:
    """Return (pnl, trades) for the current ISO week from weekly_pnl, else (0, 0)."""
    label = _iso_week_label(date.today())
    for entry in stats.get("weekly_pnl", []):
        if entry["week"] == label:
            return entry["pnl"], entry["trades"]
    return 0.0, 0


def _display_best_strategy(by_strategy: dict) -> tuple[str, dict] | None:
    """Pick the strategy with the highest total_pnl among those with trades. None if none."""
    traded = {k: v for k, v in by_strategy.items() if v["trades"] > 0}
    if not traded:
        return None
    name = max(traded, key=lambda k: traded[k]["total_pnl"])
    return name, traded[name]


def format_weekly_report(stats: dict) -> str:
    """Format performance stats into a rich HTML Telegram weekly report.

    Adds a paper-mode watermark, and a go/no-go nudge based on expectancy and
    sample size. Returns a short placeholder message when no trades have closed.
    """
    summary = stats["summary"]
    is_paper = stats.get("is_paper", True)
    paper_tag = " | ⚠️ PAPER" if is_paper else ""

    if summary["total_trades"] == 0:
        msg = "📊 <b>Weekly Performance Report</b>\n\nNo closed trades yet — paper trading active"
        if is_paper:
            msg += "\n\n⚠️ <i>All figures are paper trades — not real money</i>"
        return msg

    capital = stats["capital"]
    week_pnl, week_trades = _this_week_figures(stats)

    lines = [
        f"📊 <b>Weekly Performance Report</b>",
        f"{_current_week_range()}{paper_tag}",
        "",
        f"💰 <b>This Week</b>",
        f"P&amp;L: {week_pnl:+.0f} | Trades: {week_trades}",
        "",
        f"📈 <b>All Time Summary</b>",
        f"Total Trades: {summary['total_trades']}",
        f"Win Rate: {summary['win_rate']:.0%} ({summary['winning_trades']}/{summary['total_trades']})",
        f"Expectancy: {summary['expectancy']:+.2%} per trade",
        f"Total P&amp;L: ₹{summary['total_pnl']:+.0f}",
        f"Capital: ₹{capital['current_value']:,.0f} ({capital['total_return_pct']:+.1%})",
    ]

    best_strat = _display_best_strategy(stats["by_strategy"])
    if best_strat:
        name, s = best_strat
        lines += [
            "",
            f"🏆 <b>Best Strategy</b>",
            f"{name}: {s['win_rate']:.0%} win rate, ₹{s['total_pnl']:.0f} P&amp;L over {s['trades']} trades",
        ]

    exits = stats["by_exit_reason"]
    lines += [
        "",
        f"🎯 <b>Exit Breakdown</b>",
        (
            f"Targets hit: {exits.get('TARGET', {}).get('count', 0)} | "
            f"SL hit: {exits.get('STOPLOSS', {}).get('count', 0)} | "
            f"Time stop: {exits.get('TIME_STOP', {}).get('count', 0)}"
        ),
    ]

    open_block = stats["open_positions"]
    lines += [
        "",
        f"📌 <b>Open Positions ({open_block['count']})</b>",
        f"Unrealized: ₹{open_block['unrealized_pnl']:+.0f}",
    ]
    for p in open_block.get("positions", []):
        lines.append(
            f"• {p['symbol']}: ₹{p['entry']:.0f} → ₹{p['current']:.0f} ({p['unrealized_pct']:+.1%})"
        )

    best = summary["best_trade"]
    worst = summary["worst_trade"]
    if best:
        lines += ["", f"Best trade: {best['symbol']} {best['pnl_pct']:+.1%}"]
    if worst:
        lines.append(f"Worst trade: {worst['symbol']} {worst['pnl_pct']:+.1%}")

    expectancy = summary["expectancy"]
    win_rate = summary["win_rate"]
    total_trades = summary["total_trades"]
    if expectancy <= 0:
        lines += ["", "⚠️ <i>Negative expectancy — system not profitable yet. Do not go live.</i>"]
    elif win_rate > 0.55 and total_trades >= 10:
        lines += ["", "✅ <i>System showing positive edge. Review before going live.</i>"]

    if is_paper:
        lines += ["", "⚠️ <i>All figures are paper trades — not real money</i>"]

    return "\n".join(lines)


async def send_weekly_report() -> None:
    """Compute stats, format, send to Telegram, and cache the raw stats in Redis.

    Cached under 'analytics:latest' (7-day TTL) so the dashboard endpoint can serve
    the last computed snapshot without recomputing.
    """
    import json

    from core.telegram_bot import send_message

    stats = compute_performance_stats()
    text = format_weekly_report(stats)
    await send_message(text, parse_mode="HTML")

    _redis.setex("analytics:latest", 7 * 24 * 3600, json.dumps(stats))
    logger.info(
        "Weekly report sent: %d trades, win_rate=%.0f%%, expectancy=%+.2f%%",
        stats["summary"]["total_trades"],
        stats["summary"]["win_rate"] * 100,
        stats["summary"]["expectancy"] * 100,
    )


# ── strategy comparison + live-readiness ────────────────────────────────────────

def get_best_strategy() -> str | None:
    """Return the strategy with the highest expectancy, or None if data is thin.

    Requires at least 3 closed trades for a strategy before it is ranked. Expectancy
    is win_rate × avg_win + loss_rate × avg_loss, computed per strategy from its own
    closed trades. Used by the signal pipeline to bias confidence thresholds.
    """
    closed = get_closed_trades()
    if not closed:
        return None

    best_name: str | None = None
    best_expectancy = float("-inf")
    for strategy in _STRATEGIES:
        trades = [t for t in closed if t.strategy_type == strategy]
        if len(trades) < 3:
            continue
        wins = [t for t in trades if (t.pnl or 0.0) > 0]
        losses = [t for t in trades if (t.pnl or 0.0) <= 0]
        win_rate = len(wins) / len(trades)
        avg_win = _mean([t.pnl_pct or 0.0 for t in wins])
        avg_loss = _mean([t.pnl_pct or 0.0 for t in losses])
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        if expectancy > best_expectancy:
            best_expectancy = expectancy
            best_name = strategy

    return best_name


def should_go_live() -> dict:
    """Data-driven go/no-go for switching paper → live.

    Checks five conditions: ≥20 trades, win rate ≥55%, positive expectancy,
    ≥4 weeks traded, and no single week worse than −10% of starting capital.

    Returns:
        dict with ready (bool), per-condition flags, the list of missing
        conditions, and a human-readable message.
    """
    stats = compute_performance_stats()
    summary = stats["summary"]
    weekly = stats["weekly_pnl"]
    starting = config.TOTAL_CAPITAL or 1.0

    worst_week = min((w["pnl"] for w in weekly), default=0.0)
    max_drawdown = abs(min(0.0, worst_week)) / starting

    conditions = {
        "enough_trades": summary["total_trades"] >= 20,
        "win_rate_ok": summary["win_rate"] >= 0.55,
        "positive_expectancy": summary["expectancy"] > 0,
        "enough_weeks": len(weekly) >= 4,
        "drawdown_ok": max_drawdown < 0.10,
    }
    missing = [name for name, ok in conditions.items() if not ok]
    met = len(conditions) - len(missing)
    ready = not missing

    if ready:
        message = "All 5 conditions met. System is ready for live trading review."
    else:
        message = f"{met}/5 conditions met. Keep paper trading — missing: {', '.join(missing)}."

    return {
        "ready": ready,
        "conditions": conditions,
        "missing": missing,
        "message": message,
    }
