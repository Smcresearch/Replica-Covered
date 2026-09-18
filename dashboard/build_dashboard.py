"""Rebuild the Overlay Desk dashboard from the backtest workbooks.

Reads the two combined backtests and the conditioned-call log, bakes the numbers
into template.html, and writes two outputs:

  overlay_desk.html   a complete standalone page -- double-click it, works offline
  artifact_page.html  the same content without the <html>/<head>/<body> wrapper,
                      which is the form the Artifact publisher expects

Run portfolio/combined_backtest.py first whenever the underlying data moves;
this script only re-reads what that produced.

    python build_dashboard.py
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = r"D:\DK_sir\portfolio"
CAPITAL = 1e7
START = "2021-02-01"

BOOKS = [("A", "ModelA", "Model A"), ("D", "ModelD", "Model D")]
#: Boundaries on the volatility z-score. Matches the writeup's five regimes.
Z_BUCKETS = ([-9, -1, -0.35, 0.35, 1, 9],
             ["Very quiet", "Quiet", "Normal", "Busy", "Violent"])

WRAPPER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
</head>
<body style="margin:0">
{body}
</body>
</html>
"""


def collect():
    out = {"books": {}, "meta": {}}
    for key, fname, label in BOOKS:
        f = os.path.join(PORT, f"Backtest_{fname}_CoveredCall.xlsx")
        s = pd.read_excel(f, sheet_name="Summary")
        m = pd.read_excel(f, sheet_name="Monthly")
        y = pd.read_excel(f, sheet_name="Yearly")
        d = pd.read_excel(f, sheet_name="Daily_Ledger")
        d["Date"] = pd.to_datetime(d["Date"])

        ledger = d.set_index("Date")["Ledger"].resample("ME").last().dropna()
        profit = (ledger - CAPITAL) / CAPITAL * 100
        drawdn = (ledger - ledger.cummax()) / CAPITAL * 100

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
                       "dd": round(float(q), 2)}
                      for i, p, q in zip(ledger.index, profit, drawdn)],
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
    out["meta"] = {"cycles": len(cc), "from": cc["Entry"].min(), "to": cc["Exit"].max(),
                   "optTotal": round(cc["Net_Rs"].sum()),
                   "optWin": round((cc["Net_Rs"] > 0).mean() * 100, 1),
                   "best": round(cc["Net_Rs"].max()), "worst": round(cc["Net_Rs"].min())}
    return out


def main():
    data = collect()
    blob = json.dumps(data, separators=(",", ":"))

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__DATA__" not in tpl:
        raise SystemExit("template.html has no __DATA__ placeholder")
    body = tpl.replace("__DATA__", blob)

    with open(os.path.join(HERE, "dash_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    with open(os.path.join(HERE, "artifact_page.html"), "w", encoding="utf-8") as f:
        f.write(body)
    with open(os.path.join(HERE, "overlay_desk.html"), "w", encoding="utf-8") as f:
        f.write(WRAPPER.format(body=body))

    n = len(data["books"]["A"]["monthly"])
    print(f"data: {n} months, {len(data['regime'])} regimes, "
          f"{data['meta']['cycles']} option cycles "
          f"({data['meta']['from']} .. {data['meta']['to']})")
    for f in ("overlay_desk.html", "artifact_page.html", "dash_data.json"):
        p = os.path.join(HERE, f)
        print(f"  {f:<22} {os.path.getsize(p):>8,} bytes")


if __name__ == "__main__":
    main()
