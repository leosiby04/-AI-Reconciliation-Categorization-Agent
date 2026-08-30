# Case study: an AI system you can trust with the books

*A reconciliation & categorization agent for messy consumer-brand finance.*

This shows how I approach AI on top of real, messy financial data — accounting
exports, payout feeds, payroll — where the output has to be not just plausible
but *correct and auditable*. It runs end-to-end with no API key (offline mock)
and with a real LLM when you add one.

---

## The problem, in one paragraph

A business collects payments via Razorpay, alongside a wholesale channel. Money
arrives in lumps: one bank line might be "40 orders' worth, net of gateway fees
and GST-on-fees, from two days ago," labelled `RAZORPAY SETTLEMENT 0001
UTRPO0001`. Someone has to (a) decide what every transaction *is*, and (b) prove
each deposit equals what Razorpay's settlement report said it owed, net of
fees, GST-on-fees, refunds, and risk holds. It's tedious, unforgiving, and the
data fights you: gross-vs-net mismatches, settlement lag, Razorpay holding a
settlement for risk review, an accounting export full of `₹1,234.56` strings and
an "Ask My Accountant" bucket.

## The one design decision that matters

**The LLM is only allowed to judge. It is never allowed to do arithmetic.**

- *Judgment* (which category? which payout does this deposit belong to?) is
  fuzzy, language-shaped work — the LLM is good at it, and when it's wrong the
  evaluation catches it.
- *Arithmetic* (net = gross − fees − refunds; does the deposit match to the
  penny?) is done by plain, deterministic Python that produces an audit trail.
  A hallucinated number here wouldn't be caught by an eval — it would silently
  mis-state the P&L. That risk is unacceptable, so the model never touches it.

This split is the whole architecture, and it's the thing I'd defend in finance
AI generally: **don't ask the model to be a calculator; ask it to be a
classifier, and verify everything downstream.**

## What I built

A handful of small modules (see `README.md` for the map): a generator that
produces *deliberately* messy data plus held-out ground truth; a **142-passage
accounting knowledge base generated from the same source as the data**; a
categorization agent grounded by **RAG over that KB** (and over similar past
transactions), citing the policy rule it applied; a deterministic reconciliation
engine; evaluation harnesses; and a Streamlit dashboard. No fine-tuning —
intentionally. The senior move is showing you *don't* need to train a model; you
need good structure, retrieval, guardrails, and evaluation.

**Why the KB is generated from the data's own source:** the knowledge base and
the transactions both import the same vendor list, Razorpay settlement
economics, and chart of accounts, so the KB can never drift from the data it
describes — every vendor that can appear in a bank feed has matching policy
passages. That alignment is deliberate; a RAG corpus disconnected from the data
is a common failure I wanted to avoid.

## Grappling with the mess (the part that signals real experience)

Every failure mode below is reproduced in the synthetic data and handled
explicitly — this is the table I'd want a reviewer to read:

- **Gross vs. net** — the settlement report reports gross; the bank sees net of
  the gateway fee *and* GST charged on that fee. The engine recomputes and
  verifies to the penny.
- **Settlement lag** — deposits land days later, so matching is over a date
  window, not an exact date.
- **Razorpay risk hold** — deposits sometimes come up short; the engine flags
  the exact shortfall as `partial_reserve` instead of forcing a wrong match,
  rather than assuming the settlement report is wrong.
- **UTR-based matching** — the bank memo and the settlement report share a UTR,
  the realistic join key a finance team actually uses, not a shared primary key.
- **Dirty accounting export** — money-as-strings, messy account names, blank
  rows; parsed robustly, ambiguous accounts routed to review.
- **Ambiguity** — `RAZORPAY SOFTWARE SUBS` (the company's own platform
  subscription, a debit) vs `RAZORPAY SETTLEMENT` (a settlement credit): a KB
  edge-case rule disambiguates by memo + direction; truly unresolvable cases
  abstain (`Needs Review`) rather than guess.

## Results (measured against held-out ground truth)

The eval grades on transactions the model never sees, and retrieval is built only
from non-test rows — no answer leakage. Offline mock-model results on this
Razorpay-only, INR dataset:

| Metric | Result |
|---|---|
| Categorization accuracy, no RAG | 100.0% |
| Categorization accuracy, KB RAG | 100.0% |
| Citation coverage / accuracy-when-cited | 100.0% / 100.0% |
| Auto-post coverage at confidence ≥ 0.75 | 100.0%, 100.0% accurate on that slice |
| Reconciliation match accuracy | **100%** (18/18 deposits → correct settlement) |
| Engine auto-match rate | 66.7% matched; the rest **flagged, never guessed** (risk holds) |

The mock keyword baseline already resolves these memos cleanly, so it shows no
RAG lift on this run — that's expected. The **real +46.4% lift figure** (against
a real LLM, on cryptic vendor memos like `FACEBK *7H2K9` / `SHENZHEN MFG CO`)
came from a `gpt-4o-mini` run and is reproducible here by setting
`OPENAI_API_KEY` and re-running `evaluate.py` / `evaluate_kb.py`. The
reconciliation stays at 100% regardless of model, because it's deterministic —
the LLM is never in the numeric path.

**Honest caveat:** the KB is drawn from the same vendor distribution as the data,
so retrieval usually finds a near-exact rule → near-perfect accuracy. On genuinely
novel vendors it would be lower; the feedback loop (human corrections becoming new
KB entries) is how that gap closes. I'd rather state this than oversell the 100%.

## What's deliberately missing, and why

- **No fine-tuning** — unnecessary and a worse signal than disciplined prompting
  + retrieval + eval.
- **AR/AP and inventory** aren't built — they extend the same pattern (match an
  invoice to a payment; reconcile a 3PL inventory snapshot to recorded COGS) and
  I scoped to four sources deeply rather than seven shallowly.
- **The RAG layer is a clean v1.** Retrieval is isolated behind a small interface
  so it can be hardened — retrieval eval (recall@k/MRR), hybrid lexical+vector
  search, reranking, an ANN index, and a feedback loop where human corrections
  become new KB entries. I built exactly that hardening in the companion
  **filings-intelligence** project (hybrid retrieval + a measured retrieval eval +
  structured routing); the same upgrades apply here.

## What this demonstrates

A complete slice of real-world financial operations: a P&L spanning Razorpay
settlements and wholesale, a bank feed reconciled against a payment gateway,
structured handling of messy accounting exports, a multi-step tool-using agent,
and — most importantly — an **evaluation-first** posture, because in finance the
expensive failure isn't an outage, it's a confident wrong number. The same
approach scales directly to larger charts of accounts, more channels, and AR/AP
and inventory.
