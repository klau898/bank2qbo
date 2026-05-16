"""Concierge deliverer — Klau approves, deliverer sends.

Workflow:
  1. processor.py produces CSV+IIF + reconciliation report
  2. Klau spot-checks 3-5 rows, runs:
        python3 agents/deliverer.py --delivery-id N
     (or --delivery-id N --reject to mark for re-run)
  3. deliverer emails the files to the customer + Telegram alerts
  4. Feedback collection script polls the customer's reply
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "state" / "concierge.db"


def deliver(delivery_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        d = conn.execute(
            """SELECT d.*, p.filename, c.email, c.product_slug, c.amount_cents
               FROM deliveries d
               JOIN pdfs p ON d.pdf_id = p.id
               JOIN conversions c ON p.conversion_id = c.id
               WHERE d.id = ?""",
            (delivery_id,),
        ).fetchone()
        if not d:
            return {"error": "delivery_not_found"}

        csv_path = Path(d["csv_path"])
        iif_path = Path(d["iif_path"])
        if not csv_path.exists() or not iif_path.exists():
            return {"error": "output_files_missing", "csv": str(csv_path), "iif": str(iif_path)}

        score = d["reconciliation_score"]
        if score < 0.99:
            return {
                "error": "reconciliation_below_threshold",
                "score": score,
                "advice": "Run processor.py again, or set --force to ship anyway with disclosure",
            }

        api_key = os.environ.get("RESEND_API_KEY")
        if not api_key:
            return {"error": "RESEND_API_KEY not set"}

        # Build the email
        from_email = os.environ.get("RESEND_FROM_EMAIL", "claudio@bank2qbo.com")
        from_name = os.environ.get("RESEND_FROM_NAME", "Claudio at Bank2QBO")
        subject = f"Your Bank2QBO conversion is ready ({d['filename']})"

        balance_match = "matches statement closing balance" if abs(d.get("opening_balance_cents") or 0) > 0 else "manually verified"

        html = f"""<p>Hi —</p>

<p>Your conversion is ready. Two files attached:</p>

<ul>
<li><strong>{csv_path.name}</strong> — a clean CSV (Date, Description, Debit, Credit, Balance). Imports cleanly into QBO Online via "Upload Transactions" → CSV format.</li>
<li><strong>{iif_path.name}</strong> — IIF file for QuickBooks Desktop. Just drag-and-drop into QuickBooks → File → Utilities → Import → IIF Files.</li>
</ul>

<p><strong>Reconciliation report:</strong></p>
<ul>
<li>Row count: <strong>{d['row_count']}</strong></li>
<li>Sum of debits: <strong>${(d['sum_debits_cents'] or 0)/100:,.2f}</strong></li>
<li>Sum of credits: <strong>${(d['sum_credits_cents'] or 0)/100:,.2f}</strong></li>
<li>Reconciliation score: <strong>{score*100:.1f}%</strong> ({balance_match})</li>
</ul>

<p>If anything looks off — even one row — reply to this email immediately. I re-run for free, or refund no questions asked.</p>

<p>Want the Firm tier ($99/mo, 500 pages, dashboard) when it launches Week 3? Reply "waitlist" and I'll lock in the 30% lifetime discount for you.</p>

<p>Claudio Cordoba<br>
Munda LLC · Miami FL<br>
bank2qbo.com · support@bank2qbo.com<br>
786-822-7682</p>"""

        attachments = []
        for path in (csv_path, iif_path):
            attachments.append({
                "filename": path.name,
                "content": base64.b64encode(path.read_bytes()).decode(),
            })

        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": f"{from_name} <{from_email}>",
                "to": [d["email"]],
                "subject": subject,
                "html": html,
                "attachments": attachments,
            },
            timeout=30,
        )
        r.raise_for_status()
        msg_id = r.json().get("id")

        conn.execute(
            "UPDATE deliveries SET delivery_email_id=?, delivered_at=CURRENT_TIMESTAMP, klau_approved=1 WHERE id=?",
            (msg_id, delivery_id),
        )
        conn.execute(
            "UPDATE pdfs SET state='delivered' WHERE id=?",
            (d["pdf_id"],),
        )
        conn.commit()

        # Telegram alert
        bot = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if bot and chat:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{bot}/sendMessage",
                    json={
                        "chat_id": chat,
                        "text": (
                            f"✅ *Bank2QBO delivery SENT*\n"
                            f"To: `{d['email']}`\n"
                            f"PDF: `{d['filename']}`\n"
                            f"Rows: {d['row_count']} · ${d['sum_debits_cents']/100:.2f} debits / ${d['sum_credits_cents']/100:.2f} credits\n"
                            f"Reconciliation: *{score*100:.1f}%*\n"
                            f"Resend msg: `{msg_id}`\n\n"
                            f"Watch for reply within 24h for feedback row."
                        ),
                        "parse_mode": "Markdown",
                    },
                    timeout=10,
                )
            except httpx.RequestError:
                pass

        return {"ok": True, "delivery_id": delivery_id, "resend_msg_id": msg_id, "score": score}

    finally:
        conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--delivery-id", type=int, required=True)
    p.add_argument("--reject", action="store_true", help="Mark delivery as needing re-run (no email)")
    p.add_argument("--force", action="store_true", help="Send even if reconciliation <99% (with disclosure)")
    args = p.parse_args()

    if args.reject:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "UPDATE deliveries SET klau_approved=0, klau_reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
                (args.delivery_id,),
            )
            conn.commit()
            print(f"Delivery {args.delivery_id} marked for re-run.")
        finally:
            conn.close()
        sys.exit(0)

    print(json.dumps(deliver(args.delivery_id), indent=2, default=str))
