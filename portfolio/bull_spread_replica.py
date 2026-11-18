r"""Bull call spreads as a replacement for the equity leg -- NIFTY index version.

Tests the question: instead of buying Rs 1 crore of stock, get the long exposure
from a bull call spread rolled expiry to expiry. Same Rs 1 crore mandate as
everything else, so the result sits beside the equity books and the benchmark.

  entry   monthly expiry, 15:25. Buy a call at spot*(1+m_long), sell one at
          spot*(1+m_short) for the NEXT monthly expiry. m_long <= 0 is in the
          money for a call.
  size    lots = floor(1 Cr / (spot * lot size)), so index exposure matches the
          Rs 1 crore the equity book would have held. NOT sized to spend the
          whole crore on premium -- that would be leverage, not a comparison.
  exit    the next monthly expiry, 15:25, at traded prices.

Both legs are priced from the market at both ends; nothing is marked to
theoretical intrinsic. Costs follow the same model as the conditioned call:
0.25 index points of slippage per leg plus the Indian F&O charge stack.

A plain long call (no short leg) is included as the uncapped reference, and a
"+ idle cash" row because the spread ties up only its debit -- the rest of the
crore would really sit in liquid funds.

    python bull_spread_replica.py
"""
import numpy as np
import pandas as pd

from backtest_btst import charges, load
from conditioned_call import lot_size_for

CAPITAL = 1e7
SLIP = 0.25
CASH_YIELD = 0.06          # on the capital the spread does not tie up
ENTRY_T = "15:25:59"
START = "2021-02-01"       # the window every other book is measured over
#: strike tolerance when matching a target moneyness, as a fraction of spot
TOL = 0.006

#: (long moneyness, short moneyness). None short = plain long call, uncapped.
GRID = [
    (-0.05, 0.05), (-0.05, 0.10), (-0.05, None),
    (-0.02, 0.05), (-0.02, 0.10), (-0.02, None),
    (0.00, 0.05), (0.00, 0.10), (0.00, None),
]


def monthly_expiries(ce, days):
    """Last expiry of each calendar month that is itself a trading day.

    The ExpiryDate column carries unreliable far-dated labels (1980, 2050), so
    an expiry only counts when the data actually has that session.
    """
    exps = sorted(set(ce["ExpiryDate"]) & days)
    last = {}
    for e in exps:
        last[e[:7]] = max(last.get(e[:7], ""), e)
    return sorted(last.values())


def pick(chain, spot, m):
    """Nearest traded strike to the target moneyness, or None."""
    target = spot * (1 + m)
    c = chain[(chain["Strike"] - target).abs() < spot * TOL]
    if c.empty:
        return None
    c = c.loc[(c["Strike"] - target).abs().idxmin()]
    return c


def run(ce, spot, mon, m_long, m_short):
    by = {k: g for k, g in ce.groupby(["Date", "ExpiryDate"])}
    px = ce.set_index(["Date", "Ticker"])["Close"]
    rows = []
    for d, nxt in zip(mon, mon[1:]):
        if d < START or (d, nxt) not in by:
            continue
        chain, sp = by[(d, nxt)], spot[d]
        lo = pick(chain, sp, m_long)
        sh = pick(chain, sp, m_short) if m_short is not None else None
        if lo is None or (m_short is not None and sh is None):
            continue

        lot = lot_size_for(d)
        lots = int(CAPITAL // (sp * lot))
        qty = lots * lot
        if lots == 0:
            continue

        try:
            lo_out = float(px.loc[(nxt, lo["Ticker"])])
            sh_out = float(px.loc[(nxt, sh["Ticker"])]) if sh is not None else 0.0
        except KeyError:
            continue
        lo_in = float(lo["Close"])
        sh_in = float(sh["Close"]) if sh is not None else 0.0
        if not np.isfinite(lo_in) or lo_in <= 0:
            continue

        # long leg: buy to open, sell to close. short leg: the reverse.
        # slippage always against us.
        buy_in, sell_out = lo_in + SLIP, max(lo_out - SLIP, 0.0)
        legs = 1
        pts = sell_out - buy_in
        prem_buy, prem_sell = buy_in, sell_out
        if sh is not None:
            sell_in, buy_out = max(sh_in - SLIP, 0.0), sh_out + SLIP
            pts += sell_in - buy_out
            prem_buy += buy_out
            prem_sell += sell_in
            legs = 2
        cost = charges(prem_buy * qty, prem_sell * qty, n_lots=lots * legs)
        net = pts * qty - cost
        debit = (lo_in - sh_in) * qty

        rows.append(dict(Roll=d, Expiry=nxt, Spot=round(sp, 2),
                         K_long=lo["Strike"], K_short=sh["Strike"] if sh is not None else None,
                         Lot=lot, Lots=lots, Qty=qty,
                         Long_In=round(lo_in, 2), Long_Out=round(lo_out, 2),
                         Short_In=round(sh_in, 2), Short_Out=round(sh_out, 2),
                         Debit_Rs=round(debit), Debit_pct=round(debit / CAPITAL * 100, 2),
                         Gross_Pts=round(pts, 2), Cost_Rs=round(cost),
                         Net_Rs=round(net),
                         Notional_pct=round(qty * sp / CAPITAL * 100, 1)))
    return pd.DataFrame(rows)


def summarise(df, label, cash=False):
    if df.empty:
        return dict(Structure=label, Cycles=0)
    d = df.copy()
    if cash:
        # the crore the spread does not tie up, at a liquid-fund yield
        days = (pd.to_datetime(d.Expiry) - pd.to_datetime(d.Roll)).dt.days
        d["Net_Rs"] = d["Net_Rs"] + (CAPITAL - d["Debit_Rs"]) * CASH_YIELD * days / 365.0
    yrs = (pd.Timestamp(d.Expiry.iloc[-1]) - pd.Timestamp(d.Roll.iloc[0])).days / 365.25
    tot = d.Net_Rs.sum()
    curve = CAPITAL + d.Net_Rs.cumsum().values
    dd = (curve - np.maximum.accumulate(curve)) / CAPITAL * 100
    mr = d.Net_Rs.values / CAPITAL
    return dict(Structure=label, Cycles=len(d),
                Return_pa=round(tot / yrs / CAPITAL * 100, 2),
                Total_Rs=round(tot),
                Max_DD=round(float(dd.min()), 2),
                Win=round(float((d.Net_Rs > 0).mean() * 100), 1),
                Best=round(d.Net_Rs.max()), Worst=round(d.Net_Rs.min()),
                Avg_Debit_pct=round(d.Debit_pct.mean(), 2),
                Vol=round(float(mr.std(ddof=1) * np.sqrt(12) * 100), 2))


def main():
    s5, op = load()
    ent = op[op["Time"] == ENTRY_T]
    ce = ent[ent["Type"].astype(str).str.upper().str.startswith("C")]
    spot = s5[s5["Time"] == "15:25"].groupby("Date")["Close"].last()
    mon = monthly_expiries(ce, set(spot.index))
    print(f"monthly expiries usable: {len(mon)}  {mon[0]} .. {mon[-1]}\n")

    out, frames = [], {}
    for ml, ms in GRID:
        df = run(ce, spot, mon, ml, ms)
        lab = (f"long {ml*100:+.0f}% / short {ms*100:+.0f}%" if ms is not None
               else f"long {ml*100:+.0f}% / naked long")
        frames[lab] = df
        out.append(summarise(df, lab))
        out.append(summarise(df, lab + "  + idle cash", cash=True))
        print(f"  {lab:<32} {len(df):>3} cycles")

    rep = pd.DataFrame(out)
    print("\n" + "=" * 132)
    print(rep.to_string(index=False))
    print("=" * 132)

    path = r"D:\DK_sir\portfolio\Bull_Spread_Replica.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        rep.to_excel(xl, sheet_name="Summary", index=False)
        for lab, df in frames.items():
            if not df.empty:
                df.to_excel(xl, sheet_name=lab.replace("/", "-")[:31], index=False)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
