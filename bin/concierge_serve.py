#!/usr/bin/env python3
"""Bank2QBO concierge web server.

Three endpoints:
  GET  /health                      — liveness probe
  POST /webhook/stripe              — Stripe checkout.session.completed → intake.handle_stripe_event
  GET  /upload?session_id=<id>      — minimal HTML upload form
  POST /upload                      — multipart PDF receive → intake.handle_pdf_upload

Run with:
    PYTHONPATH=. uvicorn bin.concierge_serve:app --host 127.0.0.1 --port 8090

Expose via existing Cloudflare tunnel + DNS once bank2qbo.com is registered.

Stripe webhook signature verification REQUIRED in production. Set
STRIPE_WEBHOOK_SECRET env var. Without it, /webhook/stripe rejects all
requests with 401 to avoid spoofing the conversions table.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

# Make sibling agents/ importable when run from project root
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agents import intake  # noqa: E402

try:
    from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile, File
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
except ImportError:
    print("FATAL: fastapi not installed. Install with: pip install fastapi uvicorn python-multipart")
    sys.exit(1)

app = FastAPI(title="Bank2QBO Concierge", version="0.1.0")


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "service": "bank2qbo-concierge", "ts": int(time.time())}


LANDING_HTML = (REPO / "landing" / "index.html").read_text(encoding="utf-8") if (REPO / "landing" / "index.html").exists() else "<h1>Bank2QBO</h1>"
THANKS_HTML = (REPO / "landing" / "thanks.html").read_text(encoding="utf-8") if (REPO / "landing" / "thanks.html").exists() else "<h1>Thanks</h1>"


@app.get("/", response_class=HTMLResponse)
def root():
    return LANDING_HTML


@app.get("/thanks", response_class=HTMLResponse)
def thanks_page():
    return THANKS_HTML


# ── Stripe webhook ──────────────────────────────────────────────────────────

def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Stripe HMAC verification.

    Header format: `t=<timestamp>,v1=<signature>` (plus optional v0).
    See https://stripe.com/docs/webhooks/signatures
    """
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
    except ValueError:
        return False
    ts = parts.get("t", "")
    v1 = parts.get("v1", "")
    if not ts or not v1:
        return False
    signed_payload = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="webhook_secret_not_configured")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not _verify_stripe_signature(payload, sig, secret):
        raise HTTPException(status_code=401, detail="invalid_signature")

    try:
        event = json.loads(payload.decode())
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json")

    result = intake.handle_stripe_event(event)
    return JSONResponse(result)


# ── PDF upload page ─────────────────────────────────────────────────────────

UPLOAD_FORM = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Upload your statement · Bank2QBO</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#faf7f2;color:#1a1a1a;padding:2rem;max-width:640px;margin:0 auto;line-height:1.5}}
h1{{color:#1e3a5f;font-size:1.5rem}}
form{{background:white;padding:1.5rem;border-radius:8px;border:2px solid #c9a961;margin-top:1rem}}
label{{display:block;margin:0.75rem 0 0.25rem;font-weight:600}}
input,select{{width:100%;padding:0.6rem;border:1px solid #e5dfd6;border-radius:4px;font-size:1rem;box-sizing:border-box}}
button{{margin-top:1rem;background:#1e3a5f;color:#faf7f2;padding:0.9rem 1.6rem;border:none;border-radius:6px;font-size:1rem;font-weight:600;cursor:pointer;width:100%}}
button:hover{{background:#0f1f33}}
.note{{color:#6b6b6b;font-size:0.9rem;margin-top:1rem}}
</style></head><body>
<h1>📤 Upload your bank statement PDF</h1>
<p>Session: <code>{session_id}</code></p>
<p>I'll process this manually within 24h and email back a clean CSV + IIF plus reconciliation report.</p>
<form action="/upload" method="post" enctype="multipart/form-data">
  <input type="hidden" name="session_id" value="{session_id}">
  <label>Bank (helps with format hints)</label>
  <select name="bank_guess">
    <option value="">— select —</option>
    <option value="chase">Chase</option>
    <option value="bofa">Bank of America</option>
    <option value="wells">Wells Fargo</option>
    <option value="citi">Citibank</option>
    <option value="usbank">US Bank</option>
    <option value="capitalone">Capital One</option>
    <option value="amex">American Express</option>
    <option value="other">Other (type below)</option>
  </select>
  <label>If "Other", which bank?</label>
  <input type="text" name="bank_other" placeholder="Optional">
  <label>PDF file (up to 100 pages)</label>
  <input type="file" name="pdf" accept="application/pdf" required>
  <button type="submit">Upload — I'll process within 24h</button>
</form>
<p class="note">By uploading you agree to GLBA-aligned handling: TLS in transit, encrypted at rest, deleted on request. Reply "delete" to the delivery email and I purge within 1 business day.</p>
</body></html>"""


@app.get("/upload", response_class=HTMLResponse)
def upload_form(session_id: str = Query(..., min_length=10)):
    safe = session_id.replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(UPLOAD_FORM.format(session_id=safe))


@app.post("/upload")
async def upload_pdf(
    session_id: str = Form(...),
    bank_guess: str = Form(""),
    bank_other: str = Form(""),
    pdf: UploadFile = File(...),
):
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="must_be_pdf")
    file_bytes = await pdf.read()
    if len(file_bytes) > 50 * 1024 * 1024:  # 50 MB cap
        raise HTTPException(status_code=413, detail="file_too_large_50mb_max")
    bank = bank_other.strip() or bank_guess.strip() or None
    result = intake.handle_pdf_upload(
        session_id=session_id,
        filename=pdf.filename,
        file_bytes=file_bytes,
        bank_guess=bank,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return HTMLResponse(
        f"<html><body style='font-family:sans-serif;padding:2rem;max-width:640px;margin:0 auto'>"
        f"<h1 style='color:#1e3a5f'>✅ PDF received</h1>"
        f"<p>PDF ID: <code>{result['pdf_id']}</code> · {result.get('page_count', '?')} pages</p>"
        f"<p>You'll receive an email with the CSV + IIF + reconciliation report within 24h "
        f"(usually 4-6h during business hours).</p>"
        f"<p>Reply to that email with any questions or feedback — I personally review every delivery.</p>"
        f"<p style='color:#6b6b6b;font-size:0.9rem'>— Claudio at Bank2QBO</p>"
        f"</body></html>"
    )


if __name__ == "__main__":
    print("Run with: uvicorn bin.concierge_serve:app --host 127.0.0.1 --port 8090")
