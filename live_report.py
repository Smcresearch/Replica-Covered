"""Live monthly report: holdings marked to market, option logs, month-to-date.

One workbook answering three questions:
  what do I hold and what is it worth now   -> Model_A / Model_D holdings, each
                                               row buy price vs current price
  how has the month gone                    -> MTD sheet, books vs NIFTY
  what did the option legs do               -> condor and conditioned-call logs

Buy price is the 2026-09-01 rebalance price (chosen off data through 31 Aug);
current price is the last close on disk.

    python live_report.py
"""
import pandas as pd

CAPITAL = 1e7
MONTH_START = "2026-09-01"
NIFTY_DIR = r"D:\DK_sir\nifty50"

BOOKS = {
    "Model A": r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx",
    "Model D": r"D:\DK_sir\Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx",
}
WCOL = "Sector_Target_Weight_%"
CONDOR = r"D:\DK_sir_condor\combined_portfolio_report.xlsx"
CONDITIONED = r"D:\DK_sir\portfolio\Conditioned_Call_Updated.xlsx"


def last_close(sym):
    """Latest close on disk, and its date."""
    d = pd.read_csv(f"{NIFTY_DIR}\\{sym}_1d_max.csv", usecols=["Date", "Close"])
    d["Date"] = pd.to_datetime(d["Date"], format="%d-%m-%Y", errors="coerce")
    d = d.dropna().sort_values("Date")
    return float(d["Close"].iloc[-1]), d["Date"].iloc[-1]


def rebalance_month():
    """First day of the month the live book was struck, from the workbooks."""
    seen = set()
    for path in BOOKS.values():
        d = pd.read_excel(path, sheet_name="Current_Portfolio_Quantities")
        seen.add(str(d["Rebalance_Date"].iloc[0])[:10])
    if len(seen) > 1:
        raise SystemExit(f"books disagree on the rebalance date: {sorted(seen)}")
    return seen.pop()


def holdings(path):
    d = pd.read_excel(path, sheet_name="Current_Portfolio_Quantities")
    d = d[d[WCOL] > 0].copy()
    d["Alloc_INR"] = (d[WCOL] / 100.0 * CAPITAL).round(0)
    d["Buy_Price"] = d["Stock_Price_INR"]
    d["Qty"] = (d["Alloc_INR"] // d["Buy_Price"].where(d["Buy_Price"] > 0)) \
        .fillna(0).astype(int)

    cur, asof = zip(*(last_close(s) for s in d["Stock_Symbol"]))
    d["Current_Price"] = [round(c, 2) for c in cur]
    d["As_Of"] = [a.strftime("%Y-%m-%d") for a in asof]

    d["Cost_INR"] = (d["Qty"] * d["Buy_Price"]).round(0)
    d["Value_INR"] = (d["Qty"] * d["Current_Price"]).round(0)
    d["PnL_INR"] = (d["Value_INR"] - d["Cost_INR"]).round(0)
    d["PnL_Pct"] = ((d["Current_Price"] / d["Buy_Price"] - 1) * 100).round(2)

    cols = ["Stock_Symbol", "Sector_Industry", WCOL, "Qty", "Buy_Price",
            "Current_Price", "As_Of", "Cost_INR", "Value_INR", "PnL_INR",
            "PnL_Pct"]
    return (d[cols].sort_values("PnL_INR", ascending=False)
            .reset_index(drop=True)
            .rename(columns={WCOL: "Weight_Pct",
                             "Stock_Symbol": "Symbol",
                             "Sector_Industry": "Sector"}))


def mtd(MONTH_START):
    """Month-to-date return of each book against NIFTY, from the daily series."""
    rows, series = [], {}
    for name, path in BOOKS.items():
        d = pd.read_excel(path, sheet_name="Daily_Performance")
        d["Date"] = pd.to_datetime(d["Date"])
        m = d[d["Date"] >= MONTH_START].copy()
        p = (1 + m["Portfolio_Daily_Return_%"] / 100).prod() - 1
        n = (1 + m["NIFTY50_Daily_Return_%"] / 100).prod() - 1
        # The engine credits the new book with the rebalance day's own move, so
        # it assumes execution at the prior close. The holdings sheets mark from
        # the rebalance-day close instead, and this second figure is the one
        # that reconciles with them.
        after = m[m["Date"] > MONTH_START]
        p2 = (1 + after["Portfolio_Daily_Return_%"] / 100).prod() - 1
        rows.append(dict(Book=name, Sessions=len(m),
                         From=m["Date"].min().date(), To=m["Date"].max().date(),
                         MTD_Pct=round(p * 100, 2),
                         NIFTY_MTD_Pct=round(n * 100, 2),
                         Excess_pp=round((p - n) * 100, 2),
                         Since_Rebal_Pct=round(p2 * 100, 2),
                         Rebal_Day_Pct=round(
                             m["Portfolio_Daily_Return_%"].iloc[0], 2),
                         MTD_on_1Cr_INR=round(p * CAPITAL),
                         Best_Day=round(m["Portfolio_Daily_Return_%"].max(), 2),
                         Worst_Day=round(m["Portfolio_Daily_Return_%"].min(), 2),
                         Up_Days=int((m["Portfolio_Daily_Return_%"] > 0).sum())))
        series[name] = m.set_index("Date")[
            ["Portfolio_Daily_Return_%", "NIFTY50_Daily_Return_%"]]
    return pd.DataFrame(rows), series


def condor_log():
    out = {}
    for sheet, label in [("Combo 1 (1.4-2.2 Sigma) Details", "Condor_1.4-2.2s"),
                         ("Combo 2 (2.0-2.2 Sigma) Details", "Condor_2.0-2.2s")]:
        d = pd.read_excel(CONDOR, sheet_name=sheet)
        d["Entry_Date"] = pd.to_datetime(d["Entry_Date"]).dt.date
        d["Expiry"] = pd.to_datetime(d["Expiry"]).dt.date
        d = d[["Expiry", "Entry_Date", "Condors", "Adds", "Spot_Entry",
               "Spot_Settle", "Net_PnL", "Combined_PnL", "Combined_Eq"]]
        for c in ("Spot_Entry", "Spot_Settle", "Net_PnL", "Combined_PnL",
                  "Combined_Eq"):
            d[c] = d[c].round(2)
        out[label] = d
    return out


def main():
    MONTH_START = rebalance_month()
    stamp = pd.Timestamp(MONTH_START).strftime("%B_%Y")
    label = pd.Timestamp(MONTH_START).strftime("%B %Y")
    OUT_REPLICA = rf"D:\DK_sir\Replica_{stamp}.xlsx"
    OUT_CALL = rf"D:\DK_sir\Covered_Call_{stamp}.xlsx"

    hold = {n: holdings(p) for n, p in BOOKS.items()}
    perf, series = mtd(MONTH_START)
    condors = condor_log()
    cc = pd.read_excel(CONDITIONED, sheet_name="full_sample")
    cc_mon = cc[cc["Entry"] >= MONTH_START]
    print(f"month: {label}  (rebalanced {MONTH_START})")

    print("=" * 96)
    print("MONTH TO DATE")
    print("=" * 96)
    print(perf.to_string(index=False))

    for name, d in hold.items():
        print(f"\n{name}: {len(d)} stocks | cost Rs {d.Cost_INR.sum():,.0f} "
              f"-> value Rs {d.Value_INR.sum():,.0f} | "
              f"P&L Rs {d.PnL_INR.sum():,.0f} "
              f"({d.PnL_INR.sum()/d.Cost_INR.sum()*100:+.2f}%)")
        print(f"   best  {d.iloc[0].Symbol} {d.iloc[0].PnL_Pct:+.2f}%   "
              f"worst {d.iloc[-1].Symbol} {d.iloc[-1].PnL_Pct:+.2f}%   "
              f"{int((d.PnL_INR > 0).sum())}/{len(d)} in profit")

    cyc1 = condors["Condor_1.4-2.2s"]
    cyc1 = cyc1[cyc1.Entry_Date >= pd.Timestamp(MONTH_START).date()]
    print(f"\nCondor 1.4/2.2s cycles this month: {len(cyc1)}, "
          f"net Rs {cyc1.Net_PnL.sum():,.0f}")
    print(f"Conditioned call cycles this month: {len(cc_mon)}, "
          f"net Rs {cc_mon.Net_Rs.sum():,.0f}")

    notes = pd.DataFrame([
        ("Buy_Price", f"close on the {MONTH_START} rebalance, chosen off data "
                      f"through the prior month end"),
        ("Current_Price", "last close on disk (see As_Of column)"),
        ("MTD_Pct", f"compounded daily return from {MONTH_START} inclusive"),
        ("Since_Rebal_Pct", "same but excluding the rebalance day's own "
                            "return - this is what reconciles with the "
                            "holdings sheets"),
        ("Holdings P&L vs Since_Rebal_Pct",
         "small residual is whole-share rounding plus uninvested cash"),
        ("Condor log", "Net_PnL is the option leg per cycle; Combined_PnL "
                       "adds the EMA BTST leg"),
        ("Conditioned_Call_Log", "entry strike and sizing reconcile to the "
                                 "writeup; P&L is a FLOOR - the intraweek "
                                 "300pt re-strike is not implemented"),
    ], columns=["Field", "Meaning"])

    # 1. the equity replica: what is held, at what price, worth what now
    with pd.ExcelWriter(OUT_REPLICA, engine="openpyxl") as xl:
        perf.to_excel(xl, sheet_name="MTD_Summary", index=False)
        for name, d in hold.items():
            d.to_excel(xl, sheet_name=name.replace(" ", "_") + "_Holdings",
                       index=False)
        for name, d in series.items():
            d.round(4).to_excel(xl, sheet_name=name.replace(" ", "_") + "_Daily")
        notes[notes.Field.isin(["Buy_Price", "Current_Price", "MTD_Pct",
                                "Since_Rebal_Pct",
                                "Holdings P&L vs Since_Rebal_Pct"])].to_excel(
            xl, sheet_name="Notes", index=False)
    print(f"\nwrote {OUT_REPLICA}")

    # 2. the option overlay: conditioned call plus the two condor variants
    with pd.ExcelWriter(OUT_CALL, engine="openpyxl") as xl:
        cc_sum = pd.read_excel(CONDITIONED, sheet_name="Summary")
        cc_sum.to_excel(xl, sheet_name="Summary", index=False)
        cc.to_excel(xl, sheet_name="Conditioned_Call_Log", index=False)
        cc_mon.to_excel(xl, sheet_name="Cycles_This_Month", index=False)
        for label, d in condors.items():
            d.to_excel(xl, sheet_name=label[:31], index=False)
        notes[notes.Field.isin(["Condor log", "Conditioned_Call_Log"])].to_excel(
            xl, sheet_name="Notes", index=False)
    print(f"wrote {OUT_CALL}")


if __name__ == "__main__":
    main()
