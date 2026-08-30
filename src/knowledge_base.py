"""Accounting knowledge base — generated from the SAME source as the transactions.

This is the corpus the categorization agent retrieves over (RAG). The hard
requirement: the KB and the transaction data must describe the *same world*. So
this module imports the exact vendor list, channels, and chart of accounts that
`generate_data.py` uses to mint transactions. Every vendor that can appear in a
bank feed has matching policy passages here; there is one source of truth, so the
KB can never drift from the data.

For each vendor and category we emit several passages (a rule, a worked example,
a common-mistake note, accounting treatment), plus channel reconciliation
policies, payroll rules, and edge cases — yielding a large, realistic KB rather
than a toy lookup table.

Output: data/knowledge_base.jsonl  (one passage per line)
"""

from __future__ import annotations

import json
import os

import generate_data as g
import schema as s

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
KB_PATH = os.path.join(DATA_DIR, "knowledge_base.jsonl")


def _vendor_label(memo: str) -> str:
    """Human-ish vendor name from a raw bank memo (e.g. 'FACEBK *7H2K9' -> 'FACEBK')."""
    return memo.split("*")[0].split(" ")[0].strip().title()


def build() -> list[dict]:
    docs: list[dict] = []

    def add(category, topic, title, text, vendors=None):
        docs.append({
            "doc_id": f"kb-{len(docs) + 1:04d}",
            "category": category,
            "section": s.income_statement_section(category) if category in s.CATEGORIES else "Reference",
            "topic": topic,
            "vendors": vendors or [],
            "title": title,
            "text": text,
        })

    # 1) One policy + one accounting-treatment passage per chart-of-accounts category.
    for category, section in s.CATEGORIES.items():
        add(category, "category_policy", f"Policy: {category}",
            f"The '{category}' account rolls up to '{section}' on the income statement. "
            f"Classify a transaction here when the underlying economic activity is "
            f"{category.lower()}. When the memo is ambiguous between {category} and another "
            f"account, prefer the account that matches the counterparty's primary business, "
            f"and flag low-confidence cases for human review rather than guessing.")
        add(category, "accounting_treatment", f"Accounting treatment: {category}",
            f"{category} is reported under {section}. "
            + ("Revenue is recognized net of refunds and chargebacks (contra-revenue). "
               if section == s.REVENUE else
               "Cost of Goods Sold is matched to the revenue it generated in the period. "
               if section == s.COGS else
               "Operating expenses are recognized in the period incurred. "
               if section == s.OPEX else
               "This is a balance-sheet / equity movement and does NOT appear on the P&L. ")
            + "Amounts are recorded on an accrual basis and reconciled to the bank feed monthly.")

    # 2) Several passages per expense vendor (rule + example + common mistake).
    for category, memos in g.EXPENSE_VENDORS.items():
        for memo in memos:
            vendor = _vendor_label(memo)
            add(category, "vendor_rule", f"Vendor rule: {vendor} → {category}",
                f"Bank memos beginning with or containing '{memo}' are {vendor}, a "
                f"{category.lower()} vendor. Categorize these transactions as '{category}'. "
                f"These appear as debits (money out) on the operating account.",
                vendors=[memo])
            add(category, "vendor_example", f"Example: {vendor}",
                f"Example transaction: a debit with description '{memo}' for a few hundred to "
                f"a few lakh rupees should be booked to '{category}'. The exact amount "
                f"is verified against the bank feed, never inferred.",
                vendors=[memo])
            add(category, "common_mistake", f"Common mistake: {vendor}",
                f"Do not confuse '{memo}' with similarly named counterparties. {vendor} is "
                f"strictly {category.lower()}; matching on the full memo prefix avoids "
                f"misclassification into an unrelated account.",
                vendors=[memo])

    # 3) Razorpay settlement + reconciliation policies (gross vs net, fee + GST-on-fee,
    #    settlement lag, risk holds, UTR matching).
    for ch in g.CHANNELS:
        add(ch.category, "vendor_rule", f"Channel deposit: {ch.name} → {ch.category}",
            f"Bank deposits with memo '{ch.bank_memo}' are settlement payouts from the "
            f"{ch.name} payment gateway and are categorized as '{ch.category}' (revenue). "
            f"These are credits (money in), and the bank memo carries a UTR that also "
            f"appears on the settlement report — use it as the primary join key.",
            vendors=[ch.bank_memo])
        add(ch.category, "reconciliation", f"Reconciliation policy: {ch.name}",
            f"{ch.name} batches many orders into a periodic settlement. The bank only sees the "
            f"NET amount: gross sales minus the gateway fee (~{ch.fee_rate:.1%}) minus GST on "
            f"that fee (~{ch.gst_on_fee_rate:.0%} of the fee, not of gross) minus refunds "
            f"(~{ch.refund_rate:.1%}). To reconcile, recompute net = gross − (fee + GST-on-fee) "
            f"− refunds from the {ch.name} settlement report and match it to the bank deposit "
            f"to the penny, using the shared UTR. Settlements land ~{ch.lag_days} business "
            f"day(s) after the transaction, so match within a date window, not on an exact date.")
    add("Razorpay Sales", "reconciliation", "Reconciliation policy: Razorpay risk hold",
        "Razorpay may place a settlement under risk/compliance review, so a bank deposit can be "
        "SHORT of the computed net settlement. Do not force-match these; flag the shortfall as "
        "a risk hold and reconcile the released amount in a later period.")
    add("Razorpay Fees", "reconciliation", "Razorpay fees policy",
        "Razorpay gateway fees (plus GST charged on the fee) are netted out of settlements. "
        "Record the fee portion to 'Razorpay Fees' (COGS) so gross revenue and fees are both "
        "visible, rather than only booking the net deposit.")

    # 4) Payroll, refunds, transfers, edge cases.
    add("Payroll Expense", "vendor_rule", "Payroll: net pay vs statutory dues",
        "A 'RAZORPAYX PAYROLL NET DIRECT DEP' debit is net wages paid to employees → "
        "'Payroll Expense'. A separate 'RAZORPAYX PAYROLL EPF CHALLAN' debit is the "
        "employer's EPF contribution → 'Payroll Taxes'. They are two distinct postings "
        "from one payroll run.",
        vendors=["RAZORPAYX PAYROLL NET DIRECT DEP", "RAZORPAYX PAYROLL EPF CHALLAN"])
    add("Refunds & Chargebacks", "category_policy", "Refunds & chargebacks",
        "Refunds and chargebacks are contra-revenue: they reduce the related channel's "
        "revenue rather than being booked as an expense.")
    add("Internal Transfer", "edge_case", "Internal transfers are not P&L",
        "'TRANSFER TO/FROM SAVINGS' movements between the company's own accounts are internal "
        "transfers, not income or expense, and must be excluded from the P&L.",
        vendors=["ONLINE TRANSFER"])
    add("Owner Draw / Capital", "edge_case", "Owner distributions",
        "'OWNER DISTRIBUTION' / draws are equity movements, not operating expenses, and do not "
        "appear on the income statement.", vendors=["OWNER DISTRIBUTION"])
    add("Razorpay Sales", "edge_case", "Edge case: Razorpay subscription vs Razorpay settlement",
        "Beware: 'RAZORPAY SOFTWARE SUBS' is a debit for the company's OWN Razorpay platform "
        "subscription (an expense, Office & Admin), whereas 'RAZORPAY SETTLEMENT' is a credit "
        "PAYOUT of collected customer payments (Razorpay Sales revenue). Both memos start with "
        "'RAZORPAY' — the direction of the amount (debit vs credit) disambiguates them, not the "
        "memo prefix alone.",
        vendors=["RAZORPAY SOFTWARE SUBS", "RAZORPAY SETTLEMENT"])

    return docs


def write() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    docs = build()
    with open(KB_PATH, "w") as f:
        for d in docs:
            f.write(json.dumps(d) + "\n")
    by_topic: dict[str, int] = {}
    for d in docs:
        by_topic[d["topic"]] = by_topic.get(d["topic"], 0) + 1
    summary = {"passages": len(docs), "by_topic": by_topic,
               "categories_covered": len({d["category"] for d in docs})}
    print(json.dumps(summary, indent=2))
    return summary


def load() -> list[dict]:
    return [json.loads(line) for line in open(KB_PATH)]


if __name__ == "__main__":
    write()
