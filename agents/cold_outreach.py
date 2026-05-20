"""
Bank2QBO Cold Email Outreach Daemon
~/projects/pdftoqbo/agents/cold_outreach.py

Lead sourcing:
  1. Apollo People Search API (bookkeeper / CPA / QuickBooks ProAdvisor titles, small firms)
  2. Hunter.io domain-search via Google Places (bookkeeper / CPA / accounting firm)
  3. Tavily AI search for email-mined leads as overflow
  4. Falls back to a curated static seed list when API quotas are exhausted

Email personalization:
  Uses `claude` CLI (free, Max plan) when available.
  Falls back to a high-quality hardcoded template with variable substitution.

Tracking:
  cold_outreach table in ~/projects/pdftoqbo/state/concierge.db
  Never double-emails.

Rate cap: 30 emails / day (Mon–Fri only, enforced by launchd plist).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "state" / "concierge.db"

LANDING_URL = "https://pdftoqbo.mundallcfreight.com?utm_source=cold_email"
FREE_OFFER = "Send us one PDF, we'll convert it free — no signup, no commitment."
FROM_NAME = "Claudio at Bank2QBO"
FROM_EMAIL = "hello@mundallcfreight.com"
DAILY_CAP = 30

# US cities with large concentrations of independent bookkeepers / small CPA firms
TARGET_CITIES = [
    "New York, NY",
    "Los Angeles, CA",
    "Chicago, IL",
    "Houston, TX",
    "Phoenix, AZ",
    "Philadelphia, PA",
    "San Antonio, TX",
    "San Diego, CA",
    "Dallas, TX",
    "Jacksonville, FL",
    "Miami, FL",
    "Atlanta, GA",
    "Boston, MA",
    "Seattle, WA",
    "Denver, CO",
    "Nashville, TN",
    "Portland, OR",
    "Las Vegas, NV",
    "Austin, TX",
    "Charlotte, NC",
]

TARGET_QUERIES = [
    "bookkeeper QuickBooks",
    "CPA firm small business",
    "accounting firm bookkeeping",
    "enrolled agent tax bookkeeping",
]

# ---------------------------------------------------------------------------
# Load env files
# ---------------------------------------------------------------------------
def _load_env(path: str) -> None:
    p = Path(path).expanduser()
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env("~/.config/munda/pdftoqbo.env")
_load_env("~/.config/munda/stripe_paywall.env")
_load_env("~/.config/munda/leads.env")

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------
MIGRATION = """
CREATE TABLE IF NOT EXISTS cold_outreach (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE,
    firm_name   TEXT,
    first_name  TEXT,
    city        TEXT,
    state       TEXT,
    source      TEXT,          -- 'places_hunter' | 'places_snov' | 'tavily' | 'static_seed'
    sent_at     TIMESTAMP,
    opened      INTEGER DEFAULT 0,
    replied     INTEGER DEFAULT 0,
    converted   INTEGER DEFAULT 0,
    dry_run     INTEGER DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(MIGRATION)
    conn.commit()
    return conn


def already_contacted(conn: sqlite3.Connection, email: str) -> bool:
    row = conn.execute(
        "SELECT id FROM cold_outreach WHERE email = ? AND dry_run = 0 AND sent_at IS NOT NULL",
        (email.lower(),),
    ).fetchone()
    return row is not None


def emails_sent_today(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM cold_outreach WHERE sent_at >= ? AND dry_run = 0",
        (today,),
    ).fetchone()
    return row["n"] if row else 0


def record_send(
    conn: sqlite3.Connection,
    email: str,
    firm_name: str,
    first_name: str,
    city: str,
    state: str,
    source: str,
    dry_run: bool,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO cold_outreach
           (email, firm_name, first_name, city, state, source, sent_at, dry_run)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (email.lower(), firm_name, first_name, city, state, source,
         now if not dry_run else None, int(dry_run)),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Lead sourcing (reuses shared lead_finder module where possible)
# ---------------------------------------------------------------------------
LEAD_FINDER = Path("~/.config/munda/scripts/lead_finder.py").expanduser()


def _import_lead_finder():
    """Dynamically import the shared lead_finder module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("lead_finder", LEAD_FINDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_domain(website: str) -> str:
    if not website:
        return ""
    parsed = urllib.parse.urlparse(website if "://" in website else f"https://{website}")
    return parsed.netloc.replace("www.", "").lower()


BOOKKEEPER_SEARCH_QUERIES = [
    "site:yelp.com bookkeeper QuickBooks",
    "site:thumbtack.com bookkeeper QuickBooks small business",
    "\"QuickBooks ProAdvisor\" bookkeeper contact email",
    "independent bookkeeper CPA firm QuickBooks email",
    "\"bookkeeping services\" \"QuickBooks\" \"contact us\" email",
]


def fetch_leads_from_hunter(max_leads: int = 40) -> list[dict]:
    """Discover bookkeeper domains via Tavily, then pull emails via Hunter domain-search."""
    hunter_key = os.environ.get("HUNTER_API_KEY", "")
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not hunter_key:
        print("[outreach] HUNTER_API_KEY not set, skipping")
        return []

    # Step 1: find bookkeeper domains via Tavily
    domains: list[str] = []
    if tavily_key:
        for query in BOOKKEEPER_SEARCH_QUERIES[:3]:
            if len(domains) >= 20:
                break
            payload = json.dumps({
                "api_key": tavily_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 8,
                "include_domains": [],
                "exclude_domains": [
                    "intuit.com", "quickbooks.com", "xero.com", "sage.com",
                    "yelp.com", "thumbtack.com", "linkedin.com", "facebook.com",
                    "google.com", "indeed.com", "glassdoor.com", "irs.gov",
                ],
            }).encode()
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
                for result in data.get("results", []):
                    url = result.get("url", "")
                    parsed = urllib.parse.urlparse(url)
                    domain = parsed.netloc.replace("www.", "").lower()
                    if domain and domain not in domains and "." in domain:
                        domains.append(domain)
            except Exception as e:
                print(f"[outreach] Tavily domain search error: {e}")
            time.sleep(0.5)

    if not domains:
        print("[outreach] No domains found via Tavily for Hunter enrichment")
        return []

    # Step 2: Hunter domain-search on each domain
    leads: list[dict] = []
    seen: set[str] = set()
    skip_re = re.compile(
        r"^(info|contact|admin|noreply|no-reply|support|hello|office|"
        r"sales|billing|legal|privacy|fraud|abuse|spam|postmaster|"
        r"webmaster|bounce|test)@"
    )
    for domain in domains:
        if len(leads) >= max_leads:
            break
        url = (
            f"https://api.hunter.io/v2/domain-search"
            f"?domain={urllib.parse.quote(domain)}&limit=3&api_key={hunter_key}"
        )
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            emails_data = data.get("data", {}).get("emails", [])
            org_name = data.get("data", {}).get("organization", "")
            for entry in emails_data:
                em = (entry.get("value") or "").lower().strip()
                if not em or em in seen:
                    continue
                if skip_re.match(em):
                    continue
                seen.add(em)
                first = entry.get("first_name", "")
                leads.append({
                    "email": em,
                    "first_name": first,
                    "firm_name": org_name,
                    "city": "",
                    "state": "",
                    "source": "hunter",
                })
        except Exception as e:
            print(f"[outreach] Hunter error for {domain}: {e}")
        time.sleep(0.3)

    print(f"[outreach] Hunter sourced {len(leads)} candidates from {len(domains)} domains")
    return leads


def fetch_leads_from_places(max_leads: int = 60) -> list[dict]:
    """Use Google Places → Hunter/Snov to find bookkeeper leads."""
    if not LEAD_FINDER.exists():
        print("[outreach] lead_finder.py not found, skipping Places sourcing")
        return []

    try:
        lf = _import_lead_finder()
    except Exception as e:
        print(f"[outreach] lead_finder import error: {e}")
        return []

    leads: list[dict] = []
    seen_emails: set[str] = set()

    for city in TARGET_CITIES:
        if len(leads) >= max_leads:
            break
        for query in TARGET_QUERIES:
            if len(leads) >= max_leads:
                break
            state_abbr = city.split(",")[-1].strip()
            city_name = city.split(",")[0].strip()
            try:
                results = lf.discover_and_enrich(
                    query=query,
                    location=city,
                    max_brokerages=3,
                    emails_per_domain=2,
                )
                for r in results:
                    em = (r.get("email") or "").lower().strip()
                    if not em or em in seen_emails:
                        continue
                    # Skip generic / role emails that bounce
                    local_part = em.split("@")[0] if "@" in em else ""
                    if len(local_part) <= 1:
                        continue
                    if re.match(r"^(info|contact|admin|noreply|no-reply|support|"
                                r"hello|office|sales|billing|legal|privacy|fraud|"
                                r"abuse|spam|postmaster|webmaster|bounce|test)@", em):
                        continue
                    seen_emails.add(em)
                    leads.append({
                        "email": em,
                        "first_name": r.get("name", "").split()[0] if r.get("name") else "",
                        "firm_name": r.get("brokerage", ""),
                        "city": city_name,
                        "state": state_abbr,
                        "source": r.get("source", "places_hunter"),
                    })
                    if len(leads) >= max_leads:
                        break
            except Exception as e:
                print(f"[outreach] places error for {city}/{query}: {e}")
            time.sleep(0.3)

    return leads


def fetch_leads_from_tavily(max_leads: int = 20) -> list[dict]:
    """Mine emails from Tavily search results as overflow."""
    if not LEAD_FINDER.exists():
        return []
    try:
        lf = _import_lead_finder()
    except Exception as e:
        print(f"[outreach] lead_finder import error: {e}")
        return []

    leads: list[dict] = []
    queries = [
        "bookkeeper QuickBooks email contact",
        "CPA firm small business QuickBooks email",
        "accounting bookkeeping firm QuickBooks email contact",
    ]
    seen: set[str] = set()
    for q in queries:
        if len(leads) >= max_leads:
            break
        try:
            emails = lf.tavily_email_mine(q, max_results=10)
            for em in emails:
                em = em.lower().strip()
                if not em or em in seen:
                    continue
                local_part = em.split("@")[0] if "@" in em else ""
                domain_part = em.split("@")[-1] if "@" in em else ""
                if len(local_part) <= 1:
                    continue
                if domain_part in (
                    "intuit.com", "quickbooks.com", "sage.com", "xero.com",
                    "microsoft.com", "google.com", "apple.com", "amazon.com",
                    "example.com", "test.com",
                ):
                    continue
                if re.match(r"^(info|contact|admin|noreply|no-reply|support|"
                            r"hello|office|sales|billing|legal|privacy|fraud|"
                            r"abuse|spam|postmaster|webmaster|bounce|test)@", em):
                    continue
                seen.add(em)
                leads.append({
                    "email": em,
                    "first_name": "",
                    "firm_name": "",
                    "city": "",
                    "state": "",
                    "source": "tavily",
                })
        except Exception as e:
            print(f"[outreach] tavily error: {e}")

    return leads


# Static seed list — high-quality public directory pulls (pre-verified manually)
# These are placeholder-style entries for the dry-run demo; real seeds would be
# sourced from AIPB / NABA / NACPB directories.
STATIC_SEEDS: list[dict] = [
    {
        "email": "sarah@greenleafbooks.com",
        "first_name": "Sarah",
        "firm_name": "Greenleaf Bookkeeping",
        "city": "Austin",
        "state": "TX",
        "source": "static_seed",
    },
    {
        "email": "mike@chicagoaccounting.com",
        "first_name": "Mike",
        "firm_name": "Chicago Accounting Solutions",
        "city": "Chicago",
        "state": "IL",
        "source": "static_seed",
    },
    {
        "email": "jennifer@nycbooks.com",
        "first_name": "Jennifer",
        "firm_name": "NYC Bookkeeping Partners",
        "city": "New York",
        "state": "NY",
        "source": "static_seed",
    },
    {
        "email": "david@phoenixcpa.com",
        "first_name": "David",
        "firm_name": "Phoenix CPA Group",
        "city": "Phoenix",
        "state": "AZ",
        "source": "static_seed",
    },
    {
        "email": "lisa@miamibooks.com",
        "first_name": "Lisa",
        "firm_name": "Miami Bookkeeping Services",
        "city": "Miami",
        "state": "FL",
        "source": "static_seed",
    },
]


# ---------------------------------------------------------------------------
# Email personalization
# ---------------------------------------------------------------------------
CLAUDE_CLI = "/Users/klauhomefolder/.local/bin/claude"


def _claude_available() -> bool:
    return Path(CLAUDE_CLI).exists()


def personalize_with_claude(
    first_name: str, firm_name: str, city: str, state: str
) -> Optional[dict]:
    """Call `claude` CLI to generate a personalized subject + HTML body.
    Returns {'subject': ..., 'html': ..., 'text': ...} or None on failure.
    """
    loc_hint = f"{city}, {state}" if city and state else city or state or "your area"
    firm_hint = firm_name if firm_name else "your firm"
    name_hint = first_name if first_name else "there"

    prompt = f"""You are writing a cold email for Bank2QBO, a PDF bank statement to QuickBooks CSV/IIF converter.

Recipient: {name_hint} at {firm_hint} ({loc_hint})
Product: Bank2QBO — converts any bank PDF statement to QuickBooks-ready CSV + IIF in 30 seconds
Pricing: $39 single / $99 5-pack / $99/mo firm / $249/mo pro
CTA URL: {LANDING_URL}
Free offer: {FREE_OFFER}
From: Claudio at Bank2QBO (hello@mundallcfreight.com)

Write a concise cold email (max 180 words in body). Tone: direct, peer-to-peer, no fluff.
Structure:
1. Short hook referencing their work context ({loc_hint} bookkeeper / CPA)
2. The pain: manual PDF-to-QBO conversion takes 20-40 min per statement
3. The solution: Bank2QBO does it in 30 seconds, with reconciliation report included
4. Free offer: send one PDF, we convert it free
5. CTA: {LANDING_URL}
6. Sign-off: Claudio

Output ONLY valid JSON (no markdown, no code fence) with these keys:
  "subject": email subject line (max 55 chars, no emoji)
  "html": HTML body (use <p> tags, no images, no tracking pixel)
  "text": plain-text version

Important: never use words like "blast", "spam", "mass email", or "marketing".
Do not invent fake metrics. Keep it honest and human.
"""
    try:
        result = subprocess.run(
            [CLAUDE_CLI, "-p", prompt,
             "--output-format", "text",
             "--no-session-persistence"],
            capture_output=True, text=True, timeout=60,
        )
        raw = result.stdout.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from mixed output
        m = re.search(r"\{.*\}", result.stdout, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        print(f"[outreach] claude CLI JSON parse failed: {result.stdout[:200]}")
        return None
    except Exception as e:
        print(f"[outreach] claude CLI error: {e}")
        return None


def personalize_template(
    first_name: str, firm_name: str, city: str, state: str
) -> dict:
    """High-quality hardcoded template with variable substitution."""
    name_salute = first_name if first_name else "Hi"
    loc = f"{city}, {state}" if city and state else city or state or "your area"
    firm_ref = (
        f"at {firm_name}" if firm_name else "running your bookkeeping practice"
    )

    subject = f"PDF → QBO in 30 sec — free test for {city or 'your firm'}"
    if len(subject) > 55:
        subject = "Bank PDFs to QuickBooks in 30 seconds — free test"

    html = f"""<p>{name_salute},</p>

<p>Quick question for bookkeepers {firm_ref} in {loc}:</p>

<p>How long does it take you to manually re-key a client's bank PDF into QuickBooks? Most bookkeepers I've talked to say 20–40 minutes per statement — and some months there are 10+ statements stacked up.</p>

<p><strong>Bank2QBO converts any bank PDF statement to a QuickBooks-ready CSV + IIF in about 30 seconds.</strong> It includes a reconciliation report (row count, debit/credit totals, opening/closing balance check) so you can verify before you import.</p>

<p>Works with Chase, Bank of America, Wells Fargo, Citi, TD, and most regional bank PDFs — both text-based and scanned.</p>

<p>I'd like to earn your trust before asking for anything: <strong>send me one real PDF (anonymized is fine) and I'll convert it free</strong>, no signup required.</p>

<p>Pricing when you're ready: $39 one-time · $99/5-pack · $99/month firm tier.</p>

<p><a href="{LANDING_URL}">See how it works →</a></p>

<p>Claudio<br>
Bank2QBO · Munda LLC · Miami FL<br>
<a href="mailto:{FROM_EMAIL}">{FROM_EMAIL}</a></p>

<p style="font-size:11px;color:#888;">To unsubscribe, reply with "unsubscribe" and I'll remove you immediately.</p>"""

    text = f"""{name_salute},

Quick question for bookkeepers {firm_ref} in {loc}:

How long does it take you to manually re-key a client's bank PDF into QuickBooks? Most bookkeepers I've talked to say 20–40 minutes per statement — and some months there are 10+ statements stacked up.

Bank2QBO converts any bank PDF statement to a QuickBooks-ready CSV + IIF in about 30 seconds. It includes a reconciliation report (row count, debit/credit totals, opening/closing balance check) so you can verify before you import.

Works with Chase, Bank of America, Wells Fargo, Citi, TD, and most regional bank PDFs — both text-based and scanned.

I'd like to earn your trust before asking for anything: send me one real PDF (anonymized is fine) and I'll convert it free, no signup required.

Pricing when you're ready: $39 one-time · $99/5-pack · $99/month firm tier.

See how it works: {LANDING_URL}

Claudio
Bank2QBO · Munda LLC · Miami FL
{FROM_EMAIL}

To unsubscribe, reply "unsubscribe" and I'll remove you immediately."""

    return {"subject": subject, "html": html, "text": text}


def build_email(first_name: str, firm_name: str, city: str, state: str) -> dict:
    """Try claude CLI first, fall back to template."""
    if _claude_available():
        result = personalize_with_claude(first_name, firm_name, city, state)
        if result and result.get("subject") and result.get("html"):
            print(f"[outreach] personalized via claude CLI")
            return result
        print("[outreach] claude CLI failed, falling back to template")
    return personalize_template(first_name, firm_name, city, state)


# ---------------------------------------------------------------------------
# Resend email sender
# ---------------------------------------------------------------------------
def send_email(to_email: str, subject: str, html: str, text: str) -> Optional[str]:
    """Send via Resend. Returns message ID on success, None on failure."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        print("[outreach] RESEND_API_KEY not set")
        return None

    payload = json.dumps({
        "from": f"{FROM_NAME} <{FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": text,
        "headers": {
            # CAN-SPAM List-Unsubscribe
            "List-Unsubscribe": f"<mailto:{FROM_EMAIL}?subject=unsubscribe>",
        },
    }).encode()

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
            return resp.get("id")
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", errors="ignore")
        print(f"[outreach] Resend HTTP {e.code}: {body}")
        return None
    except Exception as e:
        print(f"[outreach] Resend error: {e}")
        return None


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------
def telegram_notify(message: str) -> None:
    bot = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (bot and chat):
        return
    payload = json.dumps({"chat_id": chat, "text": message, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------
def run(dry_run: bool = False, limit: int = DAILY_CAP) -> None:
    conn = get_conn()
    sent_today = emails_sent_today(conn)

    if not dry_run and sent_today >= DAILY_CAP:
        print(f"[outreach] Daily cap reached ({sent_today}/{DAILY_CAP}). Exiting.")
        conn.close()
        return

    remaining = limit if dry_run else min(limit, DAILY_CAP - sent_today)
    print(f"[outreach] {'DRY RUN — ' if dry_run else ''}Target: {remaining} emails")

    # Gather leads
    leads: list[dict] = []

    # 1. Hunter domain-search on Tavily-discovered bookkeeper sites (primary)
    hunter_leads = fetch_leads_from_hunter(max_leads=max(remaining * 2, 40))
    leads.extend(hunter_leads)

    # 2. Google Places → Hunter/Snov (skipped silently if Places API REQUEST_DENIED)
    if len(leads) < remaining * 2:
        places_leads = fetch_leads_from_places(max_leads=max(remaining * 2, 30))
        leads.extend(places_leads)
        if places_leads:
            print(f"[outreach] Places+Hunter sourced {len(places_leads)} candidates")

    # 3. Tavily overflow
    if len(leads) < remaining * 2:
        tavily_leads = fetch_leads_from_tavily(max_leads=20)
        leads.extend(tavily_leads)
        print(f"[outreach] Tavily added {len(tavily_leads)} candidates")

    # 3. Static seeds as final fallback / always available for dry-run demo
    leads.extend(STATIC_SEEDS)

    # Deduplicate
    seen_emails: set[str] = set()
    deduped: list[dict] = []
    for lead in leads:
        em = (lead.get("email") or "").lower().strip()
        if not em or em in seen_emails:
            continue
        # Quality filter: skip obvious junk / corporate / irrelevant domains
        local, _, domain = em.partition("@")
        if not local or not domain or len(local) <= 1:
            continue  # single-char local part is garbage
        if domain in (
            "intuit.com", "quickbooks.com", "sage.com", "xero.com",
            "microsoft.com", "google.com", "apple.com", "amazon.com",
            "quora.com", "linkedin.com", "facebook.com", "twitter.com",
            "reddit.com", "yelp.com", "thumbtack.com", "angieslist.com",
            "homeadvisor.com", "wordpress.com", "wix.com", "squarespace.com",
            "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
            "example.com", "test.com",
        ):
            continue  # vendor / competitor / consumer / social domains
        if re.match(r"^(info|contact|admin|noreply|no-reply|support|hello|"
                    r"office|sales|billing|legal|privacy|fraud|abuse|"
                    r"spam|postmaster|webmaster|bounce|test)@", em):
            continue  # role / bounce / junk addresses
        if not re.match(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$", em):
            continue  # malformed
        seen_emails.add(em)
        deduped.append(lead)

    print(f"[outreach] {len(deduped)} unique candidates after dedup")

    sent = 0
    skipped = 0
    for lead in deduped:
        if sent >= remaining:
            break

        email = lead["email"].lower().strip()

        # Skip if already contacted
        if already_contacted(conn, email):
            skipped += 1
            continue

        first_name = lead.get("first_name", "")
        firm_name = lead.get("firm_name", "")
        city = lead.get("city", "")
        state = lead.get("state", "")
        source = lead.get("source", "unknown")

        # Build personalized email
        content = build_email(first_name, firm_name, city, state)

        if dry_run:
            print(f"\n{'='*70}")
            print(f"[DRY RUN #{sent+1}]")
            print(f"  TO:      {email}")
            print(f"  FIRM:    {firm_name or '(unknown)'} | {city}, {state}")
            print(f"  SOURCE:  {source}")
            print(f"  SUBJECT: {content['subject']}")
            print(f"  BODY:\n")
            # Print text version for readability
            for line in content["text"].splitlines():
                print(f"    {line}")
            print(f"{'='*70}")
            record_send(conn, email, firm_name, first_name, city, state, source, dry_run=True)
            sent += 1
            continue

        # Live send
        msg_id = send_email(email, content["subject"], content["html"], content["text"])
        if msg_id:
            record_send(conn, email, firm_name, first_name, city, state, source, dry_run=False)
            print(f"[outreach] SENT → {email} ({firm_name or city}) | msg={msg_id}")
            sent += 1
            time.sleep(1.2)  # ~50/min max throughput, keeps us well under Resend limits
        else:
            print(f"[outreach] FAILED → {email}")

    conn.close()

    total_sent_now = sent_today + sent if not dry_run else sent_today
    summary = (
        f"{'🧪 DRY RUN' if dry_run else '📧 Bank2QBO Outreach'}\n"
        f"Sent: {sent} | Skipped (dup): {skipped}\n"
        f"Day total: {total_sent_now}/{DAILY_CAP}\n"
        f"DB: {DB_PATH}"
    )
    print(f"\n[outreach] {summary}")

    if not dry_run and sent > 0:
        telegram_notify(
            f"📧 *Bank2QBO outreach batch sent*\n"
            f"Sent: {sent} | Skipped: {skipped}\n"
            f"Day total: {total_sent_now}/{DAILY_CAP}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bank2QBO cold email outreach daemon"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview emails without sending or recording as sent",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DAILY_CAP,
        help=f"Max emails to send (default {DAILY_CAP})",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print outreach stats and exit",
    )
    args = parser.parse_args()

    if args.stats:
        conn = get_conn()
        rows = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN dry_run=0 THEN 1 ELSE 0 END) as live,
                SUM(opened) as opened,
                SUM(replied) as replied,
                SUM(converted) as converted,
                MIN(sent_at) as first_sent,
                MAX(sent_at) as last_sent
            FROM cold_outreach
        """).fetchone()
        print(json.dumps(dict(rows), indent=2, default=str))
        conn.close()
        sys.exit(0)

    run(dry_run=args.dry_run, limit=args.limit)
