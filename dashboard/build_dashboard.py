"""Rebuild the Overlay Desk dashboard from the backtest workbooks.

Reads the two combined backtests and the conditioned-call log, computes the
derived risk and distribution statistics the page shows, bakes everything into
template.html, and writes:

  overlay_desk.html   a complete standalone page -- double-click it, works offline
  artifact_page.html  the same content without the <html>/<head>/<body> wrapper,
                      which is the form the Artifact publisher expects
  ../index.html       the standalone page at the repo root, for GitHub Pages

Run portfolio/combined_backtest.py first whenever the underlying data moves.

    python build_dashboard.py
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = r"D:\DK_sir\portfolio"
CAPITAL = 1e7
START = "2021-02-01"
RF = 0.0592

BOOKS = [("A", "ModelA", "Model A"), ("D", "ModelD", "Model D")]
#: Boundaries on the volatility z-score. Matches the writeup's five regimes.
Z_BUCKETS = ([-9, -1, -0.35, 0.35, 1, 9],
             ["Very quiet", "Quiet", "Normal", "Busy", "Violent"])
#: Monthly-return histogram edges, in % of the Rs 1 crore.
HIST_EDGES = [-99, -5, -2, 0, 2, 5, 99]
HIST_NAMES = ["under −5%", "−5 to −2%", "−2 to 0%", "0 to 2%", "2 to 5%", "over +5%"]

WRAPPER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Backtest dashboard for the NIFTY equity replicas and the conditioned covered call overlay.">
{head}
</head>
<body style="margin:0">
{body}
</body>
</html>
"""


def standalone(page):
    """Wrap the artifact body as a valid standalone document.

    The artifact publisher supplies its own <head>, so the template leads with
    <title>/<link>/<style> and no document scaffolding. A local file needs those
    in a real <head> -- browsers hoist them from <body>, but only by error
    recovery, and GitHub Pages serves the file as written.
    """
    cut = page.index("</style>") + len("</style>")
    return WRAPPER.format(head=page[:cut].strip(), body=page[cut:].strip())


# ----------------------------------------------------------------------
# derived statistics
# ----------------------------------------------------------------------
def episodes(dates, curve, top=6):
    """Peak-to-trough drawdowns, deepest first, with recovery."""
    s = pd.Series(curve, index=pd.to_datetime(dates).values)
    running = s.cummax()
    out, inside, pk, tr = [], False, 0, 0
    for i in range(len(s)):
        if s.iloc[i] >= running.iloc[i]:
            if inside:
                out.append(dict(peak=str(s.index[pk].date()),
                                trough=str(s.index[tr].date()),
                                rec=str(s.index[i].date()),
                                depth=round((s.iloc[tr] - s.iloc[pk]) / CAPITAL * 100, 2),
                                days=int((s.index[i] - s.index[pk]).days)))
                inside = False
            pk = i
        else:
            if not inside:
                inside, tr = True, i
            elif s.iloc[i] < s.iloc[tr]:
                tr = i
    if inside:
        out.append(dict(peak=str(s.index[pk].date()), trough=str(s.index[tr].date()),
                        rec=None,
                        depth=round((s.iloc[tr] - s.iloc[pk]) / CAPITAL * 100, 2),
                        days=None))
    return sorted(out, key=lambda e: e["depth"])[:top]


def risk(dates, curve, monthly_pct):
    """Drawdown, exposure-to-drawdown and downside-risk statistics."""
    dd = (curve - np.maximum.accumulate(curve)) / CAPITAL * 100
    mr = np.asarray(monthly_pct) / 100.0
    downside = mr[mr < 0]
    dsd = downside.std(ddof=1) * np.sqrt(12) if len(downside) > 1 else np.nan
    ann = (curve[-1] - CAPITAL) / CAPITAL / (len(curve) / 252.0)
    # Return, drawdown and CAR/MDD come from the workbook's own Summary sheet so
    # the page never shows two slightly different values for one metric. Only
    # what Summary lacks is computed here.
    return dict(
        under=round(float((dd < -0.01).mean() * 100), 1),
        deep=round(float((dd < -10).mean() * 100), 1),
        sortino=round(float((ann - RF) / dsd), 2) if dsd and dsd == dsd else None,
    )


def rolling12(monthly_pct):
    """Trailing 12-month total return, in % of the Rs 1 crore."""
    s = pd.Series(monthly_pct)
    return [None if pd.isna(v) else round(float(v), 2)
            for v in s.rolling(12).sum()]


def histogram(monthly_pct):
    cut = pd.cut(pd.Series(monthly_pct), HIST_EDGES, labels=HIST_NAMES)
    counts = cut.value_counts().reindex(HIST_NAMES).fillna(0)
    return [int(v) for v in counts]


def collect():
    out = {"books": {}, "meta": {}}
    for key, fname, label in BOOKS:
        f = os.path.join(PORT, f"Backtest_{fname}_CoveredCall.xlsx")
        s = pd.read_excel(f, sheet_name="Summary")
        m = pd.read_excel(f, sheet_name="Monthly")
        y = pd.read_excel(f, sheet_name="Yearly")
        d = pd.read_excel(f, sheet_name="Daily_Ledger")
        d["Date"] = pd.to_datetime(d["Date"])

        # The equity leg is identical either way -- the option only adds a leg.
        # So both ledgers come out of the one daily frame.
        cw = CAPITAL + d["Equity_PnL"].cumsum() + d["Option_PnL"].cumsum()
        ca = CAPITAL + d["Equity_PnL"].cumsum()
        mw = m["Return_on_1Cr_pct"].tolist()
        ma = (m["Equity_PnL"] / CAPITAL * 100).round(2).tolist()

        def curve(series):
            mm = series.set_axis(d["Date"]).resample("ME").last().dropna()
            return mm

        cwm, cam = curve(cw), curve(ca)
        dd_w = (cwm - cwm.cummax()) / CAPITAL * 100
        dd_a = (cam - cam.cummax()) / CAPITAL * 100

        out["books"][key] = {
            "label": label,
            "alone": s.iloc[0].to_dict(),
            "withcall": s.iloc[1].to_dict(),
            "monthly": [{"m": r.Month, "eq": round(r.Equity_PnL),
                         "op": round(r.Option_PnL), "tot": round(r.Total_PnL),
                         "pct": round(r.Return_on_1Cr_pct, 2)} for r in m.itertuples()],
            "yearly": [{"y": int(r.Year), "eq": round(r.Equity_PnL),
                        "op": round(r.Option_PnL), "tot": round(r.Total_PnL),
                        "pct": round(r.Return_on_1Cr_pct, 2)} for r in y.itertuples()],
            "curve": [{"d": str(i.date())[:7], "p": round(float(p), 2),
                       "a": round(float(q), 2), "dd": round(float(x), 2),
                       "dda": round(float(z), 2)}
                      for i, p, q, x, z in zip(cwm.index, (cwm - CAPITAL) / CAPITAL * 100,
                                               (cam - CAPITAL) / CAPITAL * 100, dd_w, dd_a)],
            "roll": {"call": rolling12(mw), "alone": rolling12(ma)},
            "hist": {"call": histogram(mw), "alone": histogram(ma)},
            "risk": {"call": risk(d["Date"], cw.values, mw),
                     "alone": risk(d["Date"], ca.values, ma)},
            "eps": {"call": episodes(d["Date"], cw.values),
                    "alone": episodes(d["Date"], ca.values)},
        }

    cc = pd.read_excel(os.path.join(PORT, "Conditioned_Call_Updated.xlsx"),
                       sheet_name="walk_forward")
    cc = cc[cc["Entry"] >= START].copy()
    cc["b"] = pd.cut(cc["z"], Z_BUCKETS[0], labels=Z_BUCKETS[1])
    g = cc.groupby("b", observed=True).agg(
        weeks=("z", "size"), money=("Moneyness", "mean"), prem=("Entry_Px", "mean"),
        avg=("Net_Rs", "mean"), tot=("Net_Rs", "sum"),
        win=("Net_Rs", lambda s: (s > 0).mean() * 100))
    out["regime"] = [{"name": i, "weeks": int(r.weeks), "money": round(r.money),
                      "prem": round(r.prem, 1), "avg": round(r.avg),
                      "tot": round(r.tot), "win": round(r.win, 1)}
                     for i, r in g.iterrows()]

    cc["Year"] = cc["Entry"].str[:4]
    out["optYear"] = [{"y": int(k), "n": int(v["Net_Rs"].size),
                       "tot": round(v["Net_Rs"].sum()),
                       "win": round((v["Net_Rs"] > 0).mean() * 100, 1)}
                      for k, v in cc.groupby("Year")]
    out["trades"] = [{"e": r.Entry, "x": r.Exit, "s": round(r.Spot, 1),
                      "z": round(r.z, 2), "k": int(r.Strike),
                      "mny": round(r.Moneyness), "lot": int(r.Lot),
                      "lots": int(r.Lots), "in": round(r.Entry_Px, 2),
                      "out": round(r.Exit_Px, 2), "net": round(r.Net_Rs)}
                     for r in cc.tail(30).itertuples()][::-1]
    out["meta"] = {"cycles": len(cc), "from": cc["Entry"].min(), "to": cc["Exit"].max(),
                   "optTotal": round(cc["Net_Rs"].sum()),
                   "optWin": round((cc["Net_Rs"] > 0).mean() * 100, 1),
                   "best": round(cc["Net_Rs"].max()), "worst": round(cc["Net_Rs"].min()),
                   "avgCover": round(cc["Coverage"].mean(), 1),
                   "maxCover": round(cc["Coverage"].max(), 1),
                   "avgMargin": round(cc["Margin_Rs"].mean()),
                   "avgLots": round(cc["Lots"].mean(), 1),
                   "months": len(out["books"]["A"]["monthly"]),
                   "hist": HIST_NAMES}
    return out


def plain(o):
    """numpy scalars are not JSON types -- unwrap them."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def main():
    data = collect()
    blob = json.dumps(data, separators=(",", ":"), default=plain)

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__DATA__" not in tpl:
        raise SystemExit("template.html has no __DATA__ placeholder")
    body = tpl.replace("__DATA__", blob)
    page = standalone(body)

    with open(os.path.join(HERE, "dash_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=plain)
    with open(os.path.join(HERE, "artifact_page.html"), "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(HERE, "overlay_desk.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(HERE, os.pardir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)

    m = data["meta"]
    print(f"data: {m['months']} months, {len(data['regime'])} regimes, "
          f"{m['cycles']} cycles ({m['from']} .. {m['to']}), "
          f"{len(data['trades'])} recent trades, "
          f"{len(data['books']['A']['eps']['call'])} drawdown episodes/book")
    for f in ("overlay_desk.html", "artifact_page.html", "dash_data.json",
              os.path.join(os.pardir, "index.html")):
        p = os.path.join(HERE, f)
        print(f"  {f:<24} {os.path.getsize(p):>8,} bytes")


if __name__ == "__main__":
    main()
