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

#: NSE index reviews that fall after the tracker ends, keyed by the first month
#: the new composition applies to a rebalance. The rebalance runs on the first
#: trading session of the month, so a change effective 30-Sep-2026 first bites
#: on the 1-Oct book -- hence "2026-10", not "2026-09".
#:
#: Carrying the last tracked basket forward blindly is wrong whenever a review
#: lands in between, and it fails silently: the book simply keeps holding a
#: name that has left the index. Add a line per review.
RESHUFFLES = {
    # announced 2026-08-10, effective after the close on 2026-09-29
    "2026-10": {"in": ["BSE"], "out": ["WIPRO"]},
}


def main():
    through = sys.argv[1] if len(sys.argv) > 1 else pd.Timestamp.today().strftime("%Y-%m")

    basket = pd.read_excel(SRC, sheet_name=SHEET)
    months = [c for c in basket.columns if c != "Stock #"]
    last = max(months)
    known = set(pd.read_csv(LIST_CSV)["Symbol"].astype(str).str.strip())

    need = pd.period_range(pd.Period(last, "M") + 1, pd.Period(through, "M"), freq="M")
    if len(need) == 0:
        print("nothing to extend")
        return

    # Roll the last tracked basket forward, applying each review as it lands.
    comp = sorted(basket[last].dropna().astype(str).str.strip())
    print(f"tracker covers through {last} with {len(comp)} names")
    built = {}
    for m in need:
        rs = RESHUFFLES.get(str(m))
        if rs:
            comp = sorted((set(comp) - set(rs["out"])) | set(rs["in"]))
            print(f"  {m}: +{rs['in']} −{rs['out']}")
        else:
            print(f"  {m}: carried forward")
        if len(comp) != 50:
            raise SystemExit(f"{m} basket has {len(comp)} names, expected 50")
        missing = sorted(set(comp) - known)
        if missing:
            # Without a sector mapping a name can never be selected, so the book
            # would quietly run 49 stocks and nobody would see why.
            raise SystemExit(f"{m}: {missing} not in ind_nifty50list.csv — "
                             f"add them (with industry) or they are unselectable")
        built[str(m)] = list(comp)
        basket[str(m)] = comp
    print(f"added {len(need)} month(s)")

    shutil.copyfile(SRC, OUT)
    with pd.ExcelWriter(OUT, engine="openpyxl", mode="a",
                        if_sheet_exists="replace") as xl:
        basket.to_excel(xl, sheet_name=SHEET, index=False)
    print(f"wrote {OUT}")

    check = pd.read_excel(OUT, sheet_name=SHEET)
    for m in need:
        got = check[str(m)].dropna().astype(str).str.strip().tolist()
        assert sorted(got) == sorted(built[str(m)]), f"{m} did not round-trip"
    assert all(c in check.columns for c in months), "an original month was lost"
    print(f"verified: {len(check.columns) - 1} months, "
          f"{check[str(need[-1])].nunique()} names in {need[-1]}")


if __name__ == "__main__":
    main()
