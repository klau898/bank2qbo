# Bank2QBO — Landing Page Copy

**Domain:** bank2qbo.com
**Goal:** drive paid concierge conversions ($39 single OR $99 5-pack)
**Audience:** US solo bookkeepers + small-CPA-firm partners + SMB owners who DIY their books
**Tone:** clear, calm, accountancy-trustworthy. NOT "AI revolution" hype. NOT cheap.

---

## Hero

**Headline:** Convert any US bank statement PDF into QuickBooks-ready CSV or IIF in 24 hours.

**Sub-headline:** Real human review on every file. 99%+ reconciliation accuracy guaranteed. $39 for one statement. $99 for five.

**Primary CTA:** [Send your first statement — $39] (Stripe Payment Link → Free 5-page trial available)

**Secondary CTA:** [Try 5 pages free — no card] (Formbricks email-capture → manual processing)

---

## The Pain (one paragraph, no buzzwords)

Your client just sent you a 47-page Chase PDF — for a month. You can either retype every transaction into QuickBooks, pay a junior $150 to do it, or fight with a generic OCR tool that puts the date in the description field and leaves out half the credit-card fees.

There's a fourth option.

---

## How It Works

1. **You upload one PDF.** (Drag-and-drop. Any US bank, any size. Up to 1,000 pages on the Pro tier.)
2. **A human reviewer (me, Claudio at Munda LLC) processes it with Claude Vision + a reconciliation verifier.** Every row gets checked: dates, descriptions, debits/credits, signs, merged lines, scanned check images, bank fees.
3. **In 24 hours you receive two files:** a clean CSV (for any system) and a QBO-ready IIF (drag straight into QuickBooks Desktop) or a categorized 3-column CSV (for QBO Online import). Plus a reconciliation report: row count, sum of debits, sum of credits, opening + closing balance match.
4. **If reconciliation isn't above 99%, we re-run it.** Free.

---

## What's different from DocuClipper / Veryfi / generic OCR

- **24-hour human review on EVERY file.** Not auto-magic. Real reconciliation.
- **No subscription required for occasional use.** $39 per statement, full refund if not 99% accurate.
- **Bilingual support (EN/ES).** Spanish-speaking accountants serving Hispanic SMB clients get a native-Spanish receipt + walkthrough.
- **Per-bank tuning.** Chase, Bank of America, Wells Fargo, Citi, Capital One, Discover, US Bank, Truist, PNC — we keep a private library of per-bank parsing rules tuned by hand.
- **No data retention.** Your client's statements are deleted from our servers within 24 hours of delivery, by default. (HIPAA/GLBA-friendly posture.)

---

## Pricing (Codex-anchored)

| Tier | Price | What you get |
|---|---|---|
| **Trial** | Free | First 5 pages. Watermarked output. No payment. |
| **Single** | **$39** | One statement, any size up to 100 pages. CSV + IIF. 24h delivery. Full refund if <99% accuracy. |
| **5-Pack** | **$99** | Five statements in 30 days. $19.80 each effective. Best for one-time client cleanup projects. |
| **Firm Monthly** | **$99/mo** *(coming Week 3 — join waitlist)* | 500 pages/mo. Bulk upload. Account dashboard. Priority queue. |
| **Pro Monthly** | **$249/mo** *(coming Week 3 — join waitlist)* | 1,500 pages/mo. Batch processing. API access. Priority support. |

---

## Trust signals

- **Founded by Claudio Cordoba** (Munda LLC, Miami FL). 5+ years working with QuickBooks + bookkeeping workflows.
- **24/7 support email:** support@bank2qbo.com — reply within 2 hours during business hours.
- **Money-back guarantee:** If your reconciliation isn't 99%+ accurate, full refund. No questions.
- **Privacy:** Files deleted within 24h of delivery. We never share, train models on, or store statement data beyond delivery.

---

## FAQ

**Q: How is this different from DocuClipper / Veryfi / Dext?**
A: Those are full-auto OCR — fast, but you have to audit every row anyway. We add human verification + a per-bank library + a 99% reconciliation guarantee, so you can hand the output straight to a client without re-checking. For one-off cleanup jobs the $39 flat fee usually beats the $34/mo Dext subscription.

**Q: Can I really upload a 200-page PDF?**
A: Yes. Single tier covers up to 100 pages; for larger, drop us a line at support@bank2qbo.com and we'll quote per-page above 100.

**Q: My client has a weird bank — will it work?**
A: If it's a US bank (state, regional, credit union, fintech like Mercury/Bluevine/Chime), yes. We add new bank formats weekly. If we can't get above 99% reconciliation, full refund.

**Q: HIPAA / SOC 2 / etc.?**
A: We're a single-operator service in concierge mode. We follow GLBA reasonable-safeguards: TLS in transit, encrypted at rest, deleted within 24h. We're not a Stripe-Atlas-incorporated SaaS yet. If your firm requires a signed BAA/MNDA we can sign one — email support@bank2qbo.com.

**Q: When will the monthly tiers ship?**
A: Week 3 of May 2026. Join the waitlist on this page and we'll email you with a 30% lifetime discount when it goes live.

**Q: Refund policy?**
A: 99% reconciliation accuracy guaranteed. If your file isn't that accurate, full refund, no questions, within 24 hours of you flagging it.

---

## Below-the-fold: real customer outcomes (TODO after first 5 deliveries — leave blank Day 1)

> *(testimonial slot 1)*
> *(testimonial slot 2)*
> *(testimonial slot 3)*

---

## Footer

**Bank2QBO** by **Munda LLC** · Miami FL · USDOT 4514304 · EIN 41-2402793
support@bank2qbo.com · 786-822-7682 · Privacy · Terms

---

## Implementation notes for Lovable build

- **Page layout:** single-page, fixed-CTA-button at top-right ("Convert one — $39")
- **Color scheme:** professional dark blue (#1e3a5f) + cream (#faf7f2). Trust-money colors. NO neon. NO purple. NO "AI" iconography.
- **Hero image:** simple split-screen — left side: messy PDF page (blurred). Right side: clean CSV rows. Arrow between.
- **No stock photos of fake smiling people.**
- **Tracking embed:** PostHog snippet in `<head>` (free tier, 5k recordings/mo). Formbricks waitlist form embedded mid-page.
- **Stripe Payment Links:**
  - Single $39 → metadata `{ "product_slug": "single_39" }`
  - 5-Pack $99 → metadata `{ "product_slug": "pack_99" }`
- **Webhook target:** `paywall-hook.mundallcfreight.com/webhook/stripe` (existing infrastructure — just routes Bank2QBO events to the concierge.db ingest)
- **Mobile-first:** 80% of bookkeeper traffic on desktop, but the CTA must work on mobile so they can forward the link to a partner
