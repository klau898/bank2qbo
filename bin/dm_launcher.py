#!/usr/bin/env python3
"""
DM Launcher — cycles through targets, loads personalized DM into clipboard,
opens LinkedIn profile in Brave, and logs each send.

Usage: python3 dm_launcher.py [--target N]
  --target N  Start at target number N (1-indexed). Default: 1
"""

import subprocess, sys, time, argparse, os

# Personalized DM targets
TARGETS = [
    {
        "name": "Jennifer",
        "full": "Jennifer Springer",
        "title": "QB Advanced ProAdvisor",
        "company": "My Bookkeeper Inc",
        "url": "https://www.linkedin.com/in/jenniferspringerfl/",
        "note": "Jupiter FL — use Florida angle",
        "dm": """Hey Jennifer —

Fellow South Florida connection here. Random question: when a client sends you a PDF statement from one of the smaller credit unions down here (there are a lot), what's your current workflow for getting it into QBO?

Retype it manually, run it through a converter, send to a VA?

Reason I ask — I'm building something specifically for this and want to understand the actual pain before I assume. No pitch, just curious how you handle it today.

— Klau (Cordoba) / Munda LLC, Miami""",
    },
    {
        "name": "Lori",
        "full": "Lori Cherry",
        "title": "QB Online Certified ProAdvisor",
        "company": "Cherry Bookkeeping Inc",
        "url": "https://www.linkedin.com/in/lori-cherry-31206b43/",
        "note": "Boynton Beach FL — use Florida angle",
        "dm": """Hey Lori —

Fellow South Florida connection here. Random question: when a client sends you a PDF bank statement from a smaller credit union or community bank — no CSV, no bank feed — what's your workflow to get it into QBO?

Reason I ask — I'm building something specifically for this pain point and want to understand how real bookkeepers actually handle it today, before I assume anything.

No pitch. Just curious.

— Klau (Cordoba) / Munda LLC, Miami""",
    },
    {
        "name": "Jerome",
        "full": "Jerome Peterson",
        "title": "QBO ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/despeterson/",
        "note": "Sanford FL",
        "dm": """Hey Jerome —

Random question: when a client sends you a PDF bank statement from a small credit union with no CSV export and no bank feed, what's your current workflow? Manual retype, some converter, VA?

Building something for this specific pain point and want to understand the real workflow before I build. No pitch, just research.

— Klau / Munda LLC""",
    },
    {
        "name": "Leo",
        "full": "Leo Sheridan",
        "title": "QB Online ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/leodanielsheridaniii/",
        "note": "Tarpon Springs FL",
        "dm": """Hey Leo —

Quick question for you: when a client sends a PDF bank statement from one of those community banks or credit unions that have no CSV export — what's your go-to workflow for getting it into QuickBooks?

I'm a builder (not a bookkeeper) doing research before building a tool for this. No pitch. Genuinely curious about the real-world workflow.

— Klau / Munda LLC, Miami""",
    },
    {
        "name": "Amber",
        "full": "Amber Unsworth",
        "title": "Certified Mobile QB ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/quickbooksproadvisor/",
        "note": "Naples / SW Florida",
        "dm": """Hey Amber —

Fellow Florida connection here. Quick question: when a client hands you a PDF statement from a small credit union — no CSV, no feed — what's your current process to get it into QBO?

Building a pay-per-use solution for exactly this problem and want to make sure I understand the real pain first. No pitch, genuinely researching.

— Klau / Munda LLC, Miami""",
    },
    {
        "name": "Molly",
        "full": "Molly McNally Roberts",
        "title": "Owner, Molly Keeps Books",
        "company": "Molly Keeps Books",
        "url": "https://www.linkedin.com/in/mollykeepsbooks/",
        "note": "National — small biz focus",
        "dm": """Hey Molly —

Random question: when a client sends you a PDF bank statement from a smaller bank with no CSV export, what's your workflow to get it into QBO? Manual retype, converter tool, something else?

I'm building a pay-per-use concierge for exactly this — $39/statement, 24h turnaround, human-verified. Doing research before I launch and want to hear how real bookkeepers handle it today.

No pitch. Just curious about the real workflow.

— Klau / Munda LLC""",
    },
    {
        "name": "Alison",
        "full": "Alison Schiewe",
        "title": "QB ProAdvisor Bookkeeping Services",
        "company": "Schiewe Bookkeeping",
        "url": "https://www.linkedin.com/in/alison-schiewe-107661112/",
        "note": "National — small biz",
        "dm": """Hey Alison —

Quick research question: when a client sends a PDF bank statement from a small credit union or community bank (no CSV, no direct feed), how do you get it into QuickBooks? Manual retype? A converter? VA?

Building a tool for this specific problem and want to understand the real-world workflow first. No pitch.

— Klau / Munda LLC""",
    },
    {
        "name": "Beverly",
        "full": "Beverly Geise",
        "title": "Owner, BDG Bookkeeping",
        "company": "BDG Bookkeeping",
        "url": "https://www.linkedin.com/in/beverly-geise/",
        "note": "National — solo bookkeeper",
        "dm": """Hey Beverly —

Random question: when a client sends you a PDF statement from a smaller bank or credit union (no CSV, no bank feed), what's your current process for getting it into QuickBooks?

Building a pay-per-use service for exactly this problem — $39/statement, human-verified, 24h turnaround. Doing research before I launch. No pitch, just want to understand the real workflow.

— Klau / Munda LLC""",
    },
    {
        "name": "Karen",
        "full": "Karen Bowen",
        "title": "QB ProAdvisor, SurePoint",
        "company": "SurePoint",
        "url": "https://www.linkedin.com/in/karenbookkeeping/",
        "note": "National — QB ProAdvisor",
        "dm": """Hey Karen —

Quick research question: when a client hands you a PDF bank statement with no CSV export option, what's your workflow to get it into QBO? Manual entry, some converter tool, or do you send it out?

I'm building a concierge service for this specific problem. Trying to understand how working bookkeepers actually handle it today before I build. No pitch.

— Klau / Munda LLC""",
    },
    {
        "name": "Cheryl",
        "full": "Cheryl Clem",
        "title": "Expert Bookkeeper / QBO ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/cheryl-clem-02ba83308/",
        "note": "National — solo QBO ProAdvisor",
        "dm": """Hey Cheryl —

Random bookkeeper question: when a client sends you a PDF bank statement from a credit union or small bank (no CSV, no feed), how do you handle getting those transactions into QuickBooks?

I'm researching this exact pain point before building a solution. No pitch — genuinely trying to understand the real-world workflow.

— Klau / Munda LLC""",
    },
    {
        "name": "Carol",
        "full": "Carol Leavitt",
        "title": "Your QuickBooks Helper",
        "company": "Your QuickBooks Helper",
        "url": "https://www.linkedin.com/in/qbproadvisorcarolleavitt/",
        "note": "National — QBO specialist",
        "dm": """Hey Carol —

Quick question for a fellow QBO person: when a client sends you a PDF bank statement with no CSV export (small credit union, community bank), what's your process for getting it into QuickBooks?

I'm building a pay-per-use tool for this specific problem and doing research first. No pitch, just curious about the real workflow.

— Klau / Munda LLC""",
    },
    {
        "name": "Christy",
        "full": "Christy Dupree",
        "title": "Virtual Bookkeeper / QB ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/christy-dupree-04431289/",
        "note": "National — virtual bookkeeper",
        "dm": """Hey Christy —

Random question: when a client sends you a PDF bank statement from a smaller bank with no CSV or bank feed available, what's your go-to for getting those transactions into QBO?

Building something specifically for this problem. No pitch — doing research before I build anything. How does the workflow actually look in practice?

— Klau / Munda LLC""",
    },
    {
        "name": "Allison",
        "full": "Allison Wolf",
        "title": "Owner, All About Businesses",
        "company": "All About Businesses",
        "url": "https://www.linkedin.com/in/allaboutbusinesses/",
        "note": "National — small biz bookkeeper",
        "dm": """Hey Allison —

Quick research question: when a client sends you a PDF bank statement from a community bank or credit union (no CSV, no feed), how do you get it into QuickBooks? Manual retype, a converter, or something else?

I'm building a $39/statement concierge for this and want to understand the real-world workflow first. No pitch.

— Klau / Munda LLC""",
    },
    # ── DAY 7–10 TARGETS ──────────────────────────────────────────────
    {
        "name": "Brenda",
        "full": "Brenda Keeton",
        "title": "QB Advanced ProAdvisor",
        "company": "Balanced Books by BK",
        "url": "https://www.linkedin.com/in/brenda-keeton-b7aab8183/",
        "note": "San Antonio TX",
        "dm": """Hey Brenda —

Random question: when a client in Texas sends you a PDF bank statement from a smaller bank or credit union (no CSV, no bank feed), how do you get those transactions into QuickBooks?

Building a $39/statement concierge for exactly this problem — human-verified, 24h turnaround. Doing research before launch. No pitch, just want to understand the real workflow.

— Klau / Munda LLC, Miami""",
    },
    {
        "name": "Monica",
        "full": "Monica Davis",
        "title": "Founder, Davis Bookkeeping Services",
        "company": "Davis Bookkeeping Services",
        "url": "https://www.linkedin.com/in/monica-davis-bookkeeping/",
        "note": "Virtual — national",
        "dm": """Hey Monica —

Quick research question: when a client sends you a PDF bank statement from a small bank or credit union with no CSV export, what's your current process for getting it into QuickBooks?

Building a pay-per-use tool for this specific pain point. No pitch — genuinely want to understand how working virtual bookkeepers handle it today.

— Klau / Munda LLC""",
    },
    {
        "name": "Mary Ann",
        "full": "Mary Ann Fortin",
        "title": "Certified Bookkeeper & QB ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/mary-ann-fortin/",
        "note": "San Diego CA",
        "dm": """Hey Mary Ann —

Random bookkeeper question: when a client sends you a PDF bank statement from a credit union or small bank (no CSV, no bank feed), what's your workflow for getting it into QBO?

I'm building a concierge service for this specific problem — $39/statement, human-verified. Doing research before launch. No pitch.

— Klau / Munda LLC""",
    },
    {
        "name": "Robin",
        "full": "Robin Wakeland Farmer",
        "title": "QB & Xero Certified",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/robin-wakeland-farmer/",
        "note": "National",
        "dm": """Hey Robin —

Quick question: when a client sends you a PDF bank statement from a smaller bank with no CSV export option, how do you handle getting those transactions into QuickBooks?

Building a $39/statement concierge for this problem and want to understand the real-world workflow first. No pitch.

— Klau / Munda LLC""",
    },
    {
        "name": "Caitlin",
        "full": "Caitlin Burton",
        "title": "Owner, Burton Bookkeeping",
        "company": "Burton Bookkeeping",
        "url": "https://www.linkedin.com/in/caitlin-burton-987b40155/",
        "note": "National — firm owner",
        "dm": """Hey Caitlin —

Random question: when a client sends you a PDF bank statement from a community bank or credit union (no CSV, no feed), what's your current process for getting it into QuickBooks?

I'm building a concierge service for this exact problem and want to understand how it actually works in practice before I build. No pitch.

— Klau / Munda LLC""",
    },
    {
        "name": "Pamela",
        "full": "Pamela Smith",
        "title": "QB ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/pamelaquickbooksguru/",
        "note": "National — QB specialist",
        "dm": """Hey Pamela —

Quick question for a QB expert: when a client hands you a PDF statement from a smaller bank with no CSV export, what's your go-to process for getting those transactions into QuickBooks?

Building something specifically for this problem. No pitch — just doing research.

— Klau / Munda LLC""",
    },
    {
        "name": "Kathy",
        "full": "Kathy Hahn",
        "title": "QB Advanced ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/qbkathy/",
        "note": "National — QB Advanced",
        "dm": """Hey Kathy —

Random QB question: when a client sends you a PDF bank statement from a small credit union or community bank (no CSV, no bank feed), how do you currently get it into QuickBooks?

I'm building a $39/statement concierge for this specific pain point. No pitch — doing research on how working ProAdvisors handle it today.

— Klau / Munda LLC""",
    },
    {
        "name": "Ann",
        "full": "Ann McPherson",
        "title": "Certified Bookkeeper, QBO ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/joyinbookkeeping/",
        "note": "National",
        "dm": """Hey Ann —

Quick research question: when a client sends you a PDF bank statement from a smaller bank or credit union (no CSV, no feed), what's your process for getting those transactions into QuickBooks?

Building a pay-per-use tool for this problem. No pitch — genuinely curious about the real-world workflow.

— Klau / Munda LLC""",
    },
    {
        "name": "Charisse",
        "full": "Charisse Kelley",
        "title": "Virtual Bookkeeper, QBO ProAdvisor",
        "company": "Self-employed",
        "url": "https://www.linkedin.com/in/charisse-kelley-08b5791b5/",
        "note": "Virtual — national",
        "dm": """Hey Charisse —

Random question: when a client sends you a PDF bank statement from a small bank with no CSV export, how do you get it into QBO? Manual retype, some converter, or something else?

Building a $39/statement concierge for this and want to understand the real-world workflow. No pitch.

— Klau / Munda LLC""",
    },
    {
        "name": "Noemi",
        "full": "Noemi Gonzalez",
        "title": "Owner, Palma Bookkeeping",
        "company": "Palma Bookkeeping",
        "url": "https://www.linkedin.com/in/noemi-gonzalez-09397528/",
        "note": "Virtual — bilingual angle available",
        "dm": """Hey Noemi —

Quick question: when a client sends you a PDF bank statement from a smaller bank or credit union (no CSV, no bank feed), what's your current workflow to get it into QuickBooks?

I'm building a concierge for this exact problem — $39/statement, human-verified, 24h turnaround. Doing research before launch. No pitch.

— Klau / Munda LLC, Miami""",
    },
    {
        "name": "Jose",
        "full": "Jose Espinosa",
        "title": "Certified QB ProAdvisor",
        "company": "QuickBooks ProAdvisors USA LLC",
        "url": "https://www.linkedin.com/in/jose-espinosa-5154119a/",
        "note": "National — bilingual angle available",
        "dm": """Hey Jose —

Random question: when a client sends a PDF bank statement from a small credit union or community bank (no CSV, no bank feed), what's your process for getting it into QuickBooks?

I'm building a $39/statement service for this specific problem. Doing research before launch. No pitch — just want to understand how it actually works in practice.

— Klau / Munda LLC""",
    },
]


def copy_to_clipboard(text):
    process = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def open_url_in_brave(url):
    subprocess.run(["open", "-a", "Brave Browser", url], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=1, help="Start at target N (1-indexed)")
    args = parser.parse_args()

    start = args.target - 1
    targets = TARGETS[start:]

    print(f"\n{'='*60}")
    print(f"BANK2QBO DM LAUNCHER — {len(TARGETS)} targets total")
    print(f"Starting at target #{args.target}: {TARGETS[start]['full']}")
    print(f"{'='*60}\n")

    for i, t in enumerate(targets, start=args.target):
        print(f"\n--- TARGET {i}/{len(TARGETS)}: {t['full']} ---")
        print(f"Title:   {t['title']}")
        print(f"Company: {t['company']}")
        print(f"URL:     {t['url']}")
        print(f"Note:    {t['note']}")
        print()
        print("DM LOADED TO CLIPBOARD:")
        print("-" * 40)
        print(t["dm"])
        print("-" * 40)

        # Load DM into clipboard
        copy_to_clipboard(t["dm"])
        print("\n✓ DM copied to clipboard")

        # Open LinkedIn profile in Brave
        open_url_in_brave(t["url"])
        print(f"✓ Opening {t['url']} in Brave")
        print()
        print("YOUR STEPS:")
        print("  1. Wait for profile to load in Brave")
        print("  2. Click 'Message' button on their profile")
        print("  3. Click in message box → Cmd+V to paste")
        print("  4. Review → press Enter or click Send")
        print()

        # Log the DM
        log_cmd = [
            "python3",
            os.path.expanduser("~/Projects/pdftoqbo/bin/log_dm.py"),
            "dm",
            t["full"],
            "--title", t["title"],
            "--company", t["company"],
            "--url", t["url"],
        ]

        if i < len(TARGETS):
            resp = input(f"Sent? (y=yes+next / s=skip / q=quit): ").strip().lower()
        else:
            resp = input(f"Sent? (y=yes+done / s=skip / q=quit): ").strip().lower()

        if resp == "q":
            print("\nExiting. Run with --target to resume.")
            break
        elif resp == "y":
            subprocess.run(log_cmd)
            print(f"✓ Logged to CRM")
        elif resp == "s":
            print(f"Skipped {t['full']}")

        if i < len(TARGETS) and resp != "q":
            print(f"\nReady for target {i+1}? Press Enter...")
            input()

    print("\n" + "="*60)
    print("Session complete. Running stats...")
    subprocess.run(["python3", os.path.expanduser("~/Projects/pdftoqbo/bin/log_dm.py"), "stats"])


if __name__ == "__main__":
    main()
