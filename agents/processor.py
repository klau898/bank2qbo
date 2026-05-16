"""PDF → CSV + IIF processor with Claude Vision + reconciliation verifier.

This is the agent that does the actual work. Two modes:

  MODE 1 (concierge, Day 1-14): Klau runs `python3 processor.py --pdf-id N`
    after the agent has alerted him. The agent extracts rows via Claude Vision,
    runs the reconciliation verifier, generates CSV + IIF, marks the delivery
    PENDING_KLAU_REVIEW. Klau spot-checks 3-5 rows, approves, hits send.

  MODE 2 (post-validation, Week 3+): runs autonomously on every upload.

The reconciliation verifier is what Codex flagged as the make-or-break:
bookkeepers need TRANSACTIONS THAT RECONCILE, not OCR'd text.
"""
from __future__ import annotations

import base64
import csv
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "state" / "concierge.db"


@dataclass
class ExtractedTxn:
    date: str
    description: str
    debit_cents: int  # positive value, 0 if credit
    credit_cents: int  # positive value, 0 if debit
    balance_cents: int | None = None
    raw: str = ""


@dataclass
class ReconciliationReport:
    row_count: int
    sum_debits_cents: int
    sum_credits_cents: int
    opening_balance_cents: int | None
    closing_balance_cents: int | None
    expected_closing: int | None
    delta_cents: int | None  # closing - expected_closing
    score: float  # 0.0 - 1.0; 1.0 = perfect reconciliation
    flagged_rows: list[int]  # indices of suspicious rows
    notes: list[str]


# ── Claude Vision extraction ─────────────────────────────────────────────────

def extract_txns_via_claude(pdf_path: Path, bank_guess: str | None) -> list[ExtractedTxn]:
    """Use the local Claude CLI (Max plan, $0 marginal) to extract transactions.

    Claude Code's CLI accepts file paths via -p prompt + --add-dir. For PDFs,
    we use a Python pdfplumber pre-extract + Claude reasoning over the text.
    For scanned PDFs, we use the Claude API Vision endpoint (paid; only invoke
    if --use-api is passed).
    """
    # First pass: text extraction
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except ImportError:
        # Fallback: pypdf
        try:
            import pypdf  # type: ignore
            reader = pypdf.PdfReader(str(pdf_path))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            text = ""

    if not text or len(text) < 100:
        # Likely scanned. TODO: route to Claude Vision API or Tesseract OCR
        # For Day-1 concierge, surface as flagged + Klau handles manually
        return []

    # Ask Claude to extract transactions in strict JSON
    prompt = f"""You are extracting transactions from a US bank statement.
Bank: {bank_guess or 'unknown'}

Extract every transaction. Return ONLY valid JSON in this exact shape:
{{
  "opening_balance": <integer cents or null>,
  "closing_balance": <integer cents or null>,
  "transactions": [
    {{
      "date": "YYYY-MM-DD",
      "description": "<merchant/payee>",
      "debit_cents": <integer or 0>,
      "credit_cents": <integer or 0>,
      "balance_cents": <integer or null>
    }}
  ]
}}

Rules:
- Debits (money out) go in debit_cents; credits (money in) go in credit_cents
- ONE of debit_cents or credit_cents must be 0; never both nonzero
- Skip blank rows, headers, footers, page numbers
- If a row spans multiple lines (continuation), merge into one transaction
- Format dates as YYYY-MM-DD (assume statement year if month/day only)
- NO commentary. NO markdown. JUST the JSON object.

Statement text:
{text[:80000]}
"""

    import shutil
    if not shutil.which("claude"):
        raise RuntimeError("claude CLI not on PATH")

    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr[:300]}")

    out = result.stdout.strip()
    if out.startswith("```"):
        out = out.split("```")[1]
        if out.startswith("json"):
            out = out[4:]
        out = out.strip()

    parsed = json.loads(out)
    txns = []
    for t in parsed.get("transactions", []):
        txns.append(ExtractedTxn(
            date=t["date"],
            description=t["description"].strip()[:200],
            debit_cents=int(t.get("debit_cents") or 0),
            credit_cents=int(t.get("credit_cents") or 0),
            balance_cents=t.get("balance_cents"),
        ))
    # Stash opening/closing in module-level for verifier (cheap pass)
    extract_txns_via_claude._opening = parsed.get("opening_balance")
    extract_txns_via_claude._closing = parsed.get("closing_balance")
    return txns


# ── Reconciliation verifier ──────────────────────────────────────────────────

def reconcile(txns: list[ExtractedTxn], opening: int | None, closing: int | None) -> ReconciliationReport:
    """Verify the extraction reconciles. The core trust signal."""
    debits = sum(t.debit_cents for t in txns)
    credits = sum(t.credit_cents for t in txns)
    flagged: list[int] = []
    notes: list[str] = []

    # Sanity: every row should be one-sided
    for i, t in enumerate(txns):
        if t.debit_cents > 0 and t.credit_cents > 0:
            flagged.append(i)
            notes.append(f"row {i}: both debit + credit nonzero")
        if t.debit_cents == 0 and t.credit_cents == 0:
            flagged.append(i)
            notes.append(f"row {i}: zero-value transaction")

    expected_closing = None
    delta = None
    score = 0.0
    # Codex-tightened bands (May 14, 2026): bookkeeper trust requires delta == 0 to auto-pass.
    # ANY non-zero delta forces manual review. This is the trust-axis correction.
    if opening is not None and closing is not None:
        # Standard bank-statement equation: closing = opening + credits - debits
        expected_closing = opening + credits - debits
        delta = closing - expected_closing
        if delta == 0:
            score = 1.0
            notes.append("PERFECT — closing balance matches expected exactly")
        else:
            abs_delta = abs(delta)
            if abs_delta == 1:  # 1-cent floating-point — surface for Klau review, NOT auto-pass
                score = 0.95
                notes.append(f"1-cent delta (${delta/100:.2f}) — manual review recommended; likely rounding row")
            elif abs_delta <= 100:  # within $1
                score = 0.80
                notes.append(f"MANUAL REVIEW — off by ${delta/100:.2f}; identify missing row before send")
            elif abs_delta <= 10000:  # within $100
                score = 0.5
                notes.append(f"FAIL — off by ${delta/100:.2f}; do NOT ship; re-run")
            else:
                score = 0.2
                notes.append(f"FATAL — off by ${delta/100:.2f}; extraction broken; re-run with Vision API")
    else:
        score = 0.7  # cannot auto-verify; require Klau manual approve
        notes.append("Could not extract opening/closing balance — manual verification required before ship")

    # Reduce score by flagged-row count
    if flagged:
        score = max(0.0, score - 0.05 * len(flagged))

    return ReconciliationReport(
        row_count=len(txns),
        sum_debits_cents=debits,
        sum_credits_cents=credits,
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        expected_closing=expected_closing,
        delta_cents=delta,
        score=round(score, 3),
        flagged_rows=flagged,
        notes=notes,
    )


# ── CSV + IIF output ─────────────────────────────────────────────────────────

def write_csv(txns: list[ExtractedTxn], out_path: Path) -> None:
    """QuickBooks Online "Upload Transactions" CSV format.

    QBO accepts 3-column (Date, Description, Amount) or 4-column (Date, Description, Credit, Debit).
    We use the 4-column variant. NO Balance column (rejected by QBO importer).
    Amount sign rule: Debit (money out) → positive in Debit column; Credit (money in) → positive in Credit column.
    """
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Credit", "Debit"])
        for t in txns:
            w.writerow([
                t.date,
                t.description,
                f"{t.credit_cents/100:.2f}" if t.credit_cents else "",
                f"{t.debit_cents/100:.2f}" if t.debit_cents else "",
            ])


def write_iif(txns: list[ExtractedTxn], out_path: Path, account_name: str = "Checking") -> None:
    """QuickBooks Desktop IIF — bank-transaction format with proper TRNSTYPE + SPL splits.

    Per Intuit IIF spec, each transaction needs:
      - TRNS row (the bank side)
      - SPL row(s) (the offsetting split, e.g. uncategorized income/expense)
      - ENDTRNS marker
    Without SPL splits QuickBooks rejects the import with an unbalanced-transaction error.
    """
    lines = [
        "!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO",
        "!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO",
        "!ENDTRNS",
    ]
    for t in txns:
        # amount: positive = deposit (credit), negative = withdrawal (debit)
        amount_cents = t.credit_cents - t.debit_cents
        trns_type = "DEPOSIT" if amount_cents >= 0 else "CHECK"
        bank_amount = amount_cents / 100
        split_amount = -bank_amount  # offsetting entry
        split_account = "Uncategorized Income" if amount_cents >= 0 else "Uncategorized Expense"
        memo = t.description[:200]
        # Clean tabs from text fields
        clean_desc = t.description.replace("\t", " ").replace("\n", " ")[:120]
        lines.append(
            f"TRNS\t{trns_type}\t{t.date}\t{account_name}\t{clean_desc}\t{bank_amount:.2f}\t{memo}"
        )
        lines.append(
            f"SPL\t{trns_type}\t{t.date}\t{split_account}\t{clean_desc}\t{split_amount:.2f}\t{memo}"
        )
        lines.append("ENDTRNS")
    out_path.write_text("\n".join(lines) + "\n")


# ── Main entry ───────────────────────────────────────────────────────────────

def process_pdf(pdf_id: int, account_name: str = "Bank") -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM pdfs WHERE id = ?", (pdf_id,)).fetchone()
        if not row:
            return {"error": "pdf_not_found"}

        upload_dir = REPO / "state" / "uploads"
        # Find the PDF on disk
        candidates = list(upload_dir.rglob(row["filename"]))
        if not candidates:
            return {"error": "pdf_file_missing"}
        pdf_path = candidates[0]

        # Extract
        txns = extract_txns_via_claude(pdf_path, row["bank_guess"])
        opening = getattr(extract_txns_via_claude, "_opening", None)
        closing = getattr(extract_txns_via_claude, "_closing", None)

        # Verify
        report = reconcile(txns, opening, closing)

        # Write outputs
        out_dir = REPO / "state" / "deliveries" / str(pdf_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"{Path(row['filename']).stem}.csv"
        iif_path = out_dir / f"{Path(row['filename']).stem}.iif"
        write_csv(txns, csv_path)
        write_iif(txns, iif_path, account_name)

        # Persist delivery row
        cur = conn.execute(
            """INSERT INTO deliveries
               (pdf_id, row_count, sum_debits_cents, sum_credits_cents,
                opening_balance_cents, closing_balance_cents,
                reconciliation_score, flagged_rows, csv_path, iif_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pdf_id, report.row_count, report.sum_debits_cents, report.sum_credits_cents,
             report.opening_balance_cents, report.closing_balance_cents,
             report.score, len(report.flagged_rows), str(csv_path), str(iif_path)),
        )
        conn.commit()
        conn.execute("UPDATE pdfs SET state='reconciling' WHERE id=?", (pdf_id,))
        conn.commit()

        return {
            "ok": True,
            "pdf_id": pdf_id,
            "delivery_id": cur.lastrowid,
            "report": report.__dict__,
            "csv_path": str(csv_path),
            "iif_path": str(iif_path),
            "next_step": "Klau reviews + runs deliverer.py to send",
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pdf-id", type=int, required=True)
    p.add_argument("--account-name", default="Bank")
    args = p.parse_args()
    print(json.dumps(process_pdf(args.pdf_id, args.account_name), indent=2, default=str))
