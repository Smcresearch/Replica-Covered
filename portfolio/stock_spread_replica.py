r"""Bull call spreads on the individual holdings, instead of owning the shares.

The index version (bull_spread_replica.py) answered its question clearly: a
monthly-rolled NIFTY spread captures a NEGATIVE share of the index move,
because twelve time premiums a year cost more than the index returns. This asks
whether the per-stock version is different -- it keeps the stock-selection
alpha, which is the whole point of the models, so in principle it has more to
work with.

For each monthly rebalance it takes the model's actual holdings and weights,
replaces each share position with a bull call spread on that stock at the same
notional, rolls at the monthly expiry, and compares the weighted result with
what the shares themselves did that month (which the workbook already records).

Credentials come from the environment -- never hardcode them, this repo is public:

    export QDB_HOST=... QDB_NAME=... QDB_USER=... QDB_PW=...
    python stock_spread_replica.py [months]
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
import psycopg2

warnings.filterwarnings("ignore")

MODEL_A = r"D:\DK_sir\Sparse_Lasso_Nifty50_Styled_Report.xlsx"
OUT = r"D:\DK_sir\portfolio\Stock_Spread_Replica.xlsx"
CAPITAL = 1e7
SLIP_PCT = 0.0025          # 0.25% of premium per leg, stock options are wider
COST_PCT = 0.005           # charge stack, as a fraction of premium turnover
#: long leg moneyness, short leg moneyness
GRID = [(0.00, 0.05), (0.00, 0.10), (-0.02, 0.05), (0.00, None)]

#: Every connection detail comes from the environment. This repo is public, so
#: the host and username stay out of the file along with the password.
CONN = dict(host=os.environ.get("QDB_HOST", ""), port=int(os.environ.get("QDB_PORT", 5432)),
            dbname=os.environ.get("QDB_NAME", ""), user=os.environ.get("QDB_USER", ""),
            password=os.environ.get("QDB_PW", ""))
TABLES = {"A_F": "ABCDEF", "G_L": "GHIJKL", "M_S": "MNOPQRS", "T_Z": "TUVWXYZ"}


def table_for(sym):
    first = sym[0].upper()
    for t, letters in TABLES.items():
        if first in letters:
            return f"Stock_Options_{t}"
    raise KeyError(sym)


def fetch(dates, symbols):
    """Entry chains and exit prices for every (symbol, roll date) pair.

    One query per option table. Pulls the near-monthly expiry only, and only
    strikes that actually traded, so an untradeable strike is never selected.
    """
    frames = []
    by_table = {}
    for s in symbols:
        by_table.setdefault(table_for(s), []).append(s)

    with psycopg2.connect(connect_timeout=20, **CONN) as c:
        for tbl, syms in by_table.items():
            sql = f'''
                select "Instrument", "Date"::text, "ExpiryDate"::text,
                       "Strike"::float strike, "Close"::float px, "Volume" vol,
                       "DaysToExpiry" dte
                from "{tbl}"
                where "Date" = any(%s::date[]) and "Instrument" = any(%s)
                  and "Type" = 'CE' and "Time" = '15:25:59'
                  and "DaysToExpiry" between 18 and 40 and "Volume" > 0
            '''
            frames.append(pd.read_sql(sql, c, params=(dates, syms)))
    return pd.concat(frames, ignore_index=True)


def exits(pairs):
    """Closing price of each chosen contract on its expiry day."""
    frames = []
    by_table = {}
    for sym, exp, strike in pairs:
        by_table.setdefault(table_for(sym), []).append((sym, exp, strike))

    with psycopg2.connect(connect_timeout=20, **CONN) as c:
        for tbl, rows in by_table.items():
            syms = sorted({r[0] for r in rows})
            exps = sorted({r[1] for r in rows})
            sql = f'''
                select "Instrument", "ExpiryDate"::text, "Strike"::float strike,
                       "Close"::float px
                from "{tbl}"
                where "Date" = any(%s::date[]) and "ExpiryDate" = any(%s::date[])
                  and "Instrument" = any(%s) and "Type" = 'CE'
                  and "Time" = '15:25:59' and "DaysToExpiry" = 0
            '''
            frames.append(pd.read_sql(sql, c, params=(exps, exps, syms)))
    d = pd.concat(frames, ignore_index=True)
    return d.set_index(["Instrument", "ExpiryDate", "strike"])["px"]


def nearest(chain, target):
    if chain.empty:
        return None
    i = (chain["strike"] - target).abs().idxmin()
    row = chain.loc[i]
    return row if abs(row["strike"] - target) < target * 0.035 else None


def main():
    missing = [k for k in ("host", "dbname", "user", "password") if not CONN[k]]
    if missing:
        raise SystemExit(
            "set QDB_HOST, QDB_NAME, QDB_USER and QDB_PW in the environment "
            f"(missing: {', '.join(missing)})")
    n_months = int(sys.argv[1]) if len(sys.argv) > 1 else 18

    h = pd.read_excel(MODEL_A, sheet_name="Monthly_Stock_Detail_With_Qty")
    h["Rebalance_Date"] = pd.to_datetime(h["Rebalance_Date"]).dt.strftime("%Y-%m-%d")
    rolls = sorted(h["Rebalance_Date"].unique())[-n_months:]
    h = h[h["Rebalance_Date"].isin(rolls)].copy()
    syms = sorted(h["Stock_Symbol"].unique())
    print(f"{len(rolls)} monthly rolls, {len(syms)} distinct names "
          f"({rolls[0]} .. {rolls[-1]})")

    chains = fetch(list(rolls), syms)
    if chains.empty:
        raise SystemExit("no option rows came back")
    # one expiry per (symbol, roll): the nearest monthly
    chains["key"] = chains["Instrument"] + "|" + chains["Date"]
    pick_exp = (chains.sort_values("dte").groupby("key")["ExpiryDate"].first())
    chains = chains[chains.apply(
        lambda r: pick_exp.get(r["key"]) == r["ExpiryDate"], axis=1)]
    print(f"entry chains: {len(chains):,} rows across "
          f"{chains['key'].nunique()} (name, roll) pairs")

    results = []
    for ml, ms in GRID:
        lab = (f"long {ml*100:+.0f}% / short {ms*100:+.0f}%" if ms is not None
               else f"long {ml*100:+.0f}% / naked long")
        chosen, rows = [], []
        for (sym, roll), g in h.groupby(["Stock_Symbol", "Rebalance_Date"]):
            ch = chains[(chains["Instrument"] == sym) & (chains["Date"] == roll)]
            if ch.empty:
                continue
            spot = float(g["Entry_Stock_Price_INR"].iloc[0])
            w = float(g["Sector_Target_Weight_%"].iloc[0])
            lo = nearest(ch, spot * (1 + ml))
            sh = nearest(ch, spot * (1 + ms)) if ms is not None else None
            if lo is None or (ms is not None and sh is None):
                continue
            exp = lo["ExpiryDate"]
            chosen.append((sym, exp, lo["strike"]))
            if sh is not None:
                chosen.append((sym, exp, sh["strike"]))
            rows.append(dict(sym=sym, roll=roll, exp=exp, w=w, spot=spot,
                             k_long=lo["strike"], p_long=lo["px"],
                             k_short=sh["strike"] if sh is not None else np.nan,
                             p_short=sh["px"] if sh is not None else 0.0,
                             stock_ret=float(g["Stock_Monthly_Return_%"].iloc[0])))
        if not rows:
            print(f"  {lab}: no usable pairs")
            continue

        ex = exits(sorted(set(chosen)))
        d = pd.DataFrame(rows)

        def out_px(r, which):
            k = r["k_long"] if which == "l" else r["k_short"]
            if not np.isfinite(k):
                return 0.0
            v = ex.get((r["sym"], r["exp"], k))
            if v is None:
                # no print on expiry day -> settle at intrinsic against the strike
                return max(r["spot"] * (1 + r["stock_ret"] / 100) - k, 0.0)
            return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)

        d["out_long"] = d.apply(lambda r: out_px(r, "l"), axis=1)
        d["out_short"] = d.apply(lambda r: out_px(r, "s"), axis=1)
        d["debit"] = d.p_long - d.p_short
        gross = (d.out_long - d.p_long) - (d.out_short - d.p_short)
        turnover = d.p_long + d.p_short + d.out_long + d.out_short
        d["net_pts"] = gross - turnover * (SLIP_PCT + COST_PCT)
        # return on the notional the position stands in for
        d["spread_ret"] = d.net_pts / d.spot * 100
        d["w_spread"] = d.spread_ret * d.w / 100
        d["w_stock"] = d.stock_ret * d.w / 100

        per_month = d.groupby("roll").agg(spread=("w_spread", "sum"),
                                          stock=("w_stock", "sum"),
                                          names=("sym", "size"),
                                          debit=("debit", "mean"))
        yrs = len(per_month) / 12.0
        results.append(dict(
            Structure=lab, Rolls=len(per_month), Pairs=len(d),
            Spread_pa=round(per_month.spread.sum() / yrs, 2),
            Shares_pa=round(per_month.stock.sum() / yrs, 2),
            Capture_pct=round(per_month.spread.sum() / per_month.stock.sum() * 100, 1),
            Spread_win=round((per_month.spread > 0).mean() * 100, 1),
            Shares_win=round((per_month.stock > 0).mean() * 100, 1),
            Avg_debit_pct=round((d.debit / d.spot * 100).mean(), 2)))
        print(f"  {lab:<30} {len(per_month)} rolls, {len(d)} positions")

    rep = pd.DataFrame(results)
    print("\n" + "=" * 118)
    print(rep.to_string(index=False))
    print("=" * 118)
    print("\nSpread_pa / Shares_pa: weighted return per year from the option "
          "structure versus from owning the shares, over the same rolls.")
    with pd.ExcelWriter(OUT, engine="openpyxl") as xl:
        rep.to_excel(xl, sheet_name="Summary", index=False)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
