"""Extend the point-in-time NIFTY 50 basket to the months the tracker lacks.

The reshuffle tracker stops at 2026-06. backtest_engine applies NO universe
filter for a month it cannot find (`pit_basket_dict.get(month, set())` is
falsy), so a missing month silently widens the universe from the 50 real
constituents to every CSV on disk -- 75 names, including delisted ones. This
fills the gap from ind_nifty50list.csv, the current NSE constituent list.

    python extend_pit_basket.py            # extend through the current month
    python extend_pit_basket.py 2026-09    # extend through a given month

Writes a NEW tracker file next to the source; the original is left alone.
"""
import os
import shutil
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = r"D:\files\data\NIFTY\nifty50_reshuffle_tracker_v2.xlsx"
OUT = os.path.join(ROOT, "nifty50_reshuffle_tracker_v2_extended.xlsx")
LIST_CSV = os.path.join(ROOT, "ind_nifty50list.csv")
SHEET = "Full Basket Per Month"


def main():
    through = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.today().strftime("%Y-%m")

    basket = pd.read_excel(SRC, sheet_name=SHEET)
    months = [c for c in basket.columns if c != "Stock #"]
    last = max(months)
    current = sorted(pd.read_csv(LIST_CSV)["Symbol"].astype(str).str.strip())

    if len(current) != 50:
        raise SystemExit(f"ind_nifty50list.csv has {len(current)} symbols, expected 50")

    prev = sorted(basket[last].dropna().astype(str).str.strip())
    added, dropped = set(current) - set(prev), set(prev) - set(current)
    print(f"tracker covers through {last}; current NSE list vs {last}: "
          f"+{sorted(added) or 'none'} -{sorted(dropped) or 'none'}")

    need = pd.period_range(pd.Period(last, "M") + 1, pd.Period(through, "M"), freq="M")
    if len(need) == 0:
        print("nothing to extend")
        return

    for m in need:
        basket[str(m)] = current
    print(f"added {len(need)} month(s): {', '.join(str(m) for m in need)}")

    shutil.copyfile(SRC, OUT)
    with pd.ExcelWriter(OUT, engine="openpyxl", mode="a",
                        if_sheet_exists="replace") as xl:
        basket.to_excel(xl, sheet_name=SHEET, index=False)
    print(f"wrote {OUT}")

    check = pd.read_excel(OUT, sheet_name=SHEET)
    for m in need:
        got = check[str(m)].dropna().astype(str).str.strip().tolist()
        assert sorted(got) == current, f"{m} did not round-trip"
    assert all(c in check.columns for c in months), "an original month was lost"
    print(f"verified: {len(check.columns) - 1} months, "
          f"{check[str(need[-1])].nunique()} names in {need[-1]}")


if __name__ == "__main__":
    main()
