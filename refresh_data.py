"""Refresh nifty50 stock CSVs + the NIFTY index series from Yahoo.

Re-fetches FULL history per symbol rather than appending: the stored files use
auto_adjust=True, whose dividend/split back-adjustment rewrites every prior
close each time a new dividend lands. Appending raw rows would put a fake
return jump at the seam.

    python refresh_data.py            # fetch through today
    python refresh_data.py 2026-08-31 # fetch through a given date
"""
import glob
import os
import sys

import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.abspath(__file__))
NIFTY_DIR = os.path.join(ROOT, "nifty50")
INDEX_CSV = os.path.join(ROOT, "Nifty 50 Historical Data.csv")
START = "2016-01-01"
COLS = ["Symbol", "Company", "Industry", "Index", "Date",
        "Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]

#: Corporate actions Yahoo does not adjust correctly, leaving a fake overnight
#: crash. Each entry is (date_of_the_gap_in_yahoo_data, price_ratio, note).
#:
#: The ratio is the EXCHANGE-PUBLISHED adjustment, not the observed price gap,
#: so whatever the stock genuinely did that day survives the repair. Using the
#: observed gap instead would silently zero a real move -- TRENT actually rose
#: 0.43% and VEDL actually fell 6.2% on their respective days.
#:
#: Verify against the exchange announcement before adding an entry; a genuine
#: crash belongs in the data (INDUSINDBK -27% on 2025-03-11 is real).
CORP_ACTIONS = {
    # 1:2 bonus (1 new share per 2 held -> price x 2/3). True ex-date is
    # 2026-06-04 and Yahoo flags the 1.5 split there, but it applied the price
    # adjustment at 2026-01-01 instead -- so the repair goes where the gap is,
    # not where the action was. Checked: no double adjustment in June.
    "TRENT": [("2026-01-01", 2.0 / 3.0, "1:2 bonus, ex 2026-06-04, misdated")],
    # Demergers settle by exchange price discovery, not a share ratio.
    # Tata Motors 661 -> 400 adjusted on the record date.
    "TMPV":  [("2025-10-14", 400.0 / 661.0, "TMLCV demerger, price discovery")],
    # Vedanta special pre-open discovery settled the residual company at 289.50
    # against the prior close of 773.60.
    "VEDL":  [("2026-04-30", 289.50 / 773.60, "demerger, price discovery")],
}
#: Warn about any unlisted single-day move at least this large, so the next
#: unrecorded action is caught instead of silently corrupting a lookback.
JUMP_WARN = 0.25


def fetch(ticker, end):
    """Full daily history, back-adjusted the same way the stored files are."""
    d = yf.Ticker(ticker).history(start=START, end=end, auto_adjust=True)
    if d.empty:
        return d
    d.index = d.index.tz_localize(None)
    return d


def repair_corp_actions(d, sym):
    """Divide the known corporate-action ratio out of each listed gap.

    Scales every price before the ex-date by the published ratio, so the
    artificial part of that day's move disappears and the genuine part -- the
    residual between the exchange's adjusted reference price and where the
    stock actually closed -- is left in the series.
    """
    notes = []
    for ex_s, ratio, why in CORP_ACTIONS.get(sym, []):
        ex = pd.Timestamp(ex_s)
        if ex not in d.index:
            notes.append(f"{ex.date()} not a trading day")
            continue
        pos = d.index.get_loc(ex)
        if pos == 0:
            continue
        observed = d["Close"].iloc[pos] / d["Close"].iloc[pos - 1]
        for c in ("Open", "High", "Low", "Close"):
            d.iloc[:pos, d.columns.get_loc(c)] *= ratio
        residual = (observed / ratio - 1) * 100
        notes.append(f"{ex.date()} x{ratio:.5f} ({why}); "
                     f"real move {residual:+.2f}%")
    return d, notes


def unlisted_jumps(d, sym):
    """Single-day moves big enough to look like an unrecorded corporate action."""
    r = d["Close"].pct_change()
    known = {pd.Timestamp(x) for x, _, _ in CORP_ACTIONS.get(sym, [])}
    hits = r[r.abs() >= JUMP_WARN]
    return [(str(k.date()), round(v * 100, 2))
            for k, v in hits.items() if k not in known]


def refresh_stocks(end):
    rows, warns = [], []
    for path in sorted(glob.glob(os.path.join(NIFTY_DIR, "*_1d_max.csv"))):
        sym = os.path.basename(path).replace("_1d_max.csv", "")
        old = pd.read_csv(path)
        old_last = old["Date"].iloc[-1]
        try:
            new = fetch(sym + ".NS", end)
        except Exception as exc:                       # network / delisted
            rows.append((sym, old_last, "FETCH ERROR", len(old), 0, str(exc)[:40]))
            continue
        if new.empty or len(new) < len(old) * 0.9:
            # Refuse to overwrite a good file with a short/empty pull.
            rows.append((sym, old_last, "SKIPPED", len(old), len(new), "short pull"))
            continue

        new, fixes = repair_corp_actions(new, sym)
        warn = unlisted_jumps(new, sym)

        out = pd.DataFrame({
            "Symbol": old["Symbol"].iloc[0],
            "Company": old["Company"].iloc[0],
            "Industry": old["Industry"].iloc[0],
            "Index": old["Index"].iloc[0],
            "Date": new.index.strftime("%d-%m-%Y"),
            "Open": new["Open"].values,
            "High": new["High"].values,
            "Low": new["Low"].values,
            "Close": new["Close"].values,
            "Volume": new["Volume"].values,
            "Dividends": new["Dividends"].values,
            "Stock Splits": new["Stock Splits"].values,
        })[COLS]
        out.to_csv(path, index=False)
        note = f"+{len(out) - len(old)}"
        if fixes:
            note += "  adj: " + ", ".join(fixes)
        rows.append((sym, old_last, out["Date"].iloc[-1], len(old), len(out), note))
        if warn:
            warns.append((sym, warn))

    rep = pd.DataFrame(rows, columns=["Symbol", "Old_Last", "New_Last",
                                      "Old_Rows", "New_Rows", "Note"])
    return rep, warns


def refresh_index(end):
    d = fetch("^NSEI", end)
    if d.empty:
        print("[index] EMPTY PULL - left untouched")
        return None
    old = pd.read_csv(INDEX_CSV)
    out = pd.DataFrame({"Date": d.index.strftime("%d-%m-%Y"),
                        "Price": d["Close"].values})
    # Stored index history starts 2016-01-04; keep the same depth.
    out.to_csv(INDEX_CSV, index=False)
    print(f"[index] {old['Date'].iloc[-1]} -> {out['Date'].iloc[-1]} "
          f"({len(old)} -> {len(out)} rows)")
    return out


def main():
    end = sys.argv[1] if len(sys.argv) > 1 else \
        (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Refreshing through {end}\n")
    rep, warns = refresh_stocks(end)
    print(rep.to_string(index=False))
    bad = rep[rep["New_Last"].isin(["FETCH ERROR", "SKIPPED"])]
    print(f"\n{len(rep) - len(bad)} refreshed, {len(bad)} untouched")
    if warns:
        print(f"\n[CHECK] unlisted single-day moves >= {JUMP_WARN:.0%} -- a real "
              f"crash, or a corporate action to add to CORP_ACTIONS?")
        for sym, hits in warns:
            for dt, pct in hits:
                print(f"  {sym:<12} {dt}  {pct:+.2f}%")
    refresh_index(end)


if __name__ == "__main__":
    main()
