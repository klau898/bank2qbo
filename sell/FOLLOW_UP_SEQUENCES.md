---
product: bank2qbo
updated: 2026-05-20
cycle: 1
---

# Bank2QBO Follow-Up Sequences

> Every reply type has a next message. Copy, personalize the [brackets], send within 2h of receiving reply.

---

## TYPE A — "I retype manually / my VA does it / takes forever"

**Translation:** They have the pain. HIGH value prospect. Move directly to qualification.

**Reply:**
> Got it — yeah, that's what I keep hearing. Quick follow-up: how long does a
> 30-page statement take you, end to end? And would you ever pay a flat $39 to
> have a human verify + return a clean CSV + IIF in 24 hours, full refund if
> not 99% accurate?

**If they say yes / "sounds interesting":** → Send Type A2 (offer + trial)

**If they say "depends / how does it work":** → Send Type A3 (mechanics)

---

## TYPE A2 — Closer (after A gets positive signal)

> Perfect. Here's how it works:
>
> You email me the PDF at support@bank2qbo.com — I convert it, human-check
> every line against the statement totals, and return a clean CSV (+ IIF for
> QuickBooks import) within 24 hours. $39 flat, full refund if reconciliation
> isn't 99%.
>
> First five pages are free if you want to test it with a real statement before
> committing. Just reply here and I'll send you the upload link.

**Log as "interested" in CRM:**
```
log_dm reply [ID] "Sent offer — awaiting test PDF"
```

---

## TYPE A3 — Mechanics explanation

> It's pretty manual on my end:
>
> 1. You email the PDF
> 2. I split it into sections, run OCR, fix every OCR error by hand
> 3. Cross-check totals (running sum vs statement total)
> 4. Deliver CSV + IIF
>
> Typically done in 6-10 hours, 24h max. Works even for credit unions with
> weird table formatting that most automated tools can't handle.
>
> $39 per statement. Free 5-page test if you want to try a slice first.

---

## TYPE B — "I use DocuClipper / Dext / Hubdoc / [tool]"

**Translation:** They have a solution. Goal: find the EDGE CASES where their tool fails.

**Reply:**
> Good to know — [DocuClipper] is solid for regular formats. Does it handle
> credit union PDFs well, or do you ever get statements where the table
> structure is weird and it misses rows or misaligns columns?
>
> I'm specifically building for the edge cases the tools choke on. Curious if
> you ever hit those.

**If they say "actually yeah, credit union PDFs are a mess":** → pivot to TYPE A flow
**If they say "no, works fine for me":** Thank them, ask for a referral: TYPE E

---

## TYPE C — "We use bank feeds, don't get PDFs"

**Translation:** Wrong fit. Not a prospect. Quick close + referral ask.

**Reply:**
> That makes sense — if the bank has a feed it's a non-issue. Appreciate you
> responding. Do you know any solo bookkeepers in your network who still deal
> with small credit union clients? That's really who I'm looking for.

**Log as "dead" in CRM:**
```
log_dm reply [ID] "Uses bank feeds — wrong fit. Asked for referral."
```

---

## TYPE D — "Sounds interesting, tell me more" (vague positive)

**Translation:** Curious but not committed. Give them the one-liner.

**Reply:**
> Short version: it's a pay-per-use conversion service for the statements
> where no bank feed exists and no CSV export. You email the PDF, you get a
> clean CSV + IIF back in 24h. $39. 99% accuracy or full refund.
>
> If you have one of those sitting in your inbox right now, I'll do the first
> 5 pages free so you can see the output quality.

---

## TYPE E — "I'm fine, but maybe X would need this" (referral signal)

**Translation:** They're helpful. Get the warm lead.

**Reply:**
> That's exactly the person I'm looking for — do you think [X] would be open
> to a quick message from me? Or if you want to forward this to them and make
> the intro, I'd appreciate it.

---

## TYPE F — No reply after 5 days

**Send ONE follow-up only, then archive:**

> Hey [Name] — didn't hear back, no worries at all. If the PDF→QBO workflow
> ever becomes a headache, I'm at support@bank2qbo.com. Good luck with the
> season.

**Log as "dead" after no response to follow-up:**
```
log_dm reply [ID] "No reply after follow-up — archived"
```

---

## CRM Status Values

| Status | Meaning | Next action |
|---|---|---|
| `identified` | Found on LinkedIn, not yet messaged | Send initial DM |
| `contacted` | DM sent | Wait 24–48h for reply |
| `replied` | They replied | Send appropriate follow-up type above |
| `interested` | Asked for details / want to test | Send test PDF link |
| `paid` | Stripe payment received | Deliver + log conversion |
| `dead` | Wrong fit, no reply after follow-up, ghosted | No further action |

---

## Quick CRM Commands

```bash
# Log a DM sent
log_dm dm "First Last" --title "QuickBooks ProAdvisor" --company "Acme Bookkeeping" --url "https://linkedin.com/in/..."

# Log a reply received
log_dm reply 3 "She retypes manually, takes ~2h for 30 pages"

# Mark as interested
log_dm reply 3 "Sent offer — awaiting test PDF"  # then manually update status

# Today's dashboard
log_dm stats

# Full pipeline
log_dm pipeline

# Filter by status
log_dm list --status replied
log_dm list --status interested
```

---

## Paid conversion flow

When someone Stripe-pays:
1. Check Stripe dashboard for payment ID
2. Log to CRM:
```bash
python3 -c "
import sqlite3, os
db = os.path.expanduser('~/Projects/pdftoqbo/state/outreach_crm.db')
conn = sqlite3.connect(db)
conn.execute('UPDATE prospects SET status=\"paid\" WHERE id=?', (PROSPECT_ID,))
conn.execute('INSERT INTO conversions (prospect_id, product, amount_cents, stripe_payment_id) VALUES (?,?,?,?)',
             (PROSPECT_ID, 'single_statement', 3900, 'pi_XXXXX'))
conn.commit()
conn.close()
print('Conversion logged')
"
```
3. Email them: reply to their DM or email support@bank2qbo.com instructions
4. Process the PDF → deliver within 24h

---

## Day-14 Mini-Checkpoint (2026-05-28)

Strong signal: ≥3 paid conversions
Weak signal: ≥10 conversations in "replied" or "interested" state
Dead signal: <5 total conversations

Check on the day:
```
log_dm stats
log_dm list --status replied
log_dm list --status interested
```
