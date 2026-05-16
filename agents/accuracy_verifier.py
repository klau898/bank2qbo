"""Standalone reconciliation accuracy verifier — extracted from processor.py.

Separated so it can be:
  1. Unit-tested with synthetic transaction sets
  2. Re-run on existing deliveries (CLI: --delivery-id N)
  3. Called from processor.py (existing import path preserved)
  4. Called from concierge_serve.py upload-side preview ("show me reconciliation before I pay")

Codex-tightened bands (May 14, 2026) — delta == 0 required for auto-pass.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "state" / "concierge.db"


@dataclass
class ExtractedTxn:
    date: str
    description: str
    debit_cents: int
    credit_cents: int
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
    delta_cents: int | None
    score: float
    flagged_rows: list[int]
    notes: list[str]

    def as_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "sum_debits_cents": self.sum_debits_cents,
            "sum_credits_cents": self.sum_credits_cents,
            "opening_balance_cents": self.opening_balance_cents,
            "closing_balance_cents": self.closing_balance_cents,
            "expected_closing": self.expected_closing,
            "delta_cents": self.delta_cents,
            "score": self.score,
            "flagged_rows": self.flagged_rows,
            "notes": self.notes,
        }


def reconcile(
    txns: list[ExtractedTxn],
    opening: int | None,
    closing: int | None,
) -> ReconciliationReport:
    """Verify the extraction reconciles. The core trust signal.

    Codex-tightened bands (May 14, 2026): bookkeeper trust requires delta == 0
    to auto-pass. ANY non-zero delta forces manual review.
    """
    debits = sum(t.debit_cents for t in txns)
    credits = sum(t.credit_cents for t in txns)
    flagged: list[int] = []
    notes: list[str] = []

    for i, t in enumerate(txns):
        if t.debit_cents > 0 and t.credit_cents > 0:
            flagged.append(i)
            notes.append(f"row {i}: both debit + credit nonzero")
        if t.debit_cents == 0 and t.credit_cents == 0:
            flagged.append(i)
            notes.append(f"row {i}: zero-value transaction")

    expected_closing: int | None = None
    delta: int | None = None
    score = 0.0

    if opening is not None and closing is not None:
        expected_closing = opening + credits - debits
        delta = closing - expected_closing
        abs_delta = abs(delta)
        if delta == 0:
            score = 1.0
            notes.append("PERFECT — closing balance matches expected exactly")
        elif abs_delta == 1:
            score = 0.95
            notes.append(
                f"1-cent delta (${delta/100:.2f}) — manual review recommended; likely rounding row"
            )
        elif abs_delta <= 100:
            score = 0.80
            notes.append(
                f"MANUAL REVIEW — off by ${delta/100:.2f}; identify missing row before send"
            )
        elif abs_delta <= 10000:
            score = 0.5
            notes.append(f"FAIL — off by ${delta/100:.2f}; do NOT ship; re-run")
        else:
            score = 0.2
            notes.append(
                f"FATAL — off by ${delta/100:.2f}; extraction broken; re-run with Vision API"
            )
    else:
        score = 0.7
        notes.append(
            "Could not extract opening/closing balance — manual verification required before ship"
        )

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


def reconcile_from_csv(csv_path: Path, opening: int | None, closing: int | None) -> ReconciliationReport:
    """Re-run reconciliation against an existing CSV output.

    Expected CSV format (per processor.py write_csv): Date, Description, Credit, Debit
    """
    txns: list[ExtractedTxn] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            credit_str = row.get("Credit", "").strip()
            debit_str = row.get("Debit", "").strip()
            credit_cents = int(round(float(credit_str) * 100)) if credit_str else 0
            debit_cents = int(round(float(debit_str) * 100)) if debit_str else 0
            txns.append(ExtractedTxn(
                date=row.get("Date", ""),
                description=row.get("Description", ""),
                debit_cents=debit_cents,
                credit_cents=credit_cents,
            ))
    return reconcile(txns, opening, closing)


def reverify_delivery(delivery_id: int) -> dict:
    """Re-run reconciliation against a stored delivery's CSV file."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        d = conn.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
        if not d:
            return {"error": "delivery_not_found"}
        csv_path = Path(d["csv_path"])
        if not csv_path.exists():
            return {"error": "csv_missing", "path": str(csv_path)}
        report = reconcile_from_csv(
            csv_path,
            d["opening_balance_cents"],
            d["closing_balance_cents"],
        )
        return {"delivery_id": delivery_id, "csv": str(csv_path), "report": report.as_dict()}
    finally:
        conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--delivery-id", type=int, help="Re-verify an existing delivery by ID")
    p.add_argument("--csv", type=str, help="Verify any CSV file directly")
    p.add_argument("--opening", type=int, help="Opening balance in cents")
    p.add_argument("--closing", type=int, help="Closing balance in cents")
    args = p.parse_args()

    if args.delivery_id:
        print(json.dumps(reverify_delivery(args.delivery_id), indent=2, default=str))
    elif args.csv:
        report = reconcile_from_csv(Path(args.csv), args.opening, args.closing)
        print(json.dumps(report.as_dict(), indent=2))
    else:
        # Self-test with synthetic data
        txns = [
            ExtractedTxn(date="2026-05-01", description="Opening", debit_cents=0, credit_cents=0),
            ExtractedTxn(date="2026-05-02", description="Paycheck", debit_cents=0, credit_cents=500000),
            ExtractedTxn(date="2026-05-03", description="Rent", debit_cents=200000, credit_cents=0),
            ExtractedTxn(date="2026-05-04", description="Coffee", debit_cents=500, credit_cents=0),
        ]
        # Note: txn 0 is opening row with both 0 → will flag
        report = reconcile(txns, opening=100000, closing=100000 + 500000 - 200000 - 500)
        print(json.dumps(report.as_dict(), indent=2))
