# Replica + Covered Call

A sparse NIFTY 50 equity replication book with a volatility-conditioned weekly
call written against it, run on a fixed ₹1 crore mandate.

Backtest window **Feb 2021 – Sep 2026** — 68 months, 292 option cycles.

---

## The mandate

₹1,00,00,000 is deployed and never grows. At each month end the month's P&L is
booked out to a separate ledger and the book is reset to exactly ₹1 crore.
Returns are therefore **simple** — profit ÷ years ÷ ₹1 crore — not compounded,
and no CAGR applies. Drawdown is measured on the cumulative booked-profit curve
as a percentage of the ₹1 crore deployed.

The shares are pledged with the broker, which attracts a 50% haircut and so
produces ₹50 lakh of F&O margin without selling anything. The option overlay
uses about a fifth of that. Coverage never exceeds 100% — the short call is
covered at all times, never naked.

## The two equity books

Both replicate the NIFTY 50 with a small basket rather than all fifty names,
rebalanced monthly on the first trading session from a 252-session lookback,
against a point-in-time constituent basket so a stock is only selectable in
months it was actually in the index.

| | Model A | Model D |
|---|---|---|
| Method | sector-mean positive Lasso (α=0.001) | shrinkage QP with macro conditioning |
| Macro inputs | none | India VIX, RBI repo, 1-yr G-Sec, INR/USD |
| Avg. holdings | ~13.7 | ~24.7 |
| Cost convention | **gross** of transaction costs | **net** of 0.30% turnover |

That last row is a real asymmetry, not an oversight — see *Gotchas*.

## The overlay

A weekly short NIFTY call whose strike slides with how volatile the market has
actually been:

```
z = 14-day realised volatility, z-scored on its own trailing 252 sessions, clipped ±3
K = Spot + base + C × z,  rounded up to the 50-point strike grid
```

Enter Friday 15:25, exit Tuesday 15:25 (two sessions, four calendar days, so the
weekend decay is captured). The position is always bought back, never allowed to
settle, which avoids exercise STT.

Quiet market → z negative → strike pulled *below* spot → delta ≈ 1.0, the hedge
is on and market risk is largely cancelled while stock-selection alpha is left
alone. Violent market → z positive → strike pushed well *above* spot → delta
≈ 0.2, the hedge is off and full participation is retained. It is a variable
delta hedge, not a premium-harvesting scheme.

Two parameter sets ship:

| Set | base | C | Use |
|---|---|---|---|
| `full-sample` | −150 | +200 | the in-sample optimum |
| `walk-forward` | −100 | +100 | **plan on this one** — chosen without hindsight |

## Results

Fixed ₹1 crore, profit booked monthly, walk-forward overlay parameters.

| Book | Return /yr | Max DD | Vol | Sharpe | CAR/MDD | Win months |
|---|---|---|---|---|---|---|
| Model A only | 19.12% | −24.06% | 17.30% | 0.76 | 0.79 | 64.7% |
| **Model A + call** | **21.56%** | −21.67% | 14.09% | 1.11 | 0.99 | 61.8% |
| Model D only | 16.25% | −17.51% | 15.62% | 0.66 | 0.93 | 64.7% |
| **Model D + call** | **18.69%** | **−15.94%** | **12.29%** | 1.04 | **1.17** | **66.2%** |

Model A returns more; Model D returns more *per unit of drawdown* and is the
better risk-adjusted structure. The overlay adds ~2.44pp to both and cuts
drawdown on both.

## Layout

```
refresh_data.py          pull NIFTY 50 daily prices + index from Yahoo
test_refresh_data.py     self-check for the corporate-action repair
extend_pit_basket.py     extend the point-in-time constituent basket
rebuild_models.py        regenerate the Model A / Model D workbooks
reproduce_models.py      verify the engine still reproduces published figures
attribute_modelA_gap.py  one-off forensic: why Model A moved (paths are local)
september_book.py        the live monthly holdings, sized on ₹1 crore
september_report.py      holdings marked to market + month-to-date
src/data_loader.py       universe, prices, point-in-time basket
portfolio/conditioned_call.py   the overlay engine
portfolio/combined_backtest.py  book + overlay under the ₹1 crore mandate
dashboard/               self-contained HTML dashboard + its build script
```

`dashboard/overlay_desk.html` opens in a browser with no server and no data
files — every figure is baked in.

## Running it

Data is **not** in this repo (the option/spot parquet stores alone are ~1.2 GB).
Paths are absolute and point at the machine this was developed on; change them
at the top of each script.

```bash
python refresh_data.py            # prices through today
python extend_pit_basket.py       # basket through the current month
python rebuild_models.py          # the two equity workbooks
python portfolio/combined_backtest.py
python dashboard/build_dashboard.py
```

## Gotchas

Each of these is a real defect that was found and fixed — they are documented
because they are easy to reintroduce.

**A missing reshuffle tracker silently disables survivorship correction.**
`backtest_engine` does `pit_basket_dict.get(month, set())`, and an empty dict
means *no universe filter at all* — every delisted name on disk becomes
selectable. It inflates results badly (Model A 21.50% → 27.23%). `DataLoader`
now raises instead of warning.

**Yahoo mishandles Indian demergers and bonus issues.** It leaves a fake
overnight crash. `CORP_ACTIONS` in `refresh_data.py` repairs these using the
*exchange-published* ratio, never the observed price gap — the gap silently
erases whatever the stock genuinely did that day. Verified: TRENT (1:2 bonus,
×2/3, and note Yahoo dates the adjustment five months early), TMPV (Tata Motors
CV demerger, 661→400), VEDL (demerger, →289.50). A ≥25% jump detector flags new
ones; genuine crashes such as INDUSINDBK −27% on 2025-03-11 must stay.

**Never append rows to the price CSVs.** They are stored `auto_adjust=True`,
whose back-adjustment rewrites every prior close when a new dividend lands.
Re-fetch full history instead.

**Lot size is not constant.** NSE ran 75 → 50 (Jul 2021) → 25 (Apr 2024) → 75
(Nov 2024) → 65 (2026). `conditioned_call.py` carries the real schedule; holding
it flat at 65 mis-sizes every year but 2026.

## Known limitation

The overlay does **not** implement the intraweek 300-point re-strike ("if NIFTY
moves 300 points from the strike anchor, buy back and re-sell at the new K").
Entry strike and sizing reconcile closely to the reference note — average
coverage 94.8%, max 100.0%, average lots 9.3 over a 5–18 range, and a strike
ladder of −392/−261/−129/+14/+257 points against its −391/−265/−124/+8/+256 —
but P&L does not, and the shortfall lands exactly on the violent weeks where
re-striking matters most.

**Every overlay figure here is therefore a floor, not an estimate.**

## Disclaimer

Backtested results describe what did happen and are not a forecast. This is
research code, not investment advice.
