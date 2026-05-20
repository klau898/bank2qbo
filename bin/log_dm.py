#!/usr/bin/env python3
"""
Bank2QBO outreach quick-log CLI.

Usage:
  log_dm.py dm "First Last" [--title "Title"] [--company "Co"] [--url URL] [--notes "..."]
  log_dm.py reply PROSPECT_ID "reply summary"
  log_dm.py list [--status STATUS]
  log_dm.py stats
  log_dm.py pipeline
"""

import argparse, sqlite3, os, sys
from datetime import datetime

DB = os.path.expanduser("~/Projects/pdftoqbo/state/outreach_crm.db")


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_dm(args):
    conn = connect()
    cur = conn.cursor()

    # upsert prospect
    cur.execute(
        "SELECT id FROM prospects WHERE name = ? COLLATE NOCASE", (args.name,)
    )
    row = cur.fetchone()
    if row:
        pid = row["id"]
        # update fields if provided
        if args.title:
            cur.execute("UPDATE prospects SET title=? WHERE id=?", (args.title, pid))
        if args.company:
            cur.execute("UPDATE prospects SET company=? WHERE id=?", (args.company, pid))
        if args.url:
            cur.execute("UPDATE prospects SET profile_url=? WHERE id=?", (args.url, pid))
        if args.notes:
            cur.execute("UPDATE prospects SET notes=? WHERE id=?", (args.notes, pid))
        cur.execute("UPDATE prospects SET status='contacted' WHERE id=?", (pid,))
        print(f"Prospect updated (id={pid}): {args.name}")
    else:
        cur.execute(
            """INSERT INTO prospects (name, title, company, channel, profile_url, notes, status)
               VALUES (?, ?, ?, 'linkedin', ?, ?, 'contacted')""",
            (args.name, args.title, args.company, args.url, args.notes),
        )
        pid = cur.lastrowid
        print(f"Prospect created (id={pid}): {args.name}")

    # log touchpoint
    summary = args.msg if hasattr(args, "msg") and args.msg else "Bank2QBO PDF workflow question DM"
    cur.execute(
        """INSERT INTO touchpoints (prospect_id, channel, direction, content_summary)
           VALUES (?, 'linkedin', 'outbound', ?)""",
        (pid, summary),
    )
    conn.commit()
    conn.close()
    print(f"  DM logged at {datetime.now().strftime('%H:%M ET')}")
    _print_day_count()


def cmd_reply(args):
    conn = connect()
    cur = conn.cursor()

    pid = int(args.prospect_id)
    cur.execute("SELECT name FROM prospects WHERE id=?", (pid,))
    row = cur.fetchone()
    if not row:
        print(f"No prospect with id={pid}")
        sys.exit(1)

    # mark the most recent outbound touchpoint as replied
    cur.execute(
        """UPDATE touchpoints SET replied_at=datetime('now'), reply_summary=?
           WHERE id = (
             SELECT id FROM touchpoints
             WHERE prospect_id=? AND direction='outbound' AND replied_at IS NULL
             ORDER BY sent_at DESC LIMIT 1
           )""",
        (args.summary, pid),
    )
    cur.execute(
        "UPDATE prospects SET status='replied' WHERE id=?", (pid,)
    )
    conn.commit()
    conn.close()
    print(f"Reply logged for {row['name']} (id={pid}): {args.summary}")


def cmd_list(args):
    conn = connect()
    cur = conn.cursor()
    status_filter = args.status if args.status else None

    if status_filter:
        cur.execute(
            "SELECT id, name, title, company, status, created_at FROM prospects WHERE status=? ORDER BY created_at DESC",
            (status_filter,),
        )
    else:
        cur.execute(
            "SELECT id, name, title, company, status, created_at FROM prospects ORDER BY created_at DESC"
        )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No prospects yet. Use: log_dm.py dm \"Name\" --title \"Title\"")
        return

    print(f"{'ID':>3}  {'Name':<22} {'Title':<28} {'Status':<12} {'Date'}")
    print("-" * 80)
    for r in rows:
        date = r["created_at"][:10] if r["created_at"] else ""
        title = (r["title"] or "")[:27]
        print(f"{r['id']:>3}  {r['name']:<22} {title:<28} {r['status']:<12} {date}")


def cmd_stats(args):
    conn = connect()
    cur = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    cur.execute(
        "SELECT COUNT(*) FROM touchpoints WHERE direction='outbound' AND DATE(sent_at)=?",
        (today,),
    )
    today_dms = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM touchpoints WHERE direction='outbound'")
    total_dms = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM prospects WHERE status='replied'")
    replies = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM prospects WHERE status='paid'")
    paid = cur.fetchone()[0]

    cur.execute("SELECT SUM(amount_cents) FROM conversions")
    revenue = (cur.fetchone()[0] or 0) // 100

    conn.close()

    print(f"=== Bank2QBO Outreach Stats ===")
    print(f"Today's DMs:     {today_dms} / 5 minimum  {'✓' if today_dms >= 5 else '← NEED MORE'}")
    print(f"Total DMs sent:  {total_dms}")
    print(f"Replies:         {replies}")
    print(f"Paid:            {paid}")
    print(f"Revenue:         ${revenue}")
    print(f"")

    # day 14 math
    from datetime import date, timedelta
    cycle_start = date(2026, 5, 15)
    day14 = cycle_start + timedelta(days=13)
    today_date = date.today()
    days_left = (day14 - today_date).days
    if days_left > 0:
        dms_needed = max(0, 45 - total_dms)
        print(f"Day-14 checkpoint: {day14} ({days_left} days away)")
        print(f"DMs still needed for 45 total: {dms_needed} ({dms_needed // max(days_left,1)}/day)")
    else:
        print(f"Day-14 checkpoint: PASSED")


def cmd_pipeline(args):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pipeline")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("Pipeline empty.")
        return

    print(f"{'Name':<22} {'Status':<12} {'DMs':>4}  {'Last contact':<20} {'Revenue':>8}")
    print("-" * 72)
    for r in rows:
        lc = (r["last_contact"] or "")[:16]
        rev = f"${int(r['revenue'] or 0)}"
        print(f"{r['name']:<22} {r['status']:<12} {r['touchpoints']:>4}  {lc:<20} {rev:>8}")


def _print_day_count():
    conn = connect()
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute(
        "SELECT COUNT(*) FROM touchpoints WHERE direction='outbound' AND DATE(sent_at)=?",
        (today,),
    )
    count = cur.fetchone()[0]
    conn.close()
    bar = "█" * count + "░" * max(0, 5 - count)
    print(f"  Today: [{bar}] {count}/5 DMs")


def main():
    parser = argparse.ArgumentParser(description="Bank2QBO outreach CRM logger")
    sub = parser.add_subparsers(dest="cmd")

    p_dm = sub.add_parser("dm", help="Log a sent DM")
    p_dm.add_argument("name", help="Prospect full name")
    p_dm.add_argument("--title", default=None, help="Job title")
    p_dm.add_argument("--company", default=None, help="Company name")
    p_dm.add_argument("--url", default=None, help="LinkedIn profile URL")
    p_dm.add_argument("--notes", default=None, help="Free-text notes")
    p_dm.add_argument("--msg", default=None, help="Content summary (defaults to standard)")

    p_reply = sub.add_parser("reply", help="Log a reply from prospect")
    p_reply.add_argument("prospect_id", help="Prospect ID from list")
    p_reply.add_argument("summary", help="Brief summary of their reply")

    p_list = sub.add_parser("list", help="List prospects")
    p_list.add_argument("--status", default=None,
                        help="Filter: identified|contacted|replied|interested|paid|dead")

    sub.add_parser("stats", help="Today's progress + Day-14 math")
    sub.add_parser("pipeline", help="Full pipeline view")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "dm": cmd_dm,
        "reply": cmd_reply,
        "list": cmd_list,
        "stats": cmd_stats,
        "pipeline": cmd_pipeline,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
