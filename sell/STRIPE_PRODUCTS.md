# Bank2QBO — Stripe Product + Payment-Link Spec

Per Codex-revised pricing anchors (May 14, 2026):
> "Bookkeepers DISTRUST cheap-unlimited AI on financial data. $29 too low as
> anchor. Anchor $99/mo Firm tier headline, $39 Starter beneath."

---

## Day-1 (concierge phase) Products

| Product slug | Price | Stripe type | Description | Metadata |
|---|---|---|---|---|
| `single_39` | $39.00 one-time | Payment Link | "Bank2QBO · Single Conversion · One PDF (≤100 pages), CSV + IIF, 24h delivery, refund if <99% reconciliation" | `{ "tier": "single", "version": "v1" }` |
| `pack_99` | $99.00 one-time | Payment Link | "Bank2QBO · 5-Pack · Five PDF conversions in 30 days, $19.80 each effective, all 99%+ accuracy guaranteed" | `{ "tier": "pack", "version": "v1" }` |
| `firm_waitlist` | $0 (waitlist signup) | n/a — Formbricks form | $99/mo · 500 pages/mo · launching Week 3 May 2026 · waitlist for 30% lifetime discount | `{ "tier": "firm", "version": "v1", "waitlist": true }` |
| `pro_waitlist` | $0 (waitlist signup) | n/a — Formbricks form | $249/mo · 1,500 pages/mo · launching Week 3 · waitlist for 30% lifetime discount | `{ "tier": "pro", "version": "v1", "waitlist": true }` |

---

## Webhook routing

Every `checkout.session.completed` event for these products goes to:

```
paywall-hook.mundallcfreight.com/webhook/stripe
```

(existing infrastructure — already verified working tonight)

The webhook handler (in `paywall-hook/bot.py`):
1. Parses metadata.tier
2. If `tier in ("single", "pack")`:
   - Inserts row into `pdftoqbo/state/concierge.db:conversions`
   - Telegram alerts Klau: "💰 NEW SALE — Bank2QBO {tier} — $XX from email@..."
   - Sends customer welcome email via Resend with upload link (concierge_serve.py upload endpoint)
3. If `tier in ("firm", "pro")`:
   - (Future) creates Stripe subscription
   - (Current Day-1) treats as waitlist signup

---

## Refund policy mechanics

Stripe automatically supports refund within 90 days. Klau processes via Stripe dashboard or
via the agent (`agents/refund_processor.py` — to build if refund volume exceeds 3).

The 99% reconciliation guarantee means: if `deliveries.reconciliation_score < 0.99`, the
customer is automatically eligible for refund. The `accuracy_verifier.py` flags this.

---

## After concierge validation passes (Day 14+)

Add:

| Product slug | Price | Type | Description |
|---|---|---|---|
| `firm_99_mo` | $99.00/mo | Subscription | 500 pages/mo, dashboard, bulk upload |
| `pro_249_mo` | $249.00/mo | Subscription | 1,500 pages/mo, batch processing, API access |
| `enterprise_custom` | TBD | Custom invoice | 10k+ pages/mo + signed BAA + SLA |

---

## Stripe creation commands

(Tomorrow morning, via Stripe API or dashboard — Klau approves before going live)

```bash
# Single $39
stripe products create --name "Bank2QBO Single Conversion" --description "One PDF bank statement → CSV + IIF in 24h, $39, refund if <99% reconciliation"
# capture product_id, then:
stripe prices create --product prod_XXXX --unit-amount 3900 --currency usd
# capture price_id, then:
stripe payment_links create --line-items[][price]=price_XXXX --line-items[][quantity]=1 --metadata[tier]=single --metadata[version]=v1 --after-completion[type]=redirect --after-completion[redirect][url]="https://bank2qbo.com/upload?session_id={CHECKOUT_SESSION_ID}"

# 5-Pack $99
stripe products create --name "Bank2QBO 5-Pack" --description "Five PDF conversions in 30 days, $19.80 each effective, 99%+ accuracy guaranteed"
stripe prices create --product prod_YYYY --unit-amount 9900 --currency usd
stripe payment_links create --line-items[][price]=price_YYYY --line-items[][quantity]=1 --metadata[tier]=pack --metadata[version]=v1 --after-completion[type]=redirect --after-completion[redirect][url]="https://bank2qbo.com/upload?session_id={CHECKOUT_SESSION_ID}"
```

(After creation, the two Payment Link URLs go in landing-page CTAs.)
