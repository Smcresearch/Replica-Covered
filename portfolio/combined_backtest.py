"""Model A and Model D, each with the conditioned covered call, on Rs 1 Cr.

Answers one question: which pairing is better. Writes a separate workbook per
book so the two can be circulated independently.

Mandate, as in the writeup: Rs 1,00,00,000 deployed and never grown. Each month
end the month's P&L is booked out and the book is reset to Rs 1 Cr. Returns are
therefore SIMPLE (profit / years / 1 Cr), not compounded, and drawdown is
measured on the cumulative booked-profit curve as a percentage of the Rs 1 Cr.

Equity cost drags are the writeup's, and are what puts the two books on a
common basis given Model A's workbook is gross of costs and Model D's is net:
Model A 1.317% p.a., Model D 0.225% p.a.

Lot sizing comes from conditioned_call.py, which carries the real NSE lot
history. BUILD_REPORTS.simulate() is NOT reused because it hardcodes LOT=65 --
the flat-lot bug that Correction 1 in the writeup's audit fixed.

CAVEAT: the option leg has no intraweek 300-point re-strike (see
conditioned_call.py), so every overlay figure here is a FLOOR.

    python combined_backtest.py
"""
import numpy as np
import pandas as pd

import conditioned_call as cc

CAPITAL = 1e7
RF = 0.0592
PARAMS = "walk-forward"          # the honest set; the note says plan on this
COST_PA = {"Model A": 0.01317, "Model D": 0.00225}
BOOKS = {
    "Model A": r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx",
    "Model D": r"D:\DK_sir\Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx",
}
START = "2021-02-01"


def equity(path, cost_pa):
    d = pd.read_excel(path, sheet_name="Daily_Performance")
    d["Date"] = pd.to_datetime(d["Date"])
    d = d[d["Date"] >= START][["Date", "Portfolio_Daily_Return_%"]].copy()
    d["Portfolio_Daily_Return_%"] -= cost_pa / 252 * 100
    return d.reset_index(drop=True)


def benchmark(path):
    """NIFTY 50 buy-and-hold, put through the SAME Rs 1 crore mandate.

    The note quotes NIFTY as a CAGR, which is the natural convention for a
    passive holding but is not comparable with a book that withdraws its profit
    every month. Running the index through the identical simulate() puts every
    curve on one basis. No cost drag: the benchmark is unlevered and uncosted.
    """
    d = pd.read_excel(path, sheet_name="Daily_Performance")
    d["Date"] = pd.to_datetime(d["Date"])
    d = d[d["Date"] >= START][["Date", "NIFTY50_Daily_Return_%"]].copy()
    return (d.rename(columns={"NIFTY50_Daily_Return_%": "Portfolio_Daily_Return_%"})
             .reset_index(drop=True))


def simulate(eq, trades):
    """Rs 1 Cr deployed, month P&L booked out, option P&L landing on exit day."""
    ret = eq["Portfolio_Daily_Return_%"].values / 100.0
    dates = eq["Date"]
    ym = dates.dt.to_period("M").values

    payout = {}
    if trades is not None and len(trades):
        for _, t in trades.iterrows():
            x = pd.Timestamp(t.Exit)
            payout[x] = payout.get(x, 0.0) + float(t.Net_Rs)

    book, month_opt, booked = CAPITAL, 0.0, 0.0
    curve = np.empty(len(ret))
    eq_d = np.zeros(len(ret))
    opt_d = np.zeros(len(ret))
    months = []

    for i in range(len(ret)):
        if i > 0 and ym[i] != ym[i - 1]:
            m_eq = book - CAPITAL
            months.append({"Month": str(ym[i - 1]), "Equity_PnL": m_eq,
                           "Option_PnL": month_opt,
                           "Total_PnL": m_eq + month_opt,
                           "Return_on_1Cr": (m_eq + month_opt) / CAPITAL})
            booked += m_eq + month_opt
            book, month_opt = CAPITAL, 0.0

        prev = book
        book *= (1 + ret[i])
        eq_d[i] = book - prev

        p = payout.get(dates[i])
        if p is not None:
            month_opt += p
            opt_d[i] = p

        curve[i] = CAPITAL + booked + (book - CAPITAL) + month_opt

    m_eq = book - CAPITAL
    months.append({"Month": str(ym[-1]), "Equity_PnL": m_eq,
                   "Option_PnL": month_opt, "Total_PnL": m_eq + month_opt,
                   "Return_on_1Cr": (m_eq + month_opt) / CAPITAL})

    daily = pd.DataFrame({"Date": dates, "Equity_PnL": eq_d.round(0),
                          "Option_PnL": opt_d.round(0),
                          "Ledger": curve.round(0)})
    return curve, daily, pd.DataFrame(months)


def stats(dates, curve, months, label):
    yrs = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    total = curve[-1] - CAPITAL
    ann_pct = total / yrs / CAPITAL
    mr = months["Return_on_1Cr"].values
    vol = mr.std(ddof=1) * np.sqrt(12)
    dd = (curve - np.maximum.accumulate(curve)) / CAPITAL
    mdd = float(dd.min())
    return {"Book": label, "Years": round(yrs, 2),
            "Return_pa_%": round(ann_pct * 100, 2),
            "Total_Profit_Rs": round(total),
            "Max_DD_%": round(mdd * 100, 2),
            "Vol_%": round(vol * 100, 2),
            "Sharpe": round((ann_pct - RF) / vol, 2) if vol else np.nan,
            "CAR_MDD": round(ann_pct / abs(mdd), 2) if mdd else np.nan,
            "Worst_Month_%": round(mr.min() * 100, 2),
            "Best_Month_%": round(mr.max() * 100, 2),
            "Win_Months_%": round((mr > 0).mean() * 100, 1),
            "N_Months": len(mr)}


def yearly(months):
    m = months.copy()
    m["Year"] = m["Month"].str[:4]
    return (m.groupby("Year")
            .agg(Equity_PnL=("Equity_PnL", "sum"),
                 Option_PnL=("Option_PnL", "sum"),
                 Total_PnL=("Total_PnL", "sum"))
            .round(0)
            .assign(Return_on_1Cr_pct=lambda x: (x.Total_PnL / CAPITAL * 100).round(2))
            .reset_index())


def main():
    s5, op = cc.load()
    trades = cc.run(PARAMS, s5, op)
    trades = trades[trades.Entry >= START].reset_index(drop=True)
    print(f"option leg: {len(trades)} cycles, {trades.Entry.min()} .. "
          f"{trades.Exit.max()}  ({PARAMS} params)\n")

    bm = benchmark(BOOKS["Model A"])           # same series in both workbooks
    cb, db, mb = simulate(bm, None)
    sb = stats(bm["Date"], cb, mb, "NIFTY 50 (buy & hold)")
    nav = (1 + bm["Portfolio_Daily_Return_%"] / 100).prod()
    yrs = (bm["Date"].iloc[-1] - bm["Date"].iloc[0]).days / 365.25
    sb["CAGR_%"] = round((nav ** (1 / yrs) - 1) * 100, 2)
    print(f"benchmark: NIFTY 50 {sb['Return_pa_%']:.2f}%/yr on the mandate basis "
          f"({sb['CAGR_%']:.2f}% CAGR buy-and-hold), DD {sb['Max_DD_%']:.2f}%\n")

    summary = [sb]
    for name, path in BOOKS.items():
        eq = equity(path, COST_PA[name])

        c0, d0, m0 = simulate(eq, None)          # book alone
        c1, d1, m1 = simulate(eq, trades)        # book + conditioned call

        s0 = stats(eq["Date"], c0, m0, f"{name} only")
        s1 = stats(eq["Date"], c1, m1, f"{name} + conditioned call")
        summary += [s0, s1]

        out = (rf"D:\DK_sir\portfolio\Backtest_{name.replace(' ', '')}"
               rf"_CoveredCall.xlsx")
        with pd.ExcelWriter(out, engine="openpyxl") as xl:
            pd.DataFrame([s0, s1, sb]).to_excel(xl, sheet_name="Summary", index=False)
            mb.assign(**{c: mb[c].round(0) for c in
                         ("Equity_PnL", "Option_PnL", "Total_PnL")},
                      Return_on_1Cr_pct=(mb.Return_on_1Cr * 100).round(2)) \
              .drop(columns=["Return_on_1Cr"]) \
              .to_excel(xl, sheet_name="Benchmark_Monthly", index=False)
            db.to_excel(xl, sheet_name="Benchmark_Daily", index=False)
            yearly(m1).to_excel(xl, sheet_name="Yearly", index=False)
            m1.assign(**{c: m1[c].round(0) for c in
                         ("Equity_PnL", "Option_PnL", "Total_PnL")},
                      Return_on_1Cr_pct=(m1.Return_on_1Cr * 100).round(2)) \
              .drop(columns=["Return_on_1Cr"]) \
              .to_excel(xl, sheet_name="Monthly", index=False)
            d1.to_excel(xl, sheet_name="Daily_Ledger", index=False)
            trades.to_excel(xl, sheet_name="Option_Trade_Log", index=False)
            pd.DataFrame([
                ("Mandate", "Rs 1 Cr deployed, P&L booked out monthly, "
                            "no compounding"),
                ("Return_pa_%", "simple: total profit / years / Rs 1 Cr"),
                ("Max_DD_%", "on the cumulative booked-profit curve, "
                             "as % of Rs 1 Cr"),
                ("Equity cost drag", f"{COST_PA[name]*100:.3f}% p.a. applied daily"),
                ("Option params", f"{PARAMS} (base/C from conditioned_call.py)"),
                ("CAVEAT", "no intraweek 300pt re-strike -- overlay P&L is a FLOOR"),
            ], columns=["Field", "Meaning"]).to_excel(
                xl, sheet_name="Notes", index=False)
        print(f"wrote {out}")

    rep = pd.DataFrame(summary)
    print("\n" + "=" * 118)
    print(rep.to_string(index=False))
    print("=" * 118)

    a = rep[rep.Book.str.startswith("Model A") & rep.Book.str.contains("cond")].iloc[0]
    d = rep[rep.Book.str.startswith("Model D") & rep.Book.str.contains("cond")].iloc[0]
    print(f"\nModel A + call : {a['Return_pa_%']:.2f}%/yr, DD {a['Max_DD_%']:.2f}%, "
          f"Sharpe {a['Sharpe']:.2f}, CAR/MDD {a['CAR_MDD']:.2f}")
    print(f"Model D + call : {d['Return_pa_%']:.2f}%/yr, DD {d['Max_DD_%']:.2f}%, "
          f"Sharpe {d['Sharpe']:.2f}, CAR/MDD {d['CAR_MDD']:.2f}")
    rep.to_csv(r"D:\DK_sir\portfolio\combined_backtest_summary.csv", index=False)


if __name__ == "__main__":
    main()
