"""Tests for statement_core. Run:  uv run pytest -v
None of these call Gemini."""

import io

import pandas as pd
import pytest

import statement_core
from statement_core import categorize, format_inr, load_statement, narration_key, summarize

CSV = """Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/10/26,NEFT/CR/111111111111/ACME TECHNOLOGIES/SALARY,,"85,000.00","1,27,000.00"
03/10/26,UPI/DR/222222222222/SWIGGY/YESB/swiggy@ybl,450.00,,"1,26,550.00"
04/10/26,UPI/DR/333333333333/SWIGGY/YESB/swiggy@ybl,"1,250.00",,"1,25,300.00"
05/10/26,ACH/444444444444/GROWW SIP MUTUAL FUND,"5,000.00",,"1,20,300.00"
"""


def fake_llm(keys):
    fake_llm.calls += 1
    result = {}
    for k in keys:
        if "SWIGGY" in k: result[k] = {"merchant": "Swiggy", "category": "food_delivery"}
        elif "SALARY" in k: result[k] = {"merchant": "Acme Technologies", "category": "income"}
        elif "GROWW" in k: result[k] = {"merchant": "Groww", "category": "investments"}
    return result


@pytest.fixture
def df(tmp_path, monkeypatch):
    monkeypatch.setattr(statement_core, "CACHE_FILE", tmp_path / "cache.json")   # never touch the real cache
    fake_llm.calls = 0
    return categorize(load_statement(io.StringIO(CSV)), llm=fake_llm)


def test_load_parses_indian_amounts_and_day_first_dates():
    loaded = load_statement(io.StringIO(CSV))
    assert loaded.loc[2, "withdrawal"] == 1250.0
    assert loaded.loc[0, "deposit"] == 85000.0
    assert loaded.loc[0, "date"] == pd.Timestamp("2026-10-01")   # 1 October, not 10 January


def test_load_explains_a_missing_column():
    with pytest.raises(ValueError, match="narration"):
        load_statement(io.StringIO("Date,Amount\n01/10/26,500\n"))


def test_reference_numbers_dont_split_one_merchant():
    a = narration_key("UPI/DR/222222222222/SWIGGY/YESB/swiggy@ybl")
    b = narration_key("UPI/DR/333333333333/SWIGGY/YESB/swiggy@ybl")
    assert a == b


def test_one_llm_call_for_all_unique_merchants(df):
    assert fake_llm.calls == 1                 # 4 rows, 3 unique merchants, 1 batch
    assert set(df["category"]) == {"income", "food_delivery", "investments"}


def test_cache_means_no_second_call(df):
    categorize(df[["date", "narration", "withdrawal", "deposit"]], llm=fake_llm)
    assert fake_llm.calls == 1                 # still 1: everything came from the cache


def test_summary_totals(df):
    s = summarize(df)
    assert s["total_income"] == 85000.0
    assert s["total_spent"] == 1700.0          # Swiggy only; the SIP is investing, not spending
    assert s["total_invested"] == 5000.0
    assert s["by_category"] == {"food_delivery": 1700.0}


def test_format_inr_uses_indian_grouping():
    assert format_inr(1234567) == "Rs 12,34,567"
    assert format_inr(85000) == "Rs 85,000"
    assert format_inr(450) == "Rs 450"
