"""Concierge intake — receives PDF uploads + Stripe events, writes to SQLite, alerts Klau.

This is the "agent does the autonomous part" piece. Klau handles the manual
processing for the first 14 days; this code just:
  1. Receives the Stripe checkout.session.completed webhook → conversions row
  2. Receives the PDF upload (POST /upload) → pdfs row
  3. Telegram-alerts Klau on every event
  4. Sends a customer receipt email confirming next-steps

When the concierge phase validates (Day-14 ≥3 paid), Week-2 extends this with
agents/processor.py (Claude Vision parsing) and agents/deliverer.py (CSV+IIF
auto-build).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "state" / "concierge.db"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Stripe webhook handler ────────────────────────────────────────────────────

def handle_stripe_event(event: dict[str, Any]) -> dict:
    """Called by paywall-hook.mundallcfreight.com/webhook/stripe.

    Routes Bank2QBO events to the concierge pipeline.
    """
    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {}) or {}
    metadata = obj.get("metadata", {}) or {}

    if metadata.get("brand") != "bank2qbo":
        return {"skipped": True, "reason": "not_bank2qbo"}

    if event_type != "checkout.session.completed":
        return {"skipped": True, "reason": f"unhandled_event_type:{event_type}"}

    tier = metadata.get("tier", "unknown")
    amount = obj.get("amount_total", 0)
    email = obj.get("customer_email") or obj.get("customer_details", {}).get("email", "")
    session_id = obj.get("id", "")
    customer_id = obj.get("customer", "")

    # Insert conversion
    conn = _db()
    try:
        cur = conn.execute(
            """INSERT INTO conversions
               (stripe_session_id, stripe_customer_id, product_slug, amount_cents, email, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(stripe_session_id) DO NOTHING""",
            (session_id, customer_id, f"{tier}_{amount//100}", amount, email, json.dumps(metadata)),
        )
        conn.commit()
        conv_id = cur.lastrowid
    finally:
        conn.close()

    _send_telegram(
        f"💰 *NEW Bank2QBO SALE*\n"
        f"Tier: `{tier}` · `${amount/100:.2f}`\n"
        f"Email: `{email}`\n"
        f"Session: `{session_id}`\n\n"
        f"Customer will be redirected to: pdftoqbo.mundallcfreight.com/upload?session_id={session_id}\n"
        f"Expect a PDF upload within the next hour. SLA = 24h."
    )

    _send_customer_welcome(email, tier, session_id, amount)
    return {"ok": True, "conversion_id": conv_id, "tier": tier}


# ── PDF upload handler ────────────────────────────────────────────────────────

def handle_pdf_upload(
    session_id: str,
    filename: str,
    file_bytes: bytes,
    bank_guess: str | None = None,
) -> dict:
    """Called when the customer uploads a PDF at bank2qbo.com/upload."""
    storage_dir = REPO / "state" / "uploads" / session_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = storage_dir / filename
    pdf_path.write_bytes(file_bytes)

    import hashlib
    sha = hashlib.sha256(file_bytes).hexdigest()

    # Find the conversion row
    conn = _db()
    try:
        conv = conn.execute(
            "SELECT id, email FROM conversions WHERE stripe_session_id = ?",
            (session_id,),
        ).fetchone()
        if not conv:
            return {"error": "session_not_found", "session_id": session_id}

        # Count page count via lightweight PDF parse (no full OCR yet)
        try:
            import pypdf  # type: ignore
            reader = pypdf.PdfReader(str(pdf_path))
            pages = len(reader.pages)
        except Exception:
            pages = None

        cur = conn.execute(
            """INSERT INTO pdfs
               (conversion_id, filename, file_size_bytes, page_count, bank_guess, state, sha256)
               VALUES (?, ?, ?, ?, ?, 'received', ?)""",
            (conv["id"], filename, len(file_bytes), pages, bank_guess, sha),
        )
        conn.commit()
        pdf_id = cur.lastrowid
    finally:
        conn.close()

    _send_telegram(
        f"📥 *PDF received for Bank2QBO*\n"
        f"PDF id: `{pdf_id}` · pages: `{pages or '?'}`\n"
        f"Bank: `{bank_guess or 'unknown'}`\n"
        f"Customer: `{conv['email']}`\n"
        f"Path: `{pdf_path}`\n\n"
        f"SLA: 24h. Process via:\n"
        f"  `python3 agents/processor.py --pdf-id {pdf_id}`"
    )
    return {"ok": True, "pdf_id": pdf_id, "page_count": pages, "path": str(pdf_path)}


# ── Telegram + Resend helpers ────────────────────────────────────────────────

def _send_telegram(text: str) -> None:
    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except httpx.RequestError:
        pass


def _send_customer_welcome(email: str, tier: str, session_id: str, amount_cents: int) -> None:
    """Send the post-purchase email with upload-link + SLA."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key or not email:
        return
    from_email = os.environ.get("RESEND_FROM_EMAIL", "claudio@bank2qbo.com")
    from_name = os.environ.get("RESEND_FROM_NAME", "Claudio at Bank2QBO")
    upload_url = f"https://bank2qbo.com/upload?session_id={session_id}"

    subject = "Welcome to Bank2QBO — upload your PDF here"
    body = f"""<p>Hi —</p>

<p>Thanks for trying Bank2QBO. Here's how this works:</p>

<ol>
<li><strong>Upload your PDF here:</strong> <a href="{upload_url}">{upload_url}</a></li>
<li>I'll process it manually within 24 hours (faster, often within 4-6 hours during business hours)</li>
<li>You'll receive a clean CSV + IIF file by email with a reconciliation report (row count, sum of debits/credits, opening + closing balance match)</li>
<li>If reconciliation isn't 99%+, I'll re-run it free, or refund you no questions asked</li>
</ol>

<p>Your tier: <strong>{tier}</strong> ($‎{amount_cents/100:.2f} paid).</p>

<p>Questions or special bank format? Reply to this email — I personally read every message.</p>

<p>Claudio Cordoba<br>
Munda LLC · Miami FL<br>
bank2qbo.com · support@bank2qbo.com</p>"""

    try:
        httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": f"{from_name} <{from_email}>",
                "to": [email],
                "subject": subject,
                "html": body,
            },
            timeout=15,
        )
    except httpx.RequestError:
        pass


if __name__ == "__main__":
    # smoke test
    print("intake.py loaded OK")
    print(f"DB path: {DB_PATH}")
    print(f"DB exists: {DB_PATH.exists()}")
