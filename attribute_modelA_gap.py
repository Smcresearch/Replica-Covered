"""Why does Model A reproduce 0.94pp light while Model D reproduces exactly?

Runs Model A over the published window on three datasets:
  backup  - the nifty50 CSVs exactly as they were before the September refresh
  repaired- the refreshed CSVs (dividend back-adjustment + corporate-action fix)
  and reports which stocks the two disagree on.

Dividend back-adjustment rescales every price before an ex-date by the same
ratio, so it cannot change a return INSIDE a window that ends before the
ex-date. Any difference over 2021-02..2026-07 therefore has to come from the
three corporate-action repairs, not from the refresh itself.

    python attribute_modelA_gap.py
"""
import sys

import pandas as pd

sys.path.append(r"D:\DK_sir")
from src.backtest_engine import run_rolling_backtest       # noqa: E402
from src.data_loader import DataLoader                     # noqa: E402

CUTOFF = pd.Timestamp("2026-07-22")
SCRATCH = (r"C:\Users\PC2546\AppData\Local\Temp\claude\d--DK-sir-condor"
           r"\7e6e388d-1f4d-4414-b43f-11160df6e092\scratchpad")
BACKUP_WS = SCRATCH + r"\ws_backup"
TRACKER = r"D:\DK_sir\nifty50_reshuffle_tracker_v2_extended.xlsx"


def stats(daily_pct):
    r = daily_pct / 100.0
    nav = (1 + r).cumprod()
    cagr = nav.iloc[-1] ** (252.0 / len(r)) - 1
    return cagr * 100, (nav / nav.cummax() - 1).min() * 100


def run(workspace):
    loader = DataLoader(workspace_dir=workspace, reshuffle_file=TRACKER)
    _, sector_stock_map = loader.load_sector_mapping()
    pit = loader.load_pit_reshuffle_basket()
    aligned = loader.get_aligned_data(start_date="2020-01-01")
    aligned = aligned[aligned.index <= CUTOFF]
    cols = [c for c in aligned.columns if c not in ("Price", "Index_Return")]
    res, _, hist = run_rolling_backtest(
        returns_matrix=aligned[cols], index_returns=aligned["Index_Return"],
        sector_stock_map=sector_stock_map, lookback_days=252,
        rebalance_freq="monthly", alpha=0.001, model_type="lasso",
        pit_basket_dict=pit, cost_rate=0.003, use_macro=False)
    col = res.columns[0] if "Portfolio_Daily_Return_%" not in res.columns \
        else "Portfolio_Daily_Return_%"
    s = res[col]
    return stats(s if s.abs().max() > 1 else s * 100), hist


def main():
    out = {}
    for label, ws in (("backup", BACKUP_WS), ("repaired", r"d:\DK_sir")):
        (cagr, mdd), hist = run(ws)
        out[label] = dict(CAGR=round(cagr, 2), MDD=round(mdd, 2))
        print(f"{label:>9}: CAGR {cagr:6.2f}%   MDD {mdd:7.2f}%")

    print(f"\npublished: CAGR  22.44%   MDD  -21.47%")
    d = out["repaired"]["CAGR"] - out["backup"]["CAGR"]
    print(f"repair moved Model A by {d:+.2f}pp\n")

    # which return series actually differ inside the window
    print("stocks whose returns differ between the two datasets:")
    for sym in sorted(pd.read_csv(r"D:\DK_sir\ind_nifty50list.csv")["Symbol"]):
        try:
            a = pd.read_csv(f"{BACKUP_WS}\\nifty50\\{sym}_1d_max.csv",
                            usecols=["Date", "Close"])
            b = pd.read_csv(f"D:\\DK_sir\\nifty50\\{sym}_1d_max.csv",
                            usecols=["Date", "Close"])
        except FileNotFoundError:
            continue
        for f in (a, b):
            f["Date"] = pd.to_datetime(f["Date"], format="%d-%m-%Y", errors="coerce")
        a = a.dropna().set_index("Date").Close.pct_change().loc[:CUTOFF]
        b = b.dropna().set_index("Date").Close.pct_change().loc[:CUTOFF]
        j = pd.concat([a, b], axis=1, join="inner", keys=["old", "new"]).dropna()
        diff = (j.new - j.old).abs()
        if diff.max() > 1e-6:
            worst = diff.idxmax()
            print(f"  {sym:<12} {int((diff > 1e-6).sum()):>3} day(s) differ; "
                  f"worst {worst.date()} {j.old[worst]*100:+.2f}% -> {j.new[worst]*100:+.2f}%")


if __name__ == "__main__":
    main()
