r"""Conditioned covered call -- the volatility-responsive NIFTY call overlay.

Reconstructed from the specification in Conditioned_Covered_Call_Writeup.html;
the original generator is not in the tree. The rule, verbatim from the note:

  Friday 15:25   z = 14-day realised vol of NIFTY, z-scored on its own trailing
                 252 sessions, clipped +/-3.
  Friday 15:25   K = Spot + base + C * z, rounded UP to the 50-point grid; if
                 that strike is unquoted take the nearest listed strike above.
  Friday 15:25   lots = floor(1 Cr / (entry spot * lot size)), capped by the
                 pledge margin. Sell the call for the expiry two sessions away.
  Tuesday 15:25  buy the position back -- never allowed to settle, so no
                 exercise STT.

NOT YET IMPLEMENTED -- the intraweek adjustment:
  "if NIFTY moves 300 points either way from the strike anchor, buy the call
   back and re-sell at the new K, holding that week's z. Fires 0.34 times per
   week."
Entry strike and sizing reconcile to the note almost exactly (avg coverage
94.8%, max 100.0%, avg margin Rs 10.43 L, avg lots 9.3, range 5-18, and the
strike-vs-spot ladder -392/-261/-129/+14/+257 against its -391/-265/-124/+8/
+256). P&L does not: Rs 3.21 L/yr here against Rs 4.87 L/yr in the note, with a
deeper worst week (-Rs 3.54 L vs -Rs 2.73 L). Both gaps point the same way --
without re-striking, a runaway week is never repaired. Implementing it needs
minute bars for the breach test and an arbitrary-bar option quote for the
re-entry, which the 15:25-only portfolio cache cannot serve; the condor cache
(D:\DK_sir_condor\cache) has the dense minute chains for it.
So: trust the live strike/lots below, treat the backtest P&L as a FLOOR.

Two parameter sets matter and both are reported:
  full-sample  base=-150 C=+200  the headline figures in the note
  walk-forward base=-100 C=+100  what the note says to actually plan around
                                 ("The honest number to plan around is the
                                 walk-forward result, not the headline.")

    python conditioned_call.py           # backtest both, print summary
    python conditioned_call.py --live    # the strike/lots for the coming week
"""
import sys

import numpy as np
import pandas as pd

from backtest_btst import charges, load

CAPITAL = 1e7
PLEDGE = 0.50            # 50% haircut on the pledged equity book
CE_MARGIN = 0.11         # SPAN approximation: 11% of notional per short call
SLIP = 0.25              # index points per leg
ENTRY_T = "15:25:59"
VOL_WINDOW, Z_WINDOW, Z_CLIP = 14, 252, 3.0
STRIKE_STEP = 50
RESTRIKE_POINTS = 300.0

PARAMS = {"full-sample": (-150.0, 200.0), "walk-forward": (-100.0, 100.0)}

#: Real NSE lot-size history. Holding this flat at 65 was Correction 1 in the
#: note's look-ahead audit, so it must not be simplified back to a constant.
LOT_SCHEDULE = [("2000-01-01", 75), ("2021-07-01", 50), ("2024-04-26", 25),
                ("2024-11-20", 75), ("2026-01-01", 65)]


def lot_size_for(date_str):
    lot = LOT_SCHEDULE[0][1]
    for start, size in LOT_SCHEDULE:
        if date_str >= start:
            lot = size
    return lot


def vol_z(daily_close):
    """14-day realised vol, z-scored on its own trailing 252 sessions.

    Both windows end on the PRIOR session -- the note's look-ahead audit says
    realised vol is "computed from returns ending the prior session", and the
    z-score uses "the 252 sessions before the trade date".
    """
    lr = np.log(daily_close / daily_close.shift(1))
    rv = lr.rolling(VOL_WINDOW).std() * np.sqrt(252)
    rv_prev = rv.shift(1)
    mu = rv_prev.rolling(Z_WINDOW).mean()
    sd = rv_prev.rolling(Z_WINDOW).std()
    return ((rv_prev - mu) / sd).clip(-Z_CLIP, Z_CLIP), rv_prev


def strike_from_z(spot, z, base, c, listed):
    """K = spot + base + C*z, rounded up to the 50-grid, then to a live strike."""
    raw = spot + base + c * z
    k = np.ceil(raw / STRIKE_STEP) * STRIKE_STEP
    above = [s for s in listed if s >= k]
    return min(above) if above else (max(listed) if listed else np.nan)


def build(s5, op):
    """Per-session entry bars, daily closes, and the option slice at 15:25."""
    s5 = s5.sort_values("datetime").reset_index(drop=True)
    daily_close = s5.groupby("Date")["Close"].last()
    z, rv = vol_z(daily_close)

    spot_bar = s5[s5["Time"] == "15:25"].groupby("Date")["Close"].last()
    ent = op[op["Time"] == ENTRY_T]
    ce = ent[ent["Type"].astype(str).str.upper().str.startswith("C")]
    return daily_close, z, rv, spot_bar, ce


def cycles(days, ce):
    """(entry_day, exit_day, expiry) for every Friday->Tuesday holding period.

    The note enters Friday 15:25 and closes on expiry day 15:25, two sessions
    later. Expiry dates are read from the data rather than assumed, so the
    Thursday->Tuesday migration is handled automatically.
    """
    day_pos = {d: i for i, d in enumerate(days)}
    expiries = sorted(set(ce["ExpiryDate"]) & set(days))
    out = []
    for e in expiries:
        i = day_pos[e]
        if i < 2:
            continue
        entry = days[i - 2]          # two trading sessions before expiry
        out.append((entry, e, e))
    return out


def run(params_name, s5, op, verbose=False):
    base, c = PARAMS[params_name]
    daily_close, z, rv, spot_bar, ce = build(s5, op)
    days = sorted(set(spot_bar.index) & set(ce["Date"]))
    px = ce.set_index(["Date", "Ticker"])["Close"]
    by_day_exp = {k: g for k, g in ce.groupby(["Date", "ExpiryDate"])}

    rows = []
    for entry, exit_day, expiry in cycles(days, ce):
        if entry not in spot_bar.index or entry not in z.index:
            continue
        zi, spot = z.get(entry, np.nan), spot_bar.get(entry, np.nan)
        if not np.isfinite(zi) or not np.isfinite(spot):
            continue

        chain = by_day_exp.get((entry, expiry))
        if chain is None or chain.empty:
            continue
        listed = sorted(chain["Strike"].unique())
        k = strike_from_z(spot, zi, base, c, listed)
        leg = chain[chain["Strike"] == k]
        if leg.empty:
            continue
        tkr = leg["Ticker"].iloc[0]
        entry_px = float(leg["Close"].iloc[0])

        try:
            exit_px = float(px.loc[(exit_day, tkr)])
        except KeyError:
            continue
        if not np.isfinite(entry_px) or not np.isfinite(exit_px) or entry_px <= 0:
            continue

        lot = lot_size_for(entry)
        lots = int(CAPITAL // (spot * lot))
        margin_cap = int((CAPITAL * PLEDGE) // (spot * lot * CE_MARGIN))
        lots = max(0, min(lots, margin_cap))
        if lots == 0:
            continue

        # short call: sell at entry, buy back at exit; slippage against us both ways
        fill_in = entry_px - SLIP
        fill_out = exit_px + SLIP
        gross_pts = fill_in - fill_out
        qty = lots * lot
        cost = charges(fill_out * qty, fill_in * qty, n_lots=lots)
        net = gross_pts * qty - cost

        rows.append(dict(Entry=entry, Exit=exit_day, Expiry=expiry,
                         Spot=round(spot, 2), z=round(zi, 3),
                         RV=round(float(rv.get(entry, np.nan)) * 100, 2),
                         Strike=k, Moneyness=round(k - spot, 1),
                         Lot=lot, Lots=lots, Qty=qty,
                         Entry_Px=round(entry_px, 2), Exit_Px=round(exit_px, 2),
                         Gross_Pts=round(gross_pts, 2), Cost_Rs=round(cost, 0),
                         Net_Rs=round(net, 0),
                         Coverage=round(qty * spot / CAPITAL * 100, 1),
                         Margin_Rs=round(qty * spot * CE_MARGIN, 0)))
    return pd.DataFrame(rows)


def summarise(df, label):
    n = len(df)
    tot = df.Net_Rs.sum()
    yrs = (pd.Timestamp(df.Exit.iloc[-1]) - pd.Timestamp(df.Entry.iloc[0])).days / 365.25
    wins = (df.Net_Rs > 0).sum()
    return dict(Params=label, Cycles=n, Years=round(yrs, 2),
                Total_Rs=round(tot), Per_Year_Rs=round(tot / yrs),
                Pct_of_1Cr=round(tot / yrs / CAPITAL * 100, 2),
                Win_Pct=round(wins / n * 100, 1),
                Best=round(df.Net_Rs.max()), Worst=round(df.Net_Rs.min()),
                Avg_Cover=round(df.Coverage.mean(), 1),
                Max_Cover=round(df.Coverage.max(), 1),
                Avg_Margin=round(df.Margin_Rs.mean()),
                Avg_Lots=round(df.Lots.mean(), 1))


def live(s5, op):
    """Strike and size for the most recent entry the data supports."""
    daily_close, z, rv, spot_bar, ce = build(s5, op)
    days = sorted(set(spot_bar.index) & set(ce["Date"]))
    last = days[-1]
    spot, zi = spot_bar[last], z.get(last, np.nan)
    rvi = rv.get(last, np.nan)

    print(f"\nlatest session in data : {last}")
    print(f"NIFTY 15:25 close      : {spot:,.2f}")
    print(f"14d realised vol       : {rvi*100:.2f}%   (z = {zi:+.3f})")
    lot = lot_size_for(last)
    lots = int(CAPITAL // (spot * lot))
    margin_cap = int((CAPITAL * PLEDGE) // (spot * lot * CE_MARGIN))
    lots = max(0, min(lots, margin_cap))
    print(f"lot size in force      : {lot}")
    print(f"lots (Rs 1 Cr cover)   : {lots}   "
          f"-> coverage {lots*lot*spot/CAPITAL*100:.1f}%")
    print(f"margin needed          : Rs {lots*lot*spot*CE_MARGIN:,.0f} "
          f"of the Rs {CAPITAL*PLEDGE:,.0f} pledge")
    print(f"\n{'parameters':<14}{'base':>7}{'C':>7}{'raw K':>12}{'strike':>10}"
          f"{'vs spot':>10}")
    for name, (base, c) in PARAMS.items():
        raw = spot + base + c * zi
        k = np.ceil(raw / STRIKE_STEP) * STRIKE_STEP
        print(f"{name:<14}{base:>7.0f}{c:>7.0f}{raw:>12,.0f}{k:>10,.0f}"
              f"{k-spot:>+10,.0f}")
    print(f"\nre-strike if NIFTY trades through "
          f"{spot-RESTRIKE_POINTS:,.0f} or {spot+RESTRIKE_POINTS:,.0f} "
          f"(+/-{RESTRIKE_POINTS:.0f} from the anchor)")


def main():
    s5, op = load()
    print(f"data through {op['Date'].max()}")

    if "--live" in sys.argv:
        live(s5, op)
        return

    frames, summary = {}, []
    for name in PARAMS:
        df = run(name, s5, op)
        frames[name] = df
        summary.append(summarise(df, name))
        print(f"  {name}: {len(df)} cycles")

    rep = pd.DataFrame(summary)
    print("\n" + "=" * 110)
    print(rep.to_string(index=False))
    print("=" * 110)

    # Same window as the published note, so the two are directly comparable.
    wrows = []
    for name, df in frames.items():
        w = df[(df.Entry >= "2021-02-04") & (df.Exit <= "2026-07-22")]
        wrows.append(summarise(w, f"{name} (note window)"))
    rep = pd.concat([rep, pd.DataFrame(wrows)], ignore_index=True)
    print("\nwith the note's own window for comparison:")
    print(rep.to_string(index=False))

    out = r"D:\DK_sir\portfolio\Conditioned_Call_Updated.xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        rep.to_excel(xl, sheet_name="Summary", index=False)
        for name, df in frames.items():
            df.to_excel(xl, sheet_name=name.replace("-", "_")[:31], index=False)
            df["Year"] = df.Entry.str[:4]
            (df.groupby("Year")
               .agg(Cycles=("Net_Rs", "size"), Net_Rs=("Net_Rs", "sum"),
                    Win_Pct=("Net_Rs", lambda s: round((s > 0).mean() * 100, 1)))
               .assign(Pct_of_1Cr=lambda x: (x.Net_Rs / CAPITAL * 100).round(2))
               .to_excel(xl, sheet_name=f"{name[:20]}_yearly"))
    print(f"\nwrote {out}")
    live(s5, op)


if __name__ == "__main__":
    main()
