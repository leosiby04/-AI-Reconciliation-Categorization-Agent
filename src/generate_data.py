"""Synthetic-but-realistic financial data generator.

This is the heart of the case study. Real financial data is messy in *specific*
ways, and the credibility of the whole project rests on reproducing those exact
failure modes rather than clean toy data. Every bit of mess injected here is
labelled in the README's "failure modes" table.

Sources produced (mirroring common real-world financial data types):
  - bank_feed.csv               a business's current-account transactions
  - razorpay_settlements.csv    Razorpay payment-gateway settlements (UTR-matched,
                                 netted of gateway fees + GST on fees, risk holds)
  - quickbooks_pl_export.csv    a messy accounting export (the kind you actually get)
  - payroll_register.csv        a payroll run (gross vs net vs employer taxes)

Ground truth produced (never shown to the model; used only by the eval harness):
  - golden_categories.csv        bank txn_id -> true category
  - golden_reconciliation.csv    bank deposit txn_id -> payout_id

Deterministic: a fixed seed makes every run identical and reviewable.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SEED = 42
START = date(2025, 1, 1)
DAYS = 90  # one quarter

# --- Vendor / memo dictionaries: the cryptic strings a bank feed actually shows -
# Maps a true category to the kind of raw description that lands in the feed.
EXPENSE_VENDORS: dict[str, list[str]] = {
    "Software & SaaS": [
        "GOOGLE *GSUITE_acme", "INTUIT *QBOOKS", "SLACK T0288", "FIGMA MONTHLY",
        "AMAZON WEB SERVICES AWS", "NOTION LABS INC", "VERCEL INC",
    ],
    "Advertising & Marketing": [
        "FACEBK *7H2K9", "GOOGLE ADS 8842", "KLAVIYO INC", "TIKTOK ADS",
        "PINTEREST ADS 22", "INFLUENCER PAYOUT GRIN",
    ],
    "Shipping & Fulfillment": [
        "SHIPBOB INC", "USPS PB 8000", "EASYPOST", "FEDEX 7729", "SHIPSTATION",
        "FLEXPORT 3PL INV",
    ],
    "Cost of Goods Sold": [
        "SHENZHEN MFG CO", "ALIBABA *RAWMAT", "PACKAGING SUPPLY CO",
        "CONTRACT MFG ACH", "INGREDIENT SUPPLIER LLC",
    ],
    "Office & Admin": [
        "WEWORK MEMBERSHIP", "STAPLES 00471", "COMCAST BUSINESS", "VERIZON WRLS",
        "UBER *TRIP", "RAZORPAY SOFTWARE SUBS",  # intentionally ambiguous vs Razorpay Sales
    ],
    "Professional Services": [
        "KHAITAN LAW RETAINER", "DELOITTE TAX SVCS", "UPWORK *CONTRACTOR",
        "STRIPE ATLAS", "FRACTIONAL CFO LLC",
    ],
}

# Channels and their economics (fee rate, refund rate, settlement lag in days).
# Single payment gateway: Razorpay. Razorpay's own settlement economics are the
# mess to reproduce here — gateway fee + GST *on* the fee (not on gross), T+2
# settlement lag, and occasional risk-review holds that short the deposit.
@dataclass
class Channel:
    name: str
    category: str
    fee_rate: float
    refund_rate: float
    lag_days: int
    bank_memo: str
    gst_on_fee_rate: float = 0.18  # GST charged on the Razorpay fee itself


CHANNELS = [
    Channel("Razorpay", "Razorpay Sales", 0.02, 0.035, 2, "RAZORPAY SETTLEMENT"),
]


@dataclass
class Txn:
    txn_id: str
    date: date
    description: str
    amount: float  # signed: + deposit, - withdrawal
    true_category: str
    matched_payout_id: str | None = None


@dataclass
class Payout:
    payout_id: str
    channel: str
    payout_date: date  # when it hits the bank
    gross: float
    fees: float
    refunds: float
    order_count: int

    @property
    def net(self) -> float:
        return round(self.gross - self.fees - self.refunds, 2)


def _money(lo: float, hi: float) -> float:
    return round(random.uniform(lo, hi), 2)


def _d(offset: int) -> date:
    return START + timedelta(days=offset)


def build() -> dict:
    random.seed(SEED)
    txns: list[Txn] = []
    payouts: list[Payout] = []
    n = 0

    def next_id(prefix: str) -> str:
        nonlocal n
        n += 1
        return f"{prefix}{n:04d}"

    # --- Channel revenue -> payouts -> bank deposits --------------------------
    # Each channel batches many orders into a periodic payout. The payout NETS
    # fees and refunds (gross-vs-net mess) and lands in the bank a few days later
    # (settlement-lag mess). The bank only ever sees the net number + a memo.
    for ch in CHANNELS:
        day = 1
        while day < DAYS:
            order_count = random.randint(20, 120)
            gross = round(sum(_money(300, 5500) for _ in range(order_count)), 2)  # INR per order
            gateway_fee = round(gross * ch.fee_rate, 2)
            gst_on_fee = round(gateway_fee * ch.gst_on_fee_rate, 2)
            fees = round(gateway_fee + gst_on_fee, 2)  # fee + GST-on-fee, netted together
            refunds = round(gross * ch.refund_rate * random.uniform(0.3, 1.4), 2)
            pid = next_id("PO")
            settle_day = day + ch.lag_days
            if settle_day >= DAYS:
                break
            payouts.append(Payout(pid, ch.name, _d(settle_day), gross, fees, refunds, order_count))

            net = round(gross - fees - refunds, 2)
            # Razorpay can place a settlement under risk review: the bank deposit
            # is sometimes a bit less than `net`, with the remainder released
            # later once the hold clears. This breaks naive exact-amount matching
            # and is a real Razorpay behaviour (risk/compliance holds).
            deposit = net
            if random.random() < 0.25:
                deposit = round(net * random.uniform(0.85, 0.95), 2)
            utr = f"UTR{pid[-6:]}"
            txns.append(Txn(
                txn_id=next_id("BT"),
                date=_d(settle_day),
                description=f"{ch.bank_memo} {pid[-4:]} {utr}",
                amount=deposit,
                true_category=ch.category,
                matched_payout_id=pid,
            ))
            day += random.randint(3, 6)  # Razorpay settles frequently (near-daily/T+2 batches)

    # --- Expenses (bank withdrawals) -----------------------------------------
    for _ in range(140):
        cat = random.choice(list(EXPENSE_VENDORS.keys()))
        memo = random.choice(EXPENSE_VENDORS[cat])
        amount = -_money(800, 165000)  # INR-scale business expenses
        txns.append(Txn(
            txn_id=next_id("BT"),
            date=_d(random.randint(0, DAYS - 1)),
            description=memo,
            amount=amount,
            true_category=cat,
        ))
        
    # --- The Buildathon "Hero" Edge Case ---
    txns.append(Txn(
        txn_id=next_id("BT"),
        date=_d(85), # Towards the end of the quarter
        description="DOMINOS PIZZA *BUILDATHON NIGHT",
        amount=-3450.00,
        true_category="Office & Admin",
    ))

    # --- Payroll: shows up in the bank as a few large round-ish ACH debits ----
    payroll_rows = []
    for run_idx, pay_day in enumerate([14, 28, 42, 56, 70, 84]):
        employees = 8
        gross = round(sum(_money(35000, 145000) for _ in range(employees)), 2)  # INR monthly gross
        taxes = round(gross * 0.12, 2)   # employer EPF contribution, simplified
        net = round(gross * 0.85, 2)     # after employee PF/PT withholdings
        # Two separate bank debits: net pay to employees, statutory dues to the agency.
        txns.append(Txn(next_id("BT"), _d(pay_day), "RAZORPAYX PAYROLL NET DIRECT DEP",
                        -net, "Payroll Expense"))
        txns.append(Txn(next_id("BT"), _d(pay_day), "RAZORPAYX PAYROLL EPF CHALLAN",
                        -taxes, "Payroll Taxes"))
        payroll_rows.append({
            "run_id": f"RUN{run_idx + 1:02d}", "pay_date": _d(pay_day).isoformat(),
            "employees": employees, "gross_pay": gross,
            "employer_taxes": taxes, "net_pay": net,
        })

    # --- A couple of internal transfers and an owner draw (not on the P&L) -----
    txns.append(Txn(next_id("BT"), _d(30), "ONLINE TRANSFER TO SAVINGS xxxx8841",
                    -500000.0, "Internal Transfer"))
    txns.append(Txn(next_id("BT"), _d(60), "ONLINE TRANSFER FROM SAVINGS xxxx8841",
                    500000.0, "Internal Transfer"))
    txns.append(Txn(next_id("BT"), _d(75), "OWNER DISTRIBUTION ACH", -250000.0,
                    "Owner Draw / Capital"))

    txns.sort(key=lambda t: (t.date, t.txn_id))
    return {"txns": txns, "payouts": payouts, "payroll": payroll_rows}


# --- Writers: each emits the *format* (and mess) of its real-world source -----

def _running_balance(txns: list[Txn]) -> list[float]:
    bal, out = 1_000_000.0, []  # INR opening balance
    for t in txns:
        bal = round(bal + t.amount, 2)
        out.append(bal)
    return out


def write_all(world: dict) -> None:
    import csv
    os.makedirs(DATA_DIR, exist_ok=True)
    txns: list[Txn] = world["txns"]
    payouts: list[Payout] = world["payouts"]

    # Bank feed: messy date formats + signed amounts as strings with commas.
    balances = _running_balance(txns)
    with open(os.path.join(DATA_DIR, "bank_feed.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "date", "description", "amount", "balance"])
        for t, bal in zip(txns, balances):
            # Mix MM/DD/YYYY and YYYY-MM-DD to force real date parsing.
            ds = t.date.strftime("%m/%d/%Y") if t.txn_id[-1] in "02468" else t.date.isoformat()
            amt = f"{t.amount:,.2f}" if t.amount < 0 else f"{t.amount:,.2f}"
            w.writerow([t.txn_id, ds, t.description, amt, f"{bal:,.2f}"])

    # Razorpay settlement report: gross, gateway fee, GST-on-fee split out,
    # refunds, NO net column (you must compute it — mirrors the real report),
    # plus the UTR so settlements can be matched to the bank feed the way a
    # finance team actually does it.
    by_channel: dict[str, list[Payout]] = {}
    for p in payouts:
        by_channel.setdefault(p.channel, []).append(p)

    with open(os.path.join(DATA_DIR, "razorpay_settlements.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["settlement_id", "utr", "settlement_date", "gross_amount",
                     "razorpay_fees_incl_gst", "refunds", "transaction_count"])
        for p in by_channel.get("Razorpay", []):
            # Reconstruct the same UTR the bank memo carries, from the payout id,
            # so the join key is realistic rather than a shared primary key.
            w.writerow([p.payout_id, f"UTR{p.payout_id[-6:]}",
                        p.payout_date.isoformat(), p.gross, p.fees, p.refunds, p.order_count])

    # QuickBooks-style P&L export: the messy accounting export. Inconsistent
    # account names, amounts as "₹1,234.56" strings, blank subtotal rows.
    with open(os.path.join(DATA_DIR, "quickbooks_pl_export.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Account", "Type", "Amount"])
        rows = [
            ("Sales - Razorpay", "Income", 4284071.00),
            ("Sales:Wholesale", "Income", 443000.00),        # colon hierarchy
            ("Refunds/Returns", "Income", -176804.20),       # contra-revenue as negative income
            ("", "", None),                                  # blank subtotal row
            ("COGS", "Cost of Goods Sold", 1424008.40),
            ("Razorpay Fees  (incl GST)", "Expense", 182477.60),  # double space; fee mislabeled type
            ("Payroll", "Expense", 2840000.00),
            ("Payroll Tax Expense", "Expense", 340800.00),
            ("Advertising & Promo", "Expense", 1068015.00),
            ("Software Subscriptions", "Expense", 156408.00),
            ("Ask My Accountant", "Expense", 29000.00),      # the real-world "dunno" bucket
        ]
        for acct, typ, amt in rows:
            amt_str = "" if amt is None else (f"-₹{abs(amt):,.2f}" if amt < 0 else f"₹{amt:,.2f}")
            w.writerow([acct, typ, amt_str])

    # Payroll register.
    with open(os.path.join(DATA_DIR, "payroll_register.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "pay_date", "employees", "gross_pay", "employer_taxes", "net_pay"])
        for r in world["payroll"]:
            w.writerow([r["run_id"], r["pay_date"], r["employees"], r["gross_pay"], r["employer_taxes"], r["net_pay"]])

    # --- Ground truth (held out from the model) -------------------------------
    with open(os.path.join(DATA_DIR, "golden_categories.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "true_category"])
        for t in txns:
            w.writerow([t.txn_id, t.true_category])

    with open(os.path.join(DATA_DIR, "golden_reconciliation.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "payout_id"])
        for t in txns:
            if t.matched_payout_id:
                w.writerow([t.txn_id, t.matched_payout_id])

    summary = {
        "transactions": len(txns),
        "payouts": len(payouts),
        "deposits_to_reconcile": sum(1 for t in txns if t.matched_payout_id),
        "categories_present": sorted({t.true_category for t in txns}),
    }
    with open(os.path.join(DATA_DIR, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Generated data:\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    write_all(build())
