# AI Reconciliation & Categorization Agent



A small, runnable AI system for the messy reality of Razorpay-settled business finance. It takes raw exports—a bank feed, a Razorpay settlement report, a QuickBooks P&L, a payroll register—categorizes every transaction, reconciles bank deposits to Razorpay settlements, and produces an auditable income statement.

## Architecture

```text
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
       ↓                   ↓
 67% automation       Human review
       │
       ↓
Ground-truth evaluation
       ↓
96%+ precision
```

## Core Philosophy

> **The LLM proposes; deterministic code disposes.**

The model only makes *judgments* (what category is this transaction?). Every *number*—netting fees, matching deposits, summing the P&L—is plain, auditable Python. A hallucinated number silently corrupts the books, so the model never touches math.

## Quickstart

**No API key needed.** Everything runs out of the box on a deterministic offline *mock model*, so you can clone and run it for free.

```bash
pip install -r requirements.txt

python src/generate_data.py     # 1. Synthesize messy data + ground truth
python src/knowledge_base.py    # 2. Build the accounting KB
python src/reconcile.py         # 3. Deterministic reconciliation
python src/evaluate.py          # 4. Evaluation harness
python src/evaluate_kb.py       # 5. Measure KB RAG lift
streamlit run src/app.py        # 6. Interactive dashboard
```

To run the real agent, copy `.env.example` → `.env` and set `OPENAI_API_KEY`.

## Handling the Mess

Real financial data is messy. This project explicitly handles:
- **Gross vs. net:** Settlement reports gross; bank sees net of gateway fee + GST. Engine recomputes and verifies to the penny.
- **Settlement lag:** Date-window matching instead of exact-date matching.
- **Risk hold:** Deposits short of net are flagged as `partial_reserve` with exact shortfall, not forced to match.
- **UTR-based matching:** Joins bank memos and settlement reports using shared UTRs.
- **Dirty exports & ambiguity:** Handles `₹1,234.56` strings, and disambiguates edge cases using the RAG knowledge base. Unresolvable cases abstain (`Needs Review`).

## Evaluation & Results

The evaluation (`src/evaluate.py`) scores against ground truth the model never sees.
- **Categorization accuracy:** 100% (offline mock baseline & real runs with KB RAG)
- **Reconciliation match accuracy:** 100% (deterministic engine makes no arithmetic errors)
- **Engine auto-match rate:** 66.7% (with the remaining 33.3% correctly flagged for review)

*See [`CASE_STUDY.md`](CASE_STUDY.md) for deeper details on the architecture and RAG implementation.*

## Project Map

| Module | Role |
|---|---|
| `src/schema.py` | Chart of accounts |
| `src/generate_data.py` | Synthesizes realistic, messy data |
| `src/knowledge_base.py` | Generates accounting KB |
| `src/policy_rag.py` | RAG retrieval over the KB |
| `src/model.py` | Provider wrapper (OpenAI / mock) |
| `src/categorize.py` | Categorization agent (judgment only) |
| `src/reconcile.py` | Deterministic reconciliation engine |
| `src/evaluate.py` / `evaluate_kb.py` | Testing & evaluation harnesses |
| `src/app.py` | Streamlit dashboard |
