"""Regenerate the Model A / Model D workbooks on the refreshed data.

Nothing in the tree wrote these two files any more (they were orphaned July
artefacts), so this restores the driver. Settings are the ones that reproduce
the published numbers -- see reproduce_models.py:

  Model A  lasso,        alpha=0.001, use_macro=False, GROSS of costs
  Model D  shrinkage_qp, alpha=0.001, use_macro=True,  NET of 0.30% turnover

The gross/net asymmetry is deliberate and pre-existing: the stored Model A
workbook reproduces on the gross series (max drawdown matches to -21.47%
exactly), Model D on the net series (17.86% / -16.41% to the decimal). The
portfolio layer downstream re-imposes a cost drag on each -- 1.317% p.a. for
Model A, 0.225% for Model D -- to bring them onto a common basis, so changing
the convention here would double-count. Running Model A at cost_rate=0 makes
its net series identical to its gross one, which is what the workbook expects.

    python rebuild_models.py                # through the latest data on disk
    python rebuild_models.py 2026-08-31     # freeze at a month end
"""
import sys

import pandas as pd

sys.path.append(r"D:\DK_sir")
from src.backtest_engine import run_rolling_backtest       # noqa: E402
from src.data_loader import DataLoader                     # noqa: E402
from src.excel_reporter import generate_excel_report       # noqa: E402

MODELS = {
    "Model A": dict(out=r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx",
                    model_type="lasso", use_macro=False,
                    cost_rate=0.0,      # workbook convention: gross
                    capital=100_000.0),
    "Model D": dict(out=r"D:\DK_sir\Sparse_Lasso_Nifty50_Model_D_Macro_Report.xlsx",
                    model_type="shrinkage_qp", use_macro=True,
                    cost_rate=0.003,    # workbook convention: net
                    capital=10_000_000.0),
}


def stats(r):
    nav = (1 + r).cumprod()
    return (nav.iloc[-1] ** (252.0 / len(r)) - 1) * 100, \
           (nav / nav.cummax() - 1).min() * 100


def main():
    cutoff = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else None

    loader = DataLoader(workspace_dir=r"d:\DK_sir")
    stock_sector_map, sector_stock_map = loader.load_sector_mapping()
    pit = loader.load_pit_reshuffle_basket()
    prices, _ = loader.load_stock_prices(start_year=2019)
    aligned = loader.get_aligned_data(start_date="2020-01-01")
    if cutoff is not None:
        aligned = aligned[aligned.index <= cutoff]
    cols = [c for c in aligned.columns if c not in ("Price", "Index_Return")]
    returns_matrix, index_returns = aligned[cols], aligned["Index_Return"]

    print(f"\ndata {returns_matrix.index.min().date()} .. "
          f"{returns_matrix.index.max().date()}  "
          f"({len(returns_matrix)} sessions)\n")

    for name, m in MODELS.items():
        print(f"--- {name} ---")
        results_df, metrics, hist = run_rolling_backtest(
            returns_matrix=returns_matrix, index_returns=index_returns,
            sector_stock_map=sector_stock_map, lookback_days=252,
            rebalance_freq="monthly", alpha=0.001, model_type=m["model_type"],
            pit_basket_dict=pit, cost_rate=m["cost_rate"],
            use_macro=m["use_macro"])

        cagr, mdd = stats(results_df["Portfolio_Return"])
        last = hist[-1]
        print(f"  CAGR {cagr:.2f}%   MDD {mdd:.2f}%   "
              f"rebalances {len(hist)}   avg stocks "
              f"{sum(h['num_stocks'] for h in hist) / len(hist):.1f}")
        print(f"  last rebalance {pd.Timestamp(last['date']).date()} "
              f"-> {last['num_stocks']} stocks")

        generate_excel_report(
            results_df=results_df, metrics=metrics, rebalance_history=hist,
            elbow_df=None, stock_sector_map=stock_sector_map,
            returns_matrix=returns_matrix, prices_df=prices,
            output_path=m["out"], initial_capital=m["capital"])
        print(f"  wrote {m['out']}\n")


if __name__ == "__main__":
    main()
