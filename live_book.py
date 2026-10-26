"""The live book: what to hold this month, sized on Rs 1 crore.

Under the monthly rebalance rule the book is chosen on the first trading session
of the month from the trailing 252 sessions -- i.e. off data through the end of
the previous month. The month is read from the workbooks rather than hardcoded,
so this needs no edit when the month rolls over.

    python live_book.py              # whatever the latest rebalance is
    python live_book.py 2026-10      # pin a month (must be the latest rebalance)
"""
import sys

import pandas as pd

CAPITAL = 1e7
BOOKS = {
    "MODEL A": r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx",
    "MODEL D": r"D:\DK_sir\Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx",
}
WCOL = "Sector_Target_Weight_%"


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    sheets, dates = {}, set()

    for name, path in BOOKS.items():
        d = pd.read_excel(path, sheet_name="Current_Portfolio_Quantities")
        d = d[d[WCOL] > 0].copy()
        rebal = str(d["Rebalance_Date"].iloc[0])[:10]
        dates.add(rebal)
        if want and not rebal.startswith(want):
            raise SystemExit(f"{name}: latest rebalance is {rebal}, not {want}. "
                             f"Run rebuild_models.py first.")

        # Re-size from the sheet's weights onto the Rs 1 Cr mandate; the
        # workbook's own quantities use its native capital base.
        d["Alloc_INR"] = (d[WCOL] / 100.0 * CAPITAL).round(0)
        px = d["Stock_Price_INR"].where(d["Stock_Price_INR"] > 0)
        d["Qty"] = (d["Alloc_INR"] // px).fillna(0).astype(int)
        d["Cost_INR"] = (d["Qty"] * d["Stock_Price_INR"]).round(0)

        cols = ["Rebalance_Date", "Stock_Symbol", "Sector_Industry", WCOL,
                "Stock_Price_INR", "Alloc_INR", "Qty", "Cost_INR"]
        sheets[name] = d[cols].sort_values(WCOL, ascending=False).reset_index(drop=True)

    if len(dates) > 1:
        raise SystemExit(f"books disagree on the rebalance date: {sorted(dates)}")
    rebal = dates.pop()
    stamp = pd.Timestamp(rebal).strftime("%B_%Y")
    out = rf"D:\DK_sir\{stamp}_Book.xlsx"

    for name, d in sheets.items():
        print("=" * 84)
        print(f"{name}  |  rebalance {rebal}  |  {len(d)} stocks")
        print("=" * 84)
        print(d.drop(columns=["Rebalance_Date"]).to_string(index=False))
        print(f"  weight {d[WCOL].sum():6.2f}%   deployed Rs {d.Cost_INR.sum():,.0f}"
              f"   residual cash Rs {CAPITAL - d.Cost_INR.sum():,.0f}\n")

    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        for name, d in sheets.items():
            d.to_excel(xl, sheet_name=name.replace(" ", "_"), index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
