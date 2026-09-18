"""Reproduce the stored Model A / Model D workbooks before extending them.

Nothing in the tree writes Sparse_Lasso_Nifty50_Styled_Report.xlsx or
Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx any more -- they are orphaned
July artefacts, and every figure in the Conditioned Covered Call writeup traces
back to them. Before regenerating them on fresher data, check that the current
engine still lands on the published numbers over the SAME window.

Also settles which way the point-in-time filter was actually run: the workbooks
claim "Survivorship Bias Check PASSED", but the tracker path they defaulted to
(D:\\share_live\\NIFTY) no longer exists, and a missing tracker silently
disables the filter entirely.

    python reproduce_models.py
"""
import sys

import numpy as np
import pandas as pd

sys.path.append(r"D:\DK_sir")
from src.backtest_engine import run_rolling_backtest       # noqa: E402
from src.data_loader import DataLoader                     # noqa: E402

CUTOFF = pd.Timestamp("2026-07-22")          # last row in both stored workbooks
TARGET = {
    "Model A": dict(path=r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx",
                    cagr=22.44, mdd=-21.47, model_type="lasso", use_macro=False,
                    capital=100_000.0),
    "Model D": dict(path=r"D:\DK_sir\Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx",
                    cagr=17.86, mdd=-16.41, model_type="shrinkage_qp", use_macro=True,
                    capital=10_000_000.0),
}


def stats(daily_pct):
    """CAGR and max drawdown from a daily % return series."""
    r = daily_pct / 100.0
    nav = (1 + r).cumprod()
    yrs = len(r) / 252.0
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    mdd = (nav / nav.cummax() - 1).min()
    return cagr * 100, mdd * 100


def load_universe():
    loader = DataLoader(workspace_dir=r"d:\DK_sir")
    _, sector_stock_map = loader.load_sector_mapping()
    pit = loader.load_pit_reshuffle_basket()
    aligned = loader.get_aligned_data(start_date="2020-01-01")
    aligned = aligned[aligned.index <= CUTOFF]
    cols = [c for c in aligned.columns if c not in ("Price", "Index_Return")]
    return sector_stock_map, pit, aligned[cols], aligned["Index_Return"]


def main():
    sector_stock_map, pit, returns_matrix, index_returns = load_universe()
    print(f"\nwindow {returns_matrix.index.min().date()} .. "
          f"{returns_matrix.index.max().date()}  ({len(returns_matrix)} sessions, "
          f"{returns_matrix.shape[1]} tickers on disk)\n")

    rows = []
    for name, t in TARGET.items():
        stored = pd.read_excel(t["path"], sheet_name="Daily_Performance")
        s_cagr, s_mdd = stats(stored["Portfolio_Daily_Return_%"])

        for pit_on in (True, False):
            res, _, hist = run_rolling_backtest(
                returns_matrix=returns_matrix,
                index_returns=index_returns,
                sector_stock_map=sector_stock_map,
                lookback_days=252, rebalance_freq="monthly", alpha=0.001,
                model_type=t["model_type"],
                pit_basket_dict=pit if pit_on else None,
                cost_rate=0.003, use_macro=t["use_macro"],
            )
            col = ("Portfolio_Daily_Return_%" if "Portfolio_Daily_Return_%"
                   in res.columns else res.columns[0])
            c, m = stats(res[col] if res[col].abs().max() > 1 else res[col] * 100)
            rows.append(dict(Model=name, PIT="on" if pit_on else "off",
                             CAGR=round(c, 2), MDD=round(m, 2),
                             Stocks=round(np.mean([h["num_stocks"] for h in hist]), 1),
                             Pub_CAGR=t["cagr"], Pub_MDD=t["mdd"],
                             Stored_CAGR=round(s_cagr, 2), Stored_MDD=round(s_mdd, 2)))

    rep = pd.DataFrame(rows)
    rep["dCAGR"] = (rep.CAGR - rep.Pub_CAGR).round(2)
    rep["dMDD"] = (rep.MDD - rep.Pub_MDD).round(2)
    print("\n" + "=" * 100)
    print(rep.to_string(index=False))
    print("=" * 100)
    for name in TARGET:
        sub = rep[rep.Model == name]
        best = sub.loc[sub.dCAGR.abs().idxmin()]
        print(f"{name}: closest to published is PIT {best.PIT} "
              f"(dCAGR {best.dCAGR:+.2f}pp, dMDD {best.dMDD:+.2f}pp)")
    rep.to_csv(r"D:\DK_sir\reproduce_models_result.csv", index=False)
    print("\nwrote reproduce_models_result.csv")


if __name__ == "__main__":
    main()
