"""Creates sample_statement.csv: three months of realistic, made-up transactions.
Run once:  uv run make_sample_statement.py
"""

import random
from datetime import date, timedelta

import pandas as pd

rng = random.Random(2026)
ref = lambda: rng.randint(100000000000, 999999999999)

FIXED = [  # (day of month, narration, withdrawal, deposit)
    (1, "NEFT/CR/{r}/ACME TECHNOLOGIES/SALARY", 0, 85000),
    (3, "IMPS/P2A/{r}/MOHAN RENTALS", 18000, 0),
    (5, "ACH/{r}/GROWW SIP MUTUAL FUND", 5000, 0),
    (5, "ACH/{r}/ZERODHA BROKING", 3000, 0),
    (10, "ACH/{r}/BAJAJ FINANCE EMI", 6450, 0),
    (12, "BBPS/{r}/AIRTEL POSTPAID", 599, 0),
    (14, "BBPS/{r}/MSEDCL ELECTRICITY", 0, 0),        # amount set below
    (15, "SI/{r}/NETFLIX COM", 649, 0),
    (15, "SI/{r}/SPOTIFY INDIA", 119, 0),
    (20, "BBPS/{r}/MAHANAGAR GAS", 0, 0),
]

RANDOM = [  # (narration, min, max, times per month)
    ("UPI/DR/{r}/SWIGGY/YESB/swiggy@ybl", 180, 650, 9),
    ("UPI/DR/{r}/ZOMATO LTD/HDFC/zomato@hdfcbank", 200, 700, 6),
    ("UPI/DR/{r}/BLINKIT/ICIC/blinkit@icici", 150, 900, 5),
    ("UPI/DR/{r}/ZEPTO MARKETPLACE/AXIS/zepto@axisbank", 120, 800, 4),
    ("POS/{r}/DMART AVENUE SUPERMARTS/PUNE", 900, 3200, 1),
    ("UPI/DR/{r}/UBER INDIA/AXIS/uber@axisbank", 120, 480, 6),
    ("UPI/DR/{r}/RAPIDO/YESB/rapido@ybl", 60, 180, 5),
    ("CARD/{r}/AMAZON PAY INDIA/BANGALORE", 300, 4500, 2),
    ("CARD/{r}/FLIPKART INTERNET/BANGALORE", 500, 6000, 1),
    ("UPI/DR/{r}/APOLLO PHARMACY/HDFC/apollo@hdfcbank", 150, 1200, 1),
    ("ATM/{r}/CASH WDL/FC ROAD PUNE", 2000, 5000, 1),
    ("UPI/DR/{r}/PRIYA KULKARNI/SBIN/priya.k@oksbi", 200, 1500, 1),
]

ONE_OFF = [
    (date(2026, 8, 22), "UPI/DR/{r}/IRCTC/SBIN/irctc@sbi", 2340, 0),
    (date(2026, 9, 18), "CARD/{r}/INDIGO AIRLINES/GURGAON", 6890, 0),
    (date(2026, 9, 25), "UPI/CR/{r}/RAHUL SHARMA/SBIN/rahul.s@oksbi", 0, 1200),
    (date(2026, 10, 9), "CARD/{r}/MYNTRA DESIGNS/BANGALORE", 3499, 0),
    (date(2026, 10, 14), "IMPS/CR/{r}/MYNTRA DESIGNS/REFUND", 0, 3499),
    (date(2026, 10, 20), "UPI/DR/{r}/BOOKMYSHOW/ICIC/bookmyshow@icici", 840, 0),
    (date(2026, 10, 28), "CARD/{r}/RUBY HALL CLINIC/PUNE", 1500, 0),
]

rows = []
for month in (8, 9, 10):
    for day, text, wd, dp in FIXED:
        if "MSEDCL" in text: wd = rng.randint(1100, 2400)
        if "MAHANAGAR" in text: wd = rng.randint(450, 900)
        rows.append((date(2026, month, day), text, wd, dp))
    for text, lo, hi, times in RANDOM:
        for _ in range(times):
            rows.append((date(2026, month, rng.randint(1, 30 if month != 8 else 31)), text, rng.randint(lo, hi), 0))
rows += ONE_OFF
rows.sort(key=lambda r: r[0])

balance, out = 42000.0, []
for d, text, wd, dp in rows:
    balance += dp - wd
    out.append({
        "Date": d.strftime("%d/%m/%y"),
        "Narration": text.format(r=ref()),
        "Withdrawal Amt.": f"{wd:,.2f}" if wd else "",
        "Deposit Amt.": f"{dp:,.2f}" if dp else "",
        "Closing Balance": f"{balance:,.2f}",
    })

pd.DataFrame(out).to_csv("sample_statement.csv", index=False)
print(f"Wrote sample_statement.csv with {len(out)} transactions")
