"""Statement Insight: the Streamlit app.
Run it:  uv run streamlit run app.py
"""

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from statement_core import categorize, format_inr, load_statement, narrate, summarize

st.set_page_config(page_title="Statement Insight", layout="wide")
st.title("Statement Insight")
st.caption("Upload a bank statement CSV and see where your money goes. "
           "This is a public demo: please use the sample statement, not your real one.")

SAMPLE = Path("sample_statement.csv")


@st.cache_data(show_spinner=False)
def analyse(file_bytes: bytes):
    df = load_statement(io.BytesIO(file_bytes))
    df = categorize(df)
    return df, summarize(df)


# ---- 1. Get a file ----------------------------------------------------------
uploaded = st.file_uploader("Bank statement (CSV)", type="csv")
if st.button("Try it with the sample statement"):
    st.session_state["use_sample"] = True

if uploaded is not None:
    data = uploaded.getvalue()
elif st.session_state.get("use_sample") and SAMPLE.exists():
    data = SAMPLE.read_bytes()
else:
    st.info("Upload a CSV with date, narration, withdrawal and deposit columns, or try the sample statement.")
    st.stop()

# ---- 2. Analyse it ----------------------------------------------------------
try:
    with st.spinner("Reading and categorizing your transactions..."):
        df, s = analyse(data)
except ValueError as e:
    st.error(f"I couldn't read that file. {e}")
    st.stop()
except Exception as e:
    st.error(f"Categorization failed ({type(e).__name__}). If it's a rate limit, wait a minute and try again.")
    st.stop()

# ---- 5. AI summary (one LLM call, only when asked) --------------------------
st.markdown("**AI summary**")
if st.button("Write my summary"):
    try:
        with st.spinner("Writing..."):
            st.markdown(narrate(s))
    except Exception as e:
        st.error(f"Couldn't write the summary ({type(e).__name__}). Try again in a minute.")

        
# ---- 3. Headline numbers ----------------------------------------------------
st.subheader(s["period"])
c1, c2, c3, c4 = st.columns(4)
c1.metric("Income", format_inr(s["total_income"]))
c2.metric("Spent", format_inr(s["total_spent"]))
c3.metric("Invested", format_inr(s["total_invested"]))
c4.metric("Saved", f'{s["savings_rate_pct"]}%' if s["savings_rate_pct"] is not None else "n/a")

# ---- 4. Charts --------------------------------------------------------------
left, right = st.columns(2)
with left:
    st.markdown("**Spending by category (Rs)**")
    st.bar_chart(pd.Series(s["by_category"], name="Rs"), horizontal=True)
with right:
    st.markdown("**Income vs spending by month (Rs)**")
    st.bar_chart(pd.DataFrame(s["by_month"]).T, stack=False)

st.markdown("**Top 5 places your money went**")
st.dataframe(
    pd.DataFrame({"Merchant": list(s["top_merchants"]),
                  "Spent": [format_inr(v) for v in s["top_merchants"].values()]}),
    hide_index=True, use_container_width=True,
)



# ---- 6. Every transaction ---------------------------------------------------
with st.expander("All transactions"):
    picked = st.multiselect("Filter by category", sorted(df["category"].unique()))
    view = df[df["category"].isin(picked)] if picked else df
    st.dataframe(view[[df["date"].dt.date, "narration", "merchant", "category", "withdrawal", "deposit"]],
                 hide_index=True, use_container_width=True)
