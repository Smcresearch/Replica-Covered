"""Tunable parameters for the NIFTY iron-condor backtest.

Everything you are likely to change lives here. Import `CondorConfig`,
override the fields you care about, and pass it to the cache builder /
backtester.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

# --- paths -------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
#: The authoritative market-data store. This used to be a 1.2 GB duplicate
#: under ROOT, which was deleted in October 2026; read the store directly
#: instead of keeping a second copy in step. portfolio/build_cache.py already
#: pointed here, so the two pipelines now share one source.
STORE = Path(r"D:\files\data\NIFTY")
OPTIONS_DIR = STORE / "options_parquet"
SPOT_DIR = STORE / "spot_parquet"
FUTURES_DIR = STORE / "futures_parquet"
CACHE_DIR = ROOT / "cache"

for _d in (OPTIONS_DIR, SPOT_DIR):
    if not _d.is_dir():
        raise FileNotFoundError(
            f"market data store not found: {_d}. The backtest would otherwise "
            f"scan an empty directory and silently report zero trades.")

# --- market constants --------------------------------------------------
STRIKE_STEP = 50.0  # NIFTY strike grid spacing (verified across 2019-2026)
BARS_PER_DAY = 375  # 09:15:59 .. 15:29:59, one bar per minute

#: Contract multiplier: rupees of P&L per 1 index point, per lot.
#: Only scales the rupee columns -- the points columns are per 1 quantity
#: and are unaffected.
DEFAULT_LOT_SIZE = 65


@dataclass(frozen=True)
class CondorConfig:
    """One fully-specified iron-condor experiment."""

    # ---- universe / cache -------------------------------------------
    start_date: str = "2019-02-01"  # Jan-2019 files have corrupt strike data
    end_date: str = "2026-10-16"
    #: Expiries are cached this many trading days back from expiry day.
    #: Must be >= entry_dte, otherwise the entry bar will not be in cache.
    cache_lookback_days: int = 12
    #: Cache +/- this many strike steps around each day's ATM. 80 steps ==
    #: +/-4000 index points. Fixed (not a %) so every day's slab has the same
    #: width and the per-expiry tensors stack cleanly on the GPU.
    strike_half_width: int = 80
    #: Restrict to these ContractType labels, or () for no filter.
    #: Leave empty. Each expiry date carries exactly one label, and the
    #: month-end expiry is tagged 'M' -- so filtering to ('W',) silently drops
    #: one tradeable week per month. The labels are unreliable for far-dated
    #: contracts too. Proximity (`cache_lookback_days`) is the real filter:
    #: only expiries within that horizon are ever cached.
    contract_types: tuple[str, ...] = ()

    # ---- entry -------------------------------------------------------
    #: Enter this many *trading* days before expiry. 0 == expiry day itself.
    entry_dte: int = 4
    entry_time: str = "09:20:59"
    exit_time: str = "15:15:59"

    # ---- strike selection: volatility based --------------------------
    #: Trailing window (trading days) of spot closes used for realised vol.
    vol_window: int = 7
    #: Short strikes sit at spot * (1 +/- vol_mult * sigma_daily * sqrt(T)),
    #: where T is trading days from entry to expiry.
    vol_mult: float = 1.0
    #: Wing distance in index points from the short strike.
    wing_points: float = 200.0
    #: Floor/cap on the short-strike distance, in points. Guards against a
    #: dead-quiet vol window collapsing the condor onto ATM.
    min_short_distance: float = 100.0
    max_short_distance: float = 3000.0

    # ---- execution ----------------------------------------------------
    lots: int = 1
    #: Quantity per lot. Set to 1 to read every rupee figure as "per 1 qty",
    #: which makes them numerically equal to the points columns.
    lot_size: int = DEFAULT_LOT_SIZE
    #: Per-leg slippage in index points, applied against you on entry+exit.
    slippage_points: float = 0.5
    #: Transaction cost as a fraction of *premium turnover* -- charged on the
    #: premium of every leg bought and every leg sold, on entry and on exit.
    #: 0.005 == 0.5%. This is the main cost knob.
    cost_pct_premium: float = 0.005
    #: Optional flat rupee fee per leg per side, on top of the percentage.
    cost_per_leg: float = 0.0
    #: 'settlement' -> intrinsic vs the average spot over the last
    #:                 `settlement_window_bars` minutes, i.e. how NSE actually
    #:                 settles weekly options. No slippage (nothing is traded).
    #: 'intrinsic'   -> intrinsic vs the spot print at exit_time.
    #: 'ltp'         -> square off at the traded price at exit_time. Realistic
    #:                  only if you genuinely exit before expiry; on illiquid
    #:                  far strikes the last print can be badly stale.
    exit_mode: str = "settlement"
    settlement_window_bars: int = 30
    #: Reject a trade if any leg is missing a price at entry.
    require_all_legs: bool = True
    #: Reject a leg whose entry quote has not refreshed for this many minutes.
    #: Guards against pricing a condor off a stale print on a dead strike.
    max_quote_age_bars: int = 30
    #: Reject a trade whose net credit is below this (points, per unit).
    min_net_credit: float = 1.0

    # ---- engine -------------------------------------------------------
    use_gpu: bool = True
    dtype: str = "float32"

    def lot_size_for(self, date: str) -> int:
        """Contract multiplier on a given date.

        Flat by default. Override this if you need the historical schedule
        (NIFTY was 75 before 2024-11-20, then 25).
        """
        return self.lot_size

    def variant(self, **kw) -> "CondorConfig":
        """Return a copy with fields overridden (for parameter sweeps)."""
        return replace(self, **kw)


DEFAULT = CondorConfig()
