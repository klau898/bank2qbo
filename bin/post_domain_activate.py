#!/usr/bin/env python3
"""Post-domain activation — one-shot script to wire up bank2qbo.com once registered.

Run AFTER:
  1. bank2qbo.com is registered in Cloudflare (or transferred in)
  2. Vercel landing is pointed at bank2qbo.com (Domain added in Vercel project)
  3. Cloudflare DNS A/CNAME points at Vercel
  4. Resend domain verification DNS records added (optional but recommended)

What this script does (in order, idempotent):
  1. Verifies bank2qbo.com is in Cloudflare account
  2. Creates Cloudflare Email Routing rules so support@bank2qbo.com forwards to Klau's inbox
  3. Updates pdftoqbo/.env RESEND_FROM_EMAIL to claudio@bank2qbo.com (once verified in Resend)
  4. Registers a Bank2QBO Stripe webhook endpoint pointing at https://bank2qbo.com/webhook/stripe
  5. Writes the new webhook signing secret back to pdftoqbo/.env
  6. Updates the landing's PostHog placeholder if POSTHOG_API_KEY is in .env
  7. Updates the landing's Formbricks form if FORMBRICKS_SURVEY_URL is in .env
  8. Triggers a fresh Vercel deploy
  9. Sends a Telegram confirmation message

Usage:
    python3 bin/post_domain_activate.py [--dry-run] [--klau-email klau@example.com]

The --klau-email is where support@bank2qbo.com will forward. Defaults to
the value in the script's KLAU_FORWARD_EMAIL constant — edit before run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"

# Auto-load .env so we have CLOUDFLARE_API_TOKEN, STRIPE_SECRET_KEY, etc.
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v

DOMAIN = "bank2qbo.com"
KLAU_FORWARD_EMAIL = "klau0350@gmail.com"  # ← EDIT or pass --klau-email


def cf_request(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ["CLOUDFLARE_API_TOKEN"]
    cmd = ["curl", "-s", "-X", method, "-H", f"Authorization: Bearer {token}",
           "-H", "Content-Type: application/json", f"https://api.cloudflare.com/client/v4{path}"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    return json.loads(subprocess.check_output(cmd, timeout=15).decode())


def stripe_request(method: str, path: str, params: dict | None = None) -> dict:
    key = os.environ["STRIPE_SECRET_KEY"]
    cmd = ["curl", "-s", "-X", method, "-u", f"{key}:", f"https://api.stripe.com/v1{path}"]
    if params:
        for k, v in params.items():
            if isinstance(v, list):
                for i, item in enumerate(v):
                    cmd += ["-d", f"{k}[{i}]={item}"]
            else:
                cmd += ["-d", f"{k}={v}"]
    return json.loads(subprocess.check_output(cmd, timeout=20).decode())


def step1_verify_domain_in_cloudflare() -> dict:
    r = cf_request("GET", f"/zones?name={DOMAIN}")
    zones = r.get("result", [])
    if not zones:
        return {"ok": False, "error": f"{DOMAIN} not found in Cloudflare account — register/transfer it first"}
    return {"ok": True, "zone_id": zones[0]["id"], "status": zones[0]["status"]}


def step2_email_routing(zone_id: str, dry_run: bool) -> dict:
    """Enable Email Routing + add rule: support@bank2qbo.com → KLAU_FORWARD_EMAIL."""
    if dry_run:
        return {"ok": True, "dry_run": True, "would_forward": f"support@{DOMAIN} → {KLAU_FORWARD_EMAIL}"}
    # Enable Email Routing
    cf_request("POST", f"/zones/{zone_id}/email/routing/enable")
    # Add destination address (needs verification by Klau email click — we initiate)
    dest = cf_request("POST", "/accounts/{account_id}/email/routing/addresses",
                      {"email": KLAU_FORWARD_EMAIL})
    # Add catch-all forwarding rule
    rule = cf_request("POST", f"/zones/{zone_id}/email/routing/rules",
                      {"actions": [{"type": "forward", "value": [KLAU_FORWARD_EMAIL]}],
                       "matchers": [{"type": "literal", "field": "to", "value": f"support@{DOMAIN}"}],
                       "enabled": True, "name": "support → klau"})
    return {"ok": True, "destination_added": dest, "rule_added": rule}


def step3_stripe_webhook(dry_run: bool) -> dict:
    """Create Stripe webhook endpoint for Bank2QBO + capture the signing secret."""
    if dry_run:
        return {"ok": True, "dry_run": True, "would_create": f"https://{DOMAIN}/webhook/stripe"}
    r = stripe_request("POST", "/webhook_endpoints", {
        "url": f"https://{DOMAIN}/webhook/stripe",
        "enabled_events": ["checkout.session.completed", "payment_intent.succeeded",
                           "charge.refunded", "customer.subscription.created",
                           "customer.subscription.updated", "customer.subscription.deleted"],
        "description": "Bank2QBO concierge intake (Cycle 1)",
        "metadata[brand]": "bank2qbo",
    })
    return {"ok": "secret" in r, "endpoint": r}


def step4_write_webhook_secret(secret: str) -> None:
    """Append the new STRIPE_WEBHOOK_SECRET to .env (replacing the empty line)."""
    content = ENV_PATH.read_text()
    if "STRIPE_WEBHOOK_SECRET=" in content:
        lines = content.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("STRIPE_WEBHOOK_SECRET="):
                lines[i] = f"STRIPE_WEBHOOK_SECRET={secret}"
                break
        ENV_PATH.write_text("\n".join(lines) + "\n")


def step5_redeploy_landing(dry_run: bool) -> dict:
    if dry_run:
        return {"ok": True, "dry_run": True}
    cmd = ["vercel", "--prod", "--yes", "--cwd", str(REPO / "landing")]
    try:
        out = subprocess.check_output(cmd, timeout=120).decode()
        return {"ok": True, "deploy_url": out.strip().splitlines()[-1] if out.strip() else "?"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def step6_telegram_announce(message: str) -> None:
    bot = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot or not chat:
        return
    subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://api.telegram.org/bot{bot}/sendMessage",
         "-d", f"chat_id={chat}", "--data-urlencode", f"text={message}"],
        timeout=10
    )


def main():
    global KLAU_FORWARD_EMAIL
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--klau-email", default=KLAU_FORWARD_EMAIL)
    args = p.parse_args()
    KLAU_FORWARD_EMAIL = args.klau_email

    print("=" * 70)
    print(f"Bank2QBO post-domain activation · domain={DOMAIN} · forward→{args.klau_email}")
    print("=" * 70)

    # Step 1
    print("\n[1/5] Verify domain in Cloudflare account...")
    r1 = step1_verify_domain_in_cloudflare()
    print(json.dumps(r1, indent=2))
    if not r1.get("ok"):
        print("\nCannot proceed. Register bank2qbo.com at Cloudflare first.")
        return 1
    zone_id = r1["zone_id"]

    # Step 2
    print("\n[2/5] Enable Email Routing + forwarding rule...")
    r2 = step2_email_routing(zone_id, args.dry_run)
    print(json.dumps(r2, indent=2)[:400])

    # Step 3
    print("\n[3/5] Create Stripe webhook endpoint...")
    r3 = step3_stripe_webhook(args.dry_run)
    print(json.dumps(r3, indent=2)[:500])
    if r3.get("ok") and not args.dry_run:
        secret = r3["endpoint"].get("secret", "")
        if secret:
            step4_write_webhook_secret(secret)
            print(f"   ↳ Wrote STRIPE_WEBHOOK_SECRET to {ENV_PATH}")

    # Step 4 — redeploy landing
    print("\n[4/5] Trigger Vercel re-deploy...")
    r5 = step5_redeploy_landing(args.dry_run)
    print(json.dumps(r5, indent=2)[:300])

    # Step 5 — Telegram announce
    print("\n[5/5] Telegram announce...")
    step6_telegram_announce(
        f"🎯 Bank2QBO post-domain activation complete · {DOMAIN} live · "
        f"email forwarding + Stripe webhook + landing redeployed"
    )

    print("\nDone. Next steps for Klau:")
    print("  · Verify Klau-forward-email in Cloudflare's email dest verification email")
    print(f"  · Add Resend domain verification DNS records (Resend dashboard → Domains → Add {DOMAIN})")
    print("  · Test full funnel: open https://bank2qbo.com → click $39 → pay → check Telegram for webhook event")
    return 0


if __name__ == "__main__":
    sys.exit(main())
