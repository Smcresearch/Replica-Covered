"""The live September book: what to hold, sized on Rs 1 crore.

Reads the latest rebalance out of each regenerated workbook. Under the monthly
rebalance rule the September book is chosen on the first trading session of
September from the trailing 252 sessions, i.e. off data through 31 August.

    python september_book.py
"""
import pandas as pd

CAPITAL = 1e7
BOOKS = {
    "MODEL A": r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx",
    "MODEL D": r"D:\DK_sir\Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx",
}
WCOL = "Sector_Target_Weight_%"
OUT = r"D:\DK_sir\September_2026_Book.xlsx"


def main():
    sheets = {}
    for name, path in BOOKS.items():
        d = pd.read_excel(path, sheet_name="Current_Portfolio_Quantities")
        d = d[d[WCOL] > 0].copy()
        # Re-size from the sheet's weights onto the Rs 1 Cr mandate; the
        # workbook's own quantities use its native capital base (1 L / 1 Cr).
        d["Alloc_INR"] = (d[WCOL] / 100.0 * CAPITAL).round(0)
        px = d["Stock_Price_INR"].where(d["Stock_Price_INR"] > 0)
        d["Qty"] = (d["Alloc_INR"] // px).fillna(0).astype(int)
        d["Cost_INR"] = (d["Qty"] * d["Stock_Price_INR"]).round(0)

        cols = ["Rebalance_Date", "Stock_Symbol", "Sector_Industry", WCOL,
                "Stock_Price_INR", "Alloc_INR", "Qty", "Cost_INR"]
        d = d[cols].sort_values(WCOL, ascending=False).reset_index(drop=True)
        sheets[name] = d

        print("=" * 84)
        print(f"{name}  |  rebalance {d.Rebalance_Date.iloc[0]}  |  "
              f"{len(d)} stocks")
        print("=" * 84)
        print(d.drop(columns=["Rebalance_Date"]).to_string(index=False))
        cash = CAPITAL - d.Cost_INR.sum()
        print(f"  weight {d[WCOL].sum():6.2f}%   deployed Rs {d.Cost_INR.sum():,.0f}"
              f"   residual cash Rs {cash:,.0f}\n")

    with pd.ExcelWriter(OUT, engine="openpyxl") as xl:
        for name, d in sheets.items():
            d.to_excel(xl, sheet_name=name.replace(" ", "_"), index=False)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
