# Bank2QBO — Cycle 1 Active Wedge (90-day binding gate, with Day-14 mini-checkpoint)

**Product:** AI-assisted PDF bank-statement → QuickBooks-ready CSV + IIF for US bookkeepers,
solo CPAs, and small accounting firms.

**Status:** Concierge MVP (Klau + Claude Vision + reconciliation verifier; no auto-pipeline yet)

## Gate hierarchy (reconciled 2026-05-15 with Cycle 1 lock)

This product is the **active wedge** of Cycle 1 in the archetype-cycle-loop spec at `~/vault/_CEO/ARCHETYPE_CYCLE_LOOP_DESIGN_2026-05-15.md`. The **90-day cycle gate is the binding outer envelope**; the original 14-day concierge gate from May 14 is preserved as an internal mini-checkpoint.

### Outer: Cycle 1 (90-day, binding per spec §6.2)

Cycle window: 2026-05-15 → 2026-08-13. Triple-metric gate at Day 90:

- **SCALE** = ≥$1,500 collected revenue OR ≥$500 MRR + ≥80% distribution executed
- **EXTEND** = $750-$1,499 OR $250-$499 MRR + strong demand + ≥80% distribution executed (one-time 30-day extension)
- **KILL** = ≥80% distribution executed AND revenue <$750 OR demand flat
- **REPAIR-EXECUTION** = distribution-volume <80% (KILL invalid, same archetype next cycle; per spec §6.2 hard-capped at 1 REPAIR per archetype)

### Inner: Day-14 mini-checkpoint (concierge-validation finding, not a kill-the-cycle gate)

The original 14-day concierge gate is preserved as an **early-signal checkpoint within the 90-day cycle**, not as an alternative end-state:

- **Day-14 result: ≥3 paid conversions ($39-$99 each)** → strong signal, eligible for §4.2 `EARLY-SCALE` override; otherwise just continue Week 3-12 of the 90-day plan with confidence
- **Day-14 result: 1-2 paid + 5+ leads in flight** → expected mid-cycle state; continue 90-day plan
- **Day-14 result: 0 paid after 25 cold DMs + Reddit interview-sourcing AND distribution-execution at-pace** → flag for Codex consultation; if pattern persists through Week 6 (~Day 42), evaluate KILL vs REPAIR-EXECUTION

The Day-14 checkpoint **cannot trigger a kill on its own** — kill/scale decisions happen at Day 90 per spec §6.2. Day-14 just informs Week-3-onward tactics.

## Pricing (Codex-revised anchors)

## Pricing (Codex-revised anchors)

- **Free:** 5 pages with watermark
- **Starter:** $39 single conversion (any size up to 100 pages)
- **5-pack:** $99 (5 conversions in 30 days, $19.80/each effective)
- **Firm $99/mo (headline anchor in product phase):** 500 pages/mo
- **Pro $249/mo:** 1,500 pages/mo + batch + priority

## Cycle 1 daily contract (Mon-Fri, per spec §6.4)

Klau's required daily distribution actions (channel-native logs corroborate; uncorroborated days count as zero per spec §6.4):

- **10 personalized LinkedIn / cold-email contacts** to US bookkeepers/accountants/firm owners — drop screenshot or URL into `~/vault/_CEO/cycle1_outreach_logs/linkedin/<today>/`
- **5 community / forum / Slack / Reddit interview-sourcing contacts or replies** — drop public URL line into `~/vault/_CEO/cycle1_outreach_logs/community/<today>.txt`
- **1 public proof asset** (Loom demo, anonymized reconciliation report, before/after, security note) — drop URL line into `~/vault/_CEO/cycle1_outreach_logs/proof/<today>.txt`
- **Process every inbound paid/trial file in 24h** — see `agents/processor.py`

Saturday: 1 proof asset + 25-account prospect list refresh.
Sunday: weekly log auto-generates at 9am ET via `~/projects/munda-cycle/weekly_log.py`.

## The 14-day plan (Codex-corrected, kill-rule = clicks not days)

| Days | Action | Owner |
|---|---|---|
| 1 | Buy bank2qbo.com · Build Lovable landing · Stripe links · PostHog + Formbricks | Klau (domain) + Me (rest) |
| 1-3 | Klau posts in r/Bookkeeping/r/Accounting/r/QuickBooks **as interview-sourcing** (no link, no pitch) | Klau |
| 1-3 | Klau DMs 25 bookkeepers in network (human-to-human, NO AI) | Klau |
| 1 | Klau posts Show-HN + Indie Hackers thread | Klau |
| 4-14 | Process every PDF that comes in MANUALLY with Claude Vision; audit every row; return CSV+IIF in 24h | Me + Klau (review) |
| 14 | Read signal, apply kill/scale rule | Me |

## Why concierge instead of fake-door landing

Codex peer-review verdict (May 14, 2026):
> "Bank-statement converters need ACCURACY PROOF, not pretty marketing. One bad row destroys trust.
> A Stripe link on a fake-door for a financial-data tool with no proof, no trial, no security
> story → expect ~0 conversions. Replace with concierge: 10 real bookkeepers send anonymized
> statements, you manually return QBO-ready CSV/IIF for $25-50 each. If they won't send files and pay,
> do not build."

## Deploy checklist (Klau-hands tomorrow morning — DO IN ORDER)

1. **Register `bank2qbo.com`** via Cloudflare or Namecheap (~$12). DNS to Vercel.
2. **Sign up PostHog (free)** at app.posthog.com → copy project key (looks like `phc_XXXX`) → search-and-replace `phc_PLACEHOLDER` in `landing/index.html`
3. **Sign up Formbricks (free)** at app.formbricks.com → create one survey with email + bank-name fields → copy survey URL → search-and-replace `PLACEHOLDER_SURVEY_ID` in `landing/index.html`
4. **Deploy landing** to Vercel: `cd ~/projects/pdftoqbo/landing && vercel --prod` (or push to GitHub → auto-deploy)
5. **Smoke-test the full flow:** click the Stripe Payment Link → does the redirect land on `/thanks.html` with your session ID visible? Required pass before sending any DM.
6. **Send Reddit Post #1** in r/Bookkeeping using the AUTHENTIC builder framing (per `sell/REDDIT_POSTS.md` — NOT the false-identity version)
7. **Send 5 personalized LinkedIn DMs** using Template #1 from `sell/DM_SCRIPTS.md`
8. **Post Show-HN** + r/SideProject (Post #5 in REDDIT_POSTS.md is the SideProject one — it's the ONLY one with a link)

## File layout

```
pdftoqbo/
├── agents/
│   ├── intake.py            # Receives PDF uploads → SQLite → Telegram alert
│   ├── processor.py         # Claude Vision → row extraction → reconciliation check
│   ├── deliverer.py         # Sends CSV+IIF via Resend with reconciliation report
│   └── accuracy_verifier.py # Compares totals, flags suspicious rows
├── bin/
│   ├── concierge_serve.py   # Web server for landing + uploads
│   └── daily_digest.py      # 09:00 ET daily Telegram digest of conversions+leads
├── config/
│   ├── config.toml
│   └── bank_formats.yaml    # Per-bank parsing hints (Chase, BoA, Wells, Citi, etc.)
├── landing/                 # Lovable-generated, synced to GitHub
├── migrations/
│   └── 001_concierge_pipeline.sql
├── sell/
│   ├── LANDING_COPY.md      # Lovable prompt + final positioning
│   ├── DM_SCRIPTS.md        # 25 LinkedIn/IG DM templates (Klau sends, human-to-human)
│   ├── REDDIT_POSTS.md      # Interview-sourcing drafts (NO link, NO pitch)
│   └── STRIPE_PRODUCTS.md   # Pricing tier definitions
├── state/
│   ├── concierge.db          # The pipeline SQLite
│   └── decisions.jsonl      # Every kill/scale decision logged
└── docs/
    └── CODEX_REVIEWS.md     # Every Codex review pinned + actioned
```

## Reconciliation accuracy bar (the THING that matters)

Per Codex's flagged failure mode: bookkeepers don't need OCR, they need reconciliation.
Every concierge delivery must include:
- Row count
- Sum of debits vs credits
- Statement opening + closing balance check
- Flagged rows: scanned PDFs, multi-line continuations, check images, fee reversals
- Reconciliation score: 99.0%+ delivered, anything below → re-run + flag to customer

## What's autonomous vs Klau-hands

| Step | Autonomous | Klau-hands |
|---|---|---|
| Domain purchase | — | Klau (registrar login + payment) |
| Landing build via Lovable | Me via Playwright (Klau's logged-in session) | — |
| Stripe product + payment-link creation | Me via API | — |
| Reddit posts | Drafted by me; Codex-reviewed | Klau posts (account credibility) |
| LinkedIn/IG DMs | Drafted by me; Codex-reviewed | Klau sends (legal compliance) |
| PDF processing | Me + Claude Vision | Klau review on Day-1-2 outputs |
| Reconciliation audit | Me (accuracy_verifier.py) | Klau spot-checks |
| Delivery email | Me via Resend | — |
| Telegram alerts | Me | Klau gets pinged |
| Day-14 kill/scale decision | Me applies rule | Klau gets summary, can override |

## What we measure daily

```
concierge.db:
  leads             — every inbound (form, DM reply, Reddit DM)
  conversions       — paid Stripe events
  pdfs              — every file uploaded + processing state
  deliveries        — every CSV+IIF sent + reconciliation score
  feedback          — every customer reply post-delivery (positive/negative/silence)
  decisions         — daily kill-scale snapshot
```

Daily 09:00 ET Telegram digest:
```
🔬 Bank2QBO · Day N
Leads: X (Y today)
Paid: X ($Y total)
PDFs processed: X
Avg reconciliation accuracy: 99.X%
Today's verdict: [continue | extend | kill]
```
