"""Statement Insight: the logic. No Streamlit in here, so it can be tested and reused.

Pipeline:  load_statement -> categorize (LLM) -> summarize (pandas) -> narrate (LLM)
Rule of thumb: the LLM reads and writes words; pandas does every calculation.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()
MODEL = "gemini-3.1-flash-lite"
CACHE_FILE = Path("category_cache.json")   # keep this out of git: it holds your narrations

Category = Literal[
    "food_delivery", "groceries", "transport", "bills", "shopping", "entertainment",
    "health", "investments", "loan_emi", "income", "cash", "transfers", "other",
]
CATEGORIES = list(get_args(Category))
NOT_SPENDING = {"investments", "income"}    # money out that isn't "spent"


# ---------------------------------------------------------------------------
# 1. LOAD: turn any bank's CSV into the same four columns
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    "date": ["date", "txn date", "transaction date", "value date", "value dt"],
    "narration": ["narration", "description", "particulars", "remarks", "transaction details"],
    "withdrawal": ["withdrawal", "withdrawal amt.", "withdrawal amount", "debit", "debit amount", "dr"],
    "deposit": ["deposit", "deposit amt.", "deposit amount", "credit", "credit amount", "cr"],
}


def _to_amount(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


DATE_FORMATS = ["%d/%m/%y", "%d/%m/%Y", "%d-%m-%Y", "%d-%m-%y", "%d-%b-%y", "%d-%b-%Y", "%d %b %Y", "%Y-%m-%d"]


def _to_dates(series: pd.Series) -> pd.Series:
    """Try common Indian bank formats first (day before month), then fall back."""
    text = series.astype(str).str.strip()
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        if parsed.notna().mean() > 0.9:
            return parsed
    return pd.to_datetime(text, dayfirst=True, errors="coerce", format="mixed")


def load_statement(file) -> pd.DataFrame:
    raw = pd.read_csv(file)
    by_lower = {str(c).strip().lower(): c for c in raw.columns}
    picked = {}
    for name, aliases in COLUMN_ALIASES.items():
        match = next((by_lower[a] for a in aliases if a in by_lower), None)
        if match is None:
            raise ValueError(f"Couldn't find a '{name}' column. Columns in your file: {list(raw.columns)}")
        picked[name] = match

    df = pd.DataFrame({
        "date": _to_dates(raw[picked["date"]]),
        "narration": raw[picked["narration"]].astype(str).str.strip(),
        "withdrawal": _to_amount(raw[picked["withdrawal"]]),
        "deposit": _to_amount(raw[picked["deposit"]]),
    })
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. CATEGORIZE: dedupe, then batch, then cache
#    150 rows usually come from ~30 merchants, so this is ONE LLM call, not 150.
# ---------------------------------------------------------------------------
def narration_key(narration: str) -> str:
    """Remove reference numbers so repeat payments to the same merchant match.
    'UPI/DR/431122334455/SWIGGY/...' and 'UPI/DR/998877665544/SWIGGY/...' -> same key."""
    return re.sub(r"\d{5,}", "#", narration).upper().strip()


class CategorizedItem(BaseModel):
    id: int
    merchant: str
    category: Category


class CategorizedBatch(BaseModel):
    items: list[CategorizedItem]


CATEGORIZE_PROMPT = """You categorize Indian bank statement narrations.
Each input line is "<id>: <narration>". For EVERY line, return its id, a short clean
merchant or payer name (for example "Swiggy", "Airtel", "Rahul Sharma"), and one category.

Categories:
- food_delivery: Swiggy, Zomato and other restaurant orders
- groceries: Blinkit, Zepto, BigBasket, DMart, supermarkets
- transport: cabs, autos, trains, flights, fuel
- bills: phone, electricity, gas, internet, DTH
- shopping: Amazon, Flipkart, Myntra and other retail
- entertainment: OTT subscriptions, movies, music
- health: pharmacies, hospitals, clinics
- investments: SIPs, mutual funds, brokers, PPF, FDs
- loan_emi: loan and EMI repayments
- income: salary, refunds, interest, cashback, money received from anyone
- cash: ATM withdrawals
- transfers: money sent to a person, including rent paid to a person
- other: fits none of the above

Return exactly one item per input line. Never skip a line."""


@lru_cache
def get_client() -> genai.Client:
    return genai.Client()


def categorize_with_llm(keys: list[str]) -> dict[str, dict]:
    """One LLM call for a batch. Returns {key: {"merchant", "category"}} for the items it got back."""
    lines = "\n".join(f"{i}: {k}" for i, k in enumerate(keys))
    response = get_client().models.generate_content(
        model=MODEL,
        contents=lines,
        config=types.GenerateContentConfig(
            system_instruction=CATEGORIZE_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            response_schema=CategorizedBatch,
        ),
    )
    batch = response.parsed
    got = {item.id: item for item in (batch.items if batch else [])}
    # Never trust the count: check every id came back, and only keep valid ones.
    return {k: {"merchant": got[i].merchant, "category": got[i].category}
            for i, k in enumerate(keys) if i in got}


def _load_cache() -> dict:
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def categorize(df: pd.DataFrame, llm=categorize_with_llm, batch_size: int = 60) -> pd.DataFrame:
    cache = _load_cache()
    keys = df["narration"].map(narration_key)
    todo = [k for k in dict.fromkeys(keys) if k not in cache]   # unique, in order, not cached yet

    for start in range(0, len(todo), batch_size):
        cache.update(llm(todo[start:start + batch_size]))
        CACHE_FILE.write_text(json.dumps(cache, indent=1))       # save after every batch

    out = df.copy()
    out["merchant"] = keys.map(lambda k: cache.get(k, {}).get("merchant", "Unknown"))
    out["category"] = keys.map(lambda k: cache.get(k, {}).get("category", "other"))
    return out


# ---------------------------------------------------------------------------
# 3. SUMMARIZE: plain pandas. The LLM never does arithmetic.
# ---------------------------------------------------------------------------
def summarize(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["month"] = df["date"].dt.strftime("%Y-%m")
    spending = df[(df["withdrawal"] > 0) & (~df["category"].isin(NOT_SPENDING))]
    invested = df.loc[df["category"] == "investments", "withdrawal"].sum()

    income = float(df["deposit"].sum())
    spent = float(spending["withdrawal"].sum())
    monthly = pd.DataFrame({
        "income": df.groupby("month")["deposit"].sum(),
        "spent": spending.groupby("month")["withdrawal"].sum(),
    }).fillna(0.0).round(2)

    return {
        "period": f"{df['date'].min():%d %b %Y} to {df['date'].max():%d %b %Y}",
        "total_income": round(income, 2),
        "total_spent": round(spent, 2),
        "total_invested": round(float(invested), 2),
        "savings_rate_pct": round(100 * (income - spent - invested) / income, 1) if income else None,
        "by_category": spending.groupby("category")["withdrawal"].sum().sort_values(ascending=False).round(2).to_dict(),
        "top_merchants": spending.groupby("merchant")["withdrawal"].sum().nlargest(5).round(2).to_dict(),
        "by_month": monthly.to_dict(orient="index"),
    }


# ---------------------------------------------------------------------------
# 4. NARRATE: the LLM turns numbers into words, and is told not to invent any
# ---------------------------------------------------------------------------
NARRATE_PROMPT = """You write a short spending summary for the account holder.
Use ONLY the numbers in the JSON you are given. Never invent or estimate a figure.
Write 4 bullet points in plain, friendly English, using rupees with Indian digit grouping
(for example Rs 1,23,456). Cover: overall income vs spending, the biggest spending category,
a month-to-month change worth noticing, and one practical suggestion."""


def narrate(summary: dict) -> str:
    response = get_client().models.generate_content(
        model=MODEL,
        contents=json.dumps(summary),
        config=types.GenerateContentConfig(system_instruction=NARRATE_PROMPT, temperature=0.3),
    )
    return response.text


def format_inr(amount: float) -> str:
    """1234567 -> 'Rs 12,34,567' (Indian grouping: last 3 digits, then pairs)."""
    digits = f"{abs(amount):.0f}"
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        pairs = [head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1]
        digits = ",".join(pairs) + "," + tail
    return ("-" if amount < 0 else "") + "Rs " + digits
