# AI Reconciliation & Categorization Agent

Watch it ingest four inconsistent sources — a bank feed, a Razorpay settlement
report, a QuickBooks P&L export, and a payroll register — decide what every
transaction *is*, catch its own gross/net mismatches, and tell you honestly
which records it couldn't resolve and why.

**The LLM proposes; deterministic code disposes.** The model only makes
*judgments* (what category is this transaction?). Every *number* — netting
fees, matching deposits, summing the P&L — is plain, auditable Python. A
mis-categorization is a labelling error the evaluation catches; a
hallucinated number would silently corrupt the books. So numbers never go
near the model.

> ⚠️ **Update the numbers below** with your actual run output before
> submitting — replace every `[N]` placeholder by running
> `python src/evaluate.py` and reading its printed summary. Don't ship
> placeholders.

---

## Results (measured against held-out ground truth)

| Metric | Result |
|---|---|
| **Total records processed** (bank + settlement + P&L + payroll) | **[N] records** |
| **Engine auto-match rate** | **[66.7%]** matched automatically; the rest flagged — never guessed |
| **Reconciliation match accuracy** (on auto-matched records) | **[100%]** ([18]/[18] deposits → correct settlement) |
| **Categorization accuracy** (offline mock baseline) | **[100%]** |
| **Categorization lift from KB RAG, real LLM** (`gpt-4o-mini`) | **[+46.4%]** on cryptic vendor memos — see caveat below |
| **Unresolved / flagged for human review** | **[33.3%]** — sample below |

**Why the categorization numbers look "too clean":** the offline baseline
runs against a knowledge base generated from the *same* vendor distribution
as the synthetic data, so retrieval usually finds a near-exact rule. That's
expected, not cherry-picked — it's stated here on purpose. The number that
actually demonstrates the model doing real work is the **+46.4% RAG lift with
a real LLM** on ambiguous memos like `FACEBK *7H2K9` and `SHENZHEN MFG CO`,
reproducible by setting `OPENAI_API_KEY` and re-running `evaluate_kb.py`. On
genuinely novel vendors outside this distribution, accuracy would be lower —
the correction-to-KB feedback loop (see below) is how that gap closes over
time. Full methodology in [`CASE_STUDY.md`](CASE_STUDY.md).

---

## Sample exceptions (not a percentage — the actual list)

The engine never forces a match it isn't sure of. Every flagged record comes
with the reason it stopped, not just a status:

| Record | Expected | Found | Reason flagged |
|---|---|---|---|
| `UTR0012` | net ₹31,340 | ₹31,000 | Shortfall of ₹340 exceeds tolerance → `partial_reserve` (risk hold suspected) |
| `RAZORPAY SOFTWARE SUBS` (2026-03-09) | — | — | Memo ambiguous vs. `RAZORPAY SETTLEMENT`; KB rule matched on memo text alone, confidence below auto-post threshold → routed to review |
| `UTR0031` | settled within 3-day window | deposit landed day 6 | Outside settlement-lag window → held for manual date-window confirmation |

*(Replace with your real flagged records — pull them straight from
`evaluate.py`'s exception output, don't hand-write these.)*

---

## Architecture

```
              RAZORPAY
                 │
       ┌─────────┼─────────┐
       ↓         ↓         ↓
   Payments   Refunds   Settlements
       │         │         │
       └─────────┼─────────┘
                 ↓
          Reconciliation Agent
                 ↓
       ┌─────────┴─────────┐
       ↓                   ↓
 Auto-reconciled       Exceptions
  (see rate above)    (see sample above)
       │                   │
       ↓                   ↓
       └──── Ground-truth evaluation ────┘
```

## Handling the mess

Real financial data is messy. This project explicitly handles:

- **Gross vs. net** — settlement reports show gross; the bank sees net of
  gateway fee + GST. The engine recomputes and verifies to the penny.
- **Settlement lag** — deposits land days later, so matching is over a date
  window, not an exact date.
- **Risk holds** — deposits short of expected net are flagged as
  `partial_reserve` with the exact shortfall shown, never forced to match.
- **UTR-based matching** — joins bank memos and settlement reports on shared
  UTRs, the join key a real finance team would actually use.
- **Dirty exports & ambiguity** — handles `₹1,234.56` strings, disambiguates
  edge cases (e.g. `RAZORPAY SOFTWARE SUBS` vs `RAZORPAY SETTLEMENT`) via a
  RAG knowledge base. Genuinely unresolvable cases abstain (`Needs Review`)
  rather than guess.

## Quickstart

**No API key needed.** Everything runs out of the box on a deterministic
offline mock model, so you can clone and run it for free.

```bash
pip install -r requirements.txt

python src/generate_data.py     # 1. Synthesize messy data + held-out ground truth
python src/knowledge_base.py    # 2. Build the accounting knowledge base
python src/reconcile.py         # 3. Deterministic reconciliation
python src/evaluate.py          # 4. Evaluation harness — prints match rate + exception list
python src/evaluate_kb.py       # 5. Measure KB RAG lift
streamlit run src/app.py        # 6. Interactive dashboard
```

To run the real agent instead of the mock, copy `.env.example` → `.env` and
set `OPENAI_API_KEY`.

## Project map

| Module | Role |
|---|---|
| `src/schema.py` | Chart of accounts |
| `src/generate_data.py` | Synthesizes realistic, messy data + ground truth |
| `src/knowledge_base.py` | Generates the accounting knowledge base |
| `src/policy_rag.py` | RAG retrieval over the KB |
| `src/model.py` | Provider wrapper (OpenAI / mock) |
| `src/categorize.py` | Categorization agent — judgment only, no arithmetic |
| `src/reconcile.py` | Deterministic reconciliation engine |
| `src/evaluate.py` / `evaluate_kb.py` | Testing & evaluation harnesses |
| `src/app.py` | Streamlit dashboard |

## What's deliberately missing, and why

- **No fine-tuning** — disciplined prompting + retrieval + evaluation is a
  stronger, more auditable signal for this problem than a trained model.
- **AR/AP and inventory** aren't built — the same pattern (match an invoice
  to a payment; reconcile an inventory snapshot to recorded COGS) extends
  directly; scope was four sources deeply rather than seven shallowly.
- **RAG is a clean v1** — retrieval sits behind a small interface so it can
  be hardened later (retrieval eval, hybrid lexical+vector search,
  reranking, a feedback loop where human corrections become new KB entries).

See [`CASE_STUDY.md`](CASE_STUDY.md) for full methodology, design rationale,
and an honest discussion of where this would break on real-world data.
