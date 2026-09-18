"""Self-check for the corporate-action repair in refresh_data.py.

    python test_refresh_data.py
"""
import pandas as pd

import refresh_data as rd


def _frame(closes, dates):
    return pd.DataFrame({"Open": closes, "High": closes,
                         "Low": closes, "Close": closes},
                        index=pd.to_datetime(dates))


def test_repair_divides_out_the_published_ratio_only():
    # 1:2 bonus (ratio 0.5 for this toy case) on a day the stock ALSO rose 2%:
    # 100 -> 51 is a 0.51 gap, of which 0.50 is the action and +2% is real.
    d = _frame([100.0, 100.0, 51.0, 51.0],
               ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
    rd.CORP_ACTIONS["FAKE"] = [("2026-01-05", 0.5, "toy 1:1 bonus")]
    out, notes = rd.repair_corp_actions(d.copy(), "FAKE")
    r = out["Close"].pct_change()

    assert abs(r.iloc[2] - 0.02) < 1e-12, \
        f"the real +2% must survive, got {r.iloc[2]}"
    assert abs(r.iloc[3]) < 1e-12, "post-ex-date return must be untouched"
    assert abs(out["Close"].iloc[0] - 50.0) < 1e-9, "prior prices scale by ratio"
    assert abs(out["Close"].iloc[2] - 51.0) < 1e-9, "ex-date price must not move"
    assert "x0.50000" in notes[0] and "+2.00%" in notes[0], notes
    # every OHLC column scales together, or intraday ranges break
    assert abs(out["High"].iloc[0] - 50.0) < 1e-9


def test_observed_gap_would_have_erased_the_real_move():
    # Guards the reason we use the published ratio rather than the price gap.
    d = _frame([100.0, 51.0], ["2026-01-01", "2026-01-02"])
    rd.CORP_ACTIONS["FAKE"] = [("2026-01-02", 0.51, "observed-gap ratio")]
    out, _ = rd.repair_corp_actions(d.copy(), "FAKE")
    assert abs(out["Close"].pct_change().iloc[1]) < 1e-12, \
        "using the gap as the ratio flattens the day - that is the bug"


def test_unlisted_jump_is_flagged_but_listed_one_is_not():
    d = _frame([100.0, 100.0, 50.0, 51.0],
               ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
    rd.CORP_ACTIONS["FAKE"] = [("2026-01-05", 0.5, "toy")]
    assert rd.unlisted_jumps(d, "FAKE") == [], "listed ex-date must not warn"
    assert rd.unlisted_jumps(d, "OTHER") == [("2026-01-05", -50.0)], \
        "an unlisted -50% day must warn"


def test_real_crash_survives_repair():
    # A genuine -27% day with no CORP_ACTIONS entry must stay in the series.
    d = _frame([100.0, 73.0], ["2026-01-01", "2026-01-02"])
    out, notes = rd.repair_corp_actions(d.copy(), "INDUSINDBK")
    assert notes == [], "nothing should be adjusted"
    assert abs(out["Close"].pct_change().iloc[1] + 0.27) < 1e-12


if __name__ == "__main__":
    test_repair_divides_out_the_published_ratio_only()
    test_observed_gap_would_have_erased_the_real_move()
    test_unlisted_jump_is_flagged_but_listed_one_is_not()
    test_real_crash_survives_repair()
    print("ok - corporate-action repair behaves")
