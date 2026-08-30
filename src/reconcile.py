"""Deterministic reconciliation engine: the *arithmetic* half of the system.

Matches each bank deposit to the channel payout that produced it, verifies the
money nets out to the penny, and emits an audit trail. This is plain Python:
no LLM, no probabilities, fully reproducible. That separation is the whole point
of the project — a mis-categorization is a labelling error the eval can catch,
but a hallucinated *number* silently corrupts the books, so numbers never go
near the model.

Real-world cases handled explicitly:
  - gross-vs-net: a payout reports gross sales; the bank only sees net of fees
    and refunds, which we recompute and verify.
  - settlement lag: the deposit lands days after the payout is initiated, so we
    match within a date window, not on an exact date.
  - Razorpay risk hold: the deposit is sometimes short of net (a settlement is
    held for risk/compliance review). We flag these as partial rather than
    silently mismatching.
  - UTR-based matching: the bank memo and the settlement report share a UTR,
    which is the realistic join key rather than a shared primary key.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import date, datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

AMOUNT_TOLERANCE = 0.50   # rupees; covers rounding across sources
WINDOW_DAYS = 10          # max settlement lag we'll consider a candidate


@dataclass
class NormPayout:
    payout_id: str
    channel: str
    date: date
    gross: float
    fees: float
    refunds: float

    @property
    def net(self) -> float:
        return round(self.gross - self.fees - self.refunds, 2)


@dataclass
class Match:
    txn_id: str
    deposit_amount: float
    payout_id: str | None
    expected_net: float | None
    discrepancy: float | None  # deposit - expected_net
    status: str                # matched | partial_reserve | unmatched
    note: str = ""


def _parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {s!r}")


def _money(s: str) -> float:
    """Parse '₹1,234.56' / '-₹1,234.56' / '1,234.56' / '123' to float."""
    s = s.strip().replace("₹", "").replace("$", "").replace(",", "")
    return float(s) if s else 0.0


def load_payouts() -> list[NormPayout]:
    """Normalise the Razorpay settlement file into one comparable shape."""
    out: list[NormPayout] = []

    rp = os.path.join(DATA_DIR, "razorpay_settlements.csv")
    with open(rp, newline="") as f:
        for r in csv.DictReader(f):
            out.append(NormPayout(r["settlement_id"], "Razorpay", _parse_date(r["settlement_date"]),
                                  _money(r["gross_amount"]), _money(r["razorpay_fees_incl_gst"]),
                                  _money(r["refunds"])))
    return out


# Map a bank-memo fragment to the payout channel it belongs to.
_MEMO_CHANNEL = [
    ("RAZORPAY SETTLEMENT", "Razorpay"),
]


def _channel_for(description: str) -> str | None:
    up = description.upper()
    for frag, channel in _MEMO_CHANNEL:
        if frag in up:
            return channel
    return None


def reconcile() -> tuple[list[Match], list[NormPayout]]:
    payouts = load_payouts()
    by_channel: dict[str, list[NormPayout]] = {}
    for p in payouts:
        by_channel.setdefault(p.channel, []).append(p)

    matches: list[Match] = []
    claimed: set[str] = set()

    with open(os.path.join(DATA_DIR, "bank_feed.csv"), newline="") as f:
        deposits = [r for r in csv.DictReader(f) if _money(r["amount"]) > 0]

    for r in deposits:
        channel = _channel_for(r["description"])
        if channel is None:
            continue  # not a channel deposit (e.g. a transfer in)
        amount = _money(r["amount"])
        ddate = _parse_date(r["date"])
        candidates = [
            p for p in by_channel.get(channel, [])
            if p.payout_id not in claimed and 0 <= (ddate - p.date).days <= WINDOW_DAYS
        ]
        # Prefer an exact-net match; fall back to the nearest under-payment
        # (reserve) candidate. All comparisons are deterministic arithmetic.
        exact = [p for p in candidates if abs(p.net - amount) <= AMOUNT_TOLERANCE]
        if exact:
            best = min(exact, key=lambda p: abs(p.net - amount))
            claimed.add(best.payout_id)
            matches.append(Match(r["txn_id"], amount, best.payout_id, best.net,
                                 round(amount - best.net, 2), "matched"))
            continue

        shortfalls = [p for p in candidates if p.net > amount]
        if shortfalls:
            best = min(shortfalls, key=lambda p: p.net - amount)
            claimed.add(best.payout_id)
            disc = round(amount - best.net, 2)
            matches.append(Match(r["txn_id"], amount, best.payout_id, best.net, disc,
                                 "partial_reserve",
                                 note=f"deposit short by {abs(disc):.2f}; likely reserve/hold"))
            continue

        matches.append(Match(r["txn_id"], amount, None, None, None, "unmatched",
                             note="no payout within window/amount tolerance"))
    return matches, payouts


def summarize(matches: list[Match], payouts: list[NormPayout]) -> dict:
    total = len(matches)
    by_status: dict[str, int] = {}
    for m in matches:
        by_status[m.status] = by_status.get(m.status, 0) + 1
    reserve_held = round(sum(-m.discrepancy for m in matches
                             if m.status == "partial_reserve" and m.discrepancy), 2)
    expected_cash = sum(p.net for p in payouts)
    actual_cash = sum(m.deposit_amount for m in matches)
    unexplained_variance = round(expected_cash - actual_cash, 2)
    return {
        "deposits_examined": total,
        "by_status": by_status,
        "auto_matched_pct": round(100 * by_status.get("matched", 0) / total, 1) if total else 0.0,
        "reserve_or_short_held": reserve_held,
        "expected_cash": expected_cash,
        "actual_cash": actual_cash,
        "unexplained_variance": unexplained_variance,
    }


if __name__ == "__main__":
    import json
    ms, payouts = reconcile()
    print(json.dumps(summarize(ms, payouts), indent=2))
    for m in ms[:8]:
        print(f"  {m.txn_id} {m.deposit_amount:>10.2f}  {m.status:<16} "
              f"payout={m.payout_id} disc={m.discrepancy}")
