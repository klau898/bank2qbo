#!/usr/bin/env python3
"""Bank2QBO 9am ET daily digest — concierge state snapshot to Telegram.

Reads concierge.db, computes:
- Day number within Cycle 1 (2026-05-15 + N days)
- Day-14 mini-checkpoint status (vs 14-day kill rule)
- Day-90 cycle gate progress (vs $1,500 SCALE threshold)
- Today's: leads, conversions, PDFs processed, deliveries sent, avg reconciliation
- Cumulative: leads, conversions ($ total), avg reconciliation across cycle
- Codex verdict suggestion (continue | extend | kill | repair-execution)

Format mirrors README §"Daily 09:00 ET Telegram digest" block.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "state" / "concierge.db"

# Auto-load .env if present (launchd doesn't source shell rc)
_env = REPO / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip(); _v = _v.strip().strip('"').strip("'")
            if _k and _v and _k not in os.environ:
                os.environ[_k] = _v

# Cycle 1 anchors (from ARCHETYPE_CYCLE_1_2026-05-15.md §7)
CYCLE_START = date(2026, 5, 15)
CYCLE_END = date(2026, 8, 13)
DAY14_CHECKPOINT = CYCLE_START + timedelta(days=14)
SCALE_REVENUE_CENTS = 150_000  # $1,500 collected revenue
SCALE_MRR_CENTS = 50_000        # $500 MRR
EXTEND_FLOOR_CENTS = 75_000     # $750 collected revenue (below this = KILL at Day 90)
DISTRIBUTION_TARGET = 900
DISTRIBUTION_FLOOR_PCT = 0.80


def _day_number() -> int:
    return max(1, (date.today() - CYCLE_START).days + 1)


def _q(con: sqlite3.Connection, sql: str, params=()) -> list[tuple]:
    return con.execute(sql, params).fetchall()


def _scalar(con: sqlite3.Connection, sql: str, params=(), default=0):
    row = con.execute(sql, params).fetchone()
    return (row[0] if row and row[0] is not None else default)


def gather_state() -> dict:
    today = date.today()
    today_iso = today.isoformat()
    con = sqlite3.connect(DB_PATH)
    try:
        leads_today = _scalar(con, "SELECT COUNT(*) FROM leads WHERE date(created_at) = ?", (today_iso,))
        leads_total = _scalar(con, "SELECT COUNT(*) FROM leads")
        conv_today = _scalar(con, "SELECT COUNT(*) FROM conversions WHERE date(created_at) = ?", (today_iso,))
        conv_total = _scalar(con, "SELECT COUNT(*) FROM conversions")
        rev_total_cents = _scalar(con, "SELECT COALESCE(SUM(amount_cents),0) FROM conversions")
        pdfs_today = _scalar(con, "SELECT COUNT(*) FROM pdfs WHERE date(created_at) = ?", (today_iso,))
        deliv_today = _scalar(con, "SELECT COUNT(*) FROM deliveries WHERE date(delivered_at) = ?", (today_iso,))
        deliv_total = _scalar(con, "SELECT COUNT(*) FROM deliveries WHERE delivered_at IS NOT NULL")
        avg_score = _scalar(
            con,
            "SELECT AVG(reconciliation_score) FROM deliveries WHERE delivered_at IS NOT NULL",
            default=None,
        )
    finally:
        con.close()

    return {
        "day_number": _day_number(),
        "today": today_iso,
        "day14_checkpoint": DAY14_CHECKPOINT.isoformat(),
        "cycle_end": CYCLE_END.isoformat(),
        "leads_today": leads_today,
        "leads_total": leads_total,
        "conv_today": conv_today,
        "conv_total": conv_total,
        "rev_total_cents": rev_total_cents,
        "pdfs_today": pdfs_today,
        "deliv_today": deliv_today,
        "deliv_total": deliv_total,
        "avg_reconciliation_score": avg_score,
    }


def derive_verdict(state: dict) -> tuple[str, str]:
    """Returns (verdict, rationale)."""
    day = state["day_number"]
    rev = state["rev_total_cents"]
    conv = state["conv_total"]

    if day <= 14:
        if conv >= 3:
            return "continue-strong", f"Day {day} ≥3 paid; concierge-validation passed early."
        if conv >= 1:
            return "continue", f"Day {day} {conv} paid + leads building; standard."
        if day == 14 and conv == 0:
            return "checkpoint-warning", f"Day 14 / 0 paid — flag for Codex consult; do NOT kill (90-day binding outer)."
        return "continue", f"Day {day} pre-checkpoint; keep distribution executing."

    days_left = (CYCLE_END - date.today()).days
    if day >= 88:
        if rev >= SCALE_REVENUE_CENTS:
            return "scale", f"Day {day}/90 · ${rev/100:.0f} collected ≥ ${SCALE_REVENUE_CENTS/100:.0f} SCALE threshold."
        if rev >= EXTEND_FLOOR_CENTS:
            return "extend", f"Day {day}/90 · ${rev/100:.0f} between EXTEND floor (${EXTEND_FLOOR_CENTS/100:.0f}) and SCALE (${SCALE_REVENUE_CENTS/100:.0f})."
        return "kill-pending-distribution-check", (
            f"Day {day}/90 · ${rev/100:.0f} < ${EXTEND_FLOOR_CENTS/100:.0f} EXTEND floor. "
            f"Run filesystem_scan + cycle_digest to check distribution-execution ≥80% before kill is legal."
        )
    return "continue", f"Day {day}/90 · ${rev/100:.0f} collected · {days_left}d remaining."


def format_digest(state: dict, verdict: tuple[str, str]) -> str:
    v_label, v_reason = verdict
    avg_score = state["avg_reconciliation_score"]
    avg_str = f"{avg_score*100:.1f}%" if isinstance(avg_score, (int, float)) else "n/a (no deliveries yet)"
    rev_str = f"${state['rev_total_cents']/100:,.2f}"
    lines = [
        f"🔬 Bank2QBO · Day {state['day_number']} of 90 (Cycle 1)",
        f"Today: {state['today']} · Day-14 checkpoint: {state['day14_checkpoint']} · Gate: {state['cycle_end']}",
        "",
        f"Leads: {state['leads_total']} total ({state['leads_today']} today)",
        f"Paid: {state['conv_total']} conversions · {rev_str}",
        f"PDFs uploaded today: {state['pdfs_today']}",
        f"Deliveries: {state['deliv_total']} total ({state['deliv_today']} today)",
        f"Avg reconciliation accuracy: {avg_str}",
        "",
        f"Verdict: {v_label}",
        f"Reason: {v_reason}",
    ]
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        return False
    try:
        subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                f"https://api.telegram.org/bot{bot}/sendMessage",
                "-d", f"chat_id={chat}", "--data-urlencode", f"text={message}",
            ],
            timeout=10, check=True,
        )
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"concierge.db missing at {DB_PATH} — run migrations first")
        return 1

    state = gather_state()
    verdict = derive_verdict(state)
    message = format_digest(state, verdict)
    print(message)
    if not args.dry_run:
        send_telegram(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
