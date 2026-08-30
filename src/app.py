"""Streamlit dashboard — makes the system tangible in 30 seconds.

Three views that mirror how a finance operator would actually use this:
  - Categorization: every transaction, its predicted category, confidence, and
    the similar past transactions that informed it (the RAG memory, made visible).
  - Reconciliation: each deposit matched to its payout, with penny-level
    discrepancies and the audit trail.
  - Review queue: exactly the items the system was NOT confident enough to
    auto-post — the human-in-the-loop surface.

Run:  streamlit run src/app.py
By default it uses the offline mock model so it's instant and free; set an
OPENAI_API_KEY in .env to run the real agent.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

import agent as ops_agent
from categorize import build_memory_from_golden, categorize_one, load_bank_feed
from model import USING_MOCK
from policy_rag import KnowledgeBaseIndex
from reconcile import reconcile, summarize
from schema import income_statement_section

AUTO_APPROVE = 0.75

st.set_page_config(page_title="AI Reconciliation Agent", layout="wide")

# Inject Custom CSS for premium UI
try:
    with open(os.path.join(os.path.dirname(__file__), "style.css")) as f:
        st.markdown(f"<style>\n{f.read()}\n</style>", unsafe_allow_html=True)
except Exception:
    pass


@st.cache_data(show_spinner="Categorizing transactions…")
def categorize_all() -> pd.DataFrame:
    feed = load_bank_feed()
    memory = build_memory_from_golden(holdout_ids=set())  # demo: use all history
    kb = KnowledgeBaseIndex()                             # RAG over accounting policy
    rows = []
    for r in feed:
        res = categorize_one(r["description"], memory=memory, kb=kb)
        pb = res.get("policy_basis")
        rows.append({
            "txn_id": r["txn_id"], "date": r["date"], "description": r["description"],
            "amount": r["amount"], "category": res["category"],
            "confidence": round(res["confidence"], 2),
            "section": income_statement_section(res["category"]),
            "auto_post": res["confidence"] >= AUTO_APPROVE and res["category"] != "Needs Review",
            "cited_rule": f'{pb["doc_id"]}: {pb["title"]}' if pb else "—",
            "rationale": res["rationale"],
        })
    return pd.DataFrame(rows)


@st.cache_data(show_spinner="Reconciling deposits…")
def reconcile_all() -> tuple[pd.DataFrame, dict]:
    # cache bust 2
    ms, payouts = reconcile()
    df = pd.DataFrame([{
        "txn_id": m.txn_id, "deposit_amount": m.deposit_amount, "payout_id": m.payout_id,
        "expected_net": m.expected_net, "discrepancy": m.discrepancy,
        "status": m.status, "note": m.note,
    } for m in ms])
    return df, summarize(ms, payouts)


# Inject Custom CSS for premium UI
st.markdown("""
<style>
    /* Premium Dashboard Styling */
    div[data-testid="stSidebar"] {
        background-color: transparent;
        border-right: 1px solid rgba(128,128,128, 0.2);
    }
    div[data-testid="stMetricValue"] {
        font-size: 28px !important;
        font-weight: 700 !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 14px !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-matched { background-color: #e6f4ea; color: #137333; }
    .badge-review { background-color: #fef7e0; color: #b06000; }
    .badge-unmatched { background-color: #fce8e6; color: #c5221f; }
</style>
""", unsafe_allow_html=True)

st.title("AI Finance Controller")
mode = "🔌 Offline mock model" if USING_MOCK else f"🤖 {os.getenv('APP_LLM_MODEL')}"
st.caption(f"{mode}  ·  The LLM judges & plans; all arithmetic & matching is deterministic code.")

cat_df = categorize_all()
rec_df, rec_summary = reconcile_all()

# Sidebar Navigation
st.sidebar.title("ReconcileAI")
page = st.sidebar.radio("Navigation", [
    "Overview Dashboard", 
    "Reconciliation", 
    "Manual Review", 
    "General Ledger", 
    "Ask the Agent"
])

def color_confidence(val):
    if val >= 0.9: return 'color: #137333;'
    if val >= 0.75: return 'color: #b06000;'
    return 'color: #c5221f;'

def highlight_status(val):
    if val == "matched": return 'background-color: #e6f4ea; color: #137333;'
    if val == "partial_reserve": return 'background-color: #fef7e0; color: #b06000;'
    return 'background-color: #fce8e6; color: #c5221f;'

if page == "Overview Dashboard":
    # Custom CSS exclusively for these premium cards
    st.markdown("""
    <style>
    .metric-card {
        padding: 24px;
        border-radius: 12px;
        color: white;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin-bottom: 24px;
        font-family: 'Inter', sans-serif;
    }
    .card-green { background: linear-gradient(135deg, #74b886, #439358); }
    .card-purple { background: linear-gradient(135deg, #a78bfa, #8b5cf6); }
    .card-blue { background: linear-gradient(135deg, #93c5fd, #3b82f6); }
    .card-red { background: linear-gradient(135deg, #fca5a5, #ef4444); }
    .card-title { font-size: 1.1rem; font-weight: 500; opacity: 0.9; margin-bottom: 8px; }
    .card-value { font-size: 2.8rem; font-weight: 700; margin: 0; line-height: 1.1; letter-spacing: -1px; }
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.markdown(f"""
        <div class="metric-card card-green">
            <div class="card-title">Automatically Reconciled</div>
            <div class="card-value">{rec_summary['auto_matched_pct']:.0f}%</div>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        unreconciled = int((~cat_df["auto_post"]).sum())
        st.markdown(f"""
        <div class="metric-card card-purple">
            <div class="card-title">Pending Review</div>
            <div class="card-value">{unreconciled}</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        var = rec_summary.get('unexplained_variance', 0)
        color = "card-red" if var > 0 else "card-blue"
        st.markdown(f"""
        <div class="metric-card {color}">
            <div class="card-title">Unexplained Variance</div>
            <div class="card-value">₹{var:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)
        
    st.subheader("Cash Position Drill-Down")
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Expected Cash (Razorpay)", f"₹{rec_summary.get('expected_cash', 0):,.2f}")
    cc2.metric("Actual Cash Received", f"₹{rec_summary.get('actual_cash', 0):,.2f}")
    cc3.metric("Total Processed", f"{len(cat_df)} Txns")
    
    st.divider()
    st.subheader("⚠️ Priority Action Items (Reserve Holds)")
    unmatched_preview = rec_df[rec_df["status"] != "matched"].head(6)
    if not unmatched_preview.empty:
        st.dataframe(unmatched_preview.style.map(highlight_status, subset=['status']), use_container_width=True, hide_index=True)
    else:
        st.success("All clear! No pending reconciliation exceptions.")

elif page == "Reconciliation":
    st.subheader("Bank Reconciliation")
    
    st.caption("Discrepancy is `deposit − expected_net`, computed to the penny. Non-zero rows are flagged, never silently accepted.")
    
    # Split view approximation
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("**Bank Transactions (Deposits)**")
        # Display matched deposits
        bank_view = rec_df[['txn_id', 'deposit_amount', 'status', 'discrepancy']].copy()
        st.dataframe(bank_view.style.map(highlight_status, subset=['status']), use_container_width=True, hide_index=True)
    
    with col2:
        st.markdown("**Expected Payments (Razorpay)**")
        # Display payouts matched
        payout_view = rec_df[['payout_id', 'expected_net']].copy()
        st.dataframe(payout_view, use_container_width=True, hide_index=True)

elif page == "Manual Review":
    review = cat_df[~cat_df["auto_post"]]
    unmatched = rec_df[rec_df["status"] != "matched"]
    
    st.subheader(f"Transactions Pending Review ({len(review)})")
    st.caption("The system declined to auto-post these — a cheap 'I'm not sure' beats an expensive wrong post.")
    
    display_cols = ["txn_id", "description", "category", "confidence", "rationale"]
    st.dataframe(review[display_cols].style.map(color_confidence, subset=['confidence']),
                 use_container_width=True, hide_index=True)
                 
    st.subheader(f"Deposits Needing Attention ({len(unmatched)})")
    st.dataframe(unmatched.style.map(highlight_status, subset=['status']), use_container_width=True, hide_index=True)

elif page == "General Ledger":
    st.subheader("Income Statement")
    st.caption("Rolled up from auto-categorized transactions. Numbers are summed in code, not by the model.")
    signed = cat_df.copy()
    signed["amount_num"] = signed["amount"].str.replace(",", "", regex=False).astype(float)
    pnl = signed.groupby("section")["amount_num"].sum().reindex(
        ["Revenue", "Cost of Goods Sold", "Operating Expense", "Other / Below the line"]).fillna(0)
    
    # Bar chart
    import plotly.graph_objects as go
    colors = ["#439358", "#ef4444", "#f59e0b", "#6b7280"]
    fig = go.Figure(go.Bar(
        x=pnl.index.tolist(),
        y=pnl.values.tolist(),
        marker_color=colors,
        text=[f"₹{v:,.0f}" for v in pnl.values],
        textposition="outside",
    ))
    fig.update_layout(title="P&L by Section", yaxis_title="₹ Amount",
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter"), height=380)
    st.plotly_chart(fig, use_container_width=True)
    
    st.dataframe(pnl.rename("amount").reset_index().rename(columns={"section": "P&L section"}),
                 use_container_width=True, hide_index=True)
    op_income = pnl.get("Revenue", 0) + pnl.get("Cost of Goods Sold", 0) + pnl.get("Operating Expense", 0)
    color = "normal" if op_income > 0 else "inverse"
    st.metric("Operating Income", f"₹{op_income:,.2f}", delta="Profitable ✓" if op_income > 0 else "Loss ✗", delta_color=color)

elif page == "Ask the Agent":
    st.subheader("Settlement Q&A Agent")
    st.caption("A multi-step agent: it plans which tools to call (ledger lookups, policy search), "
               "runs them, and composes the answer. Numbers come from tools — never invented by the LLM.")
    
    st.markdown("**Try a demo question:**")
    presets = [
        "What was my revenue by channel, and is operating income positive or negative?",
        "How much did I spend on advertising vs software subscriptions?",
        "What is the total amount held in Razorpay reserve holds?",
        "Summarise my cash position for the quarter.",
    ]
    cols = st.columns(2)
    for i, p in enumerate(presets):
        if cols[i % 2].button(p, key=f"preset_{i}", use_container_width=True):
            st.session_state["agent_q"] = p

    q = st.text_input("Or type your own question", 
                      value=st.session_state.get("agent_q", presets[0]),
                      key="agent_input")
    if st.button("Ask the agent", type="primary") and q:
        with st.spinner("Agent planning & calling tools…"):
            out = ops_agent.run(q)
        st.markdown("**Answer**")
        st.info(out["answer"])
        if out["trace"]:
            with st.expander("🔧 Tool calls the agent made"):
                for t in out["trace"]:
                    st.code(f"{t['tool']}({t['args']}) → {t['result']}", language="json")
