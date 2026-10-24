"""
Static lapse table by policy year, with a surrender charge cliff, plus multiplier scenarios.

All rates below are ASSUMPTIONS (set to look like a surrender-charge product and roughly
the shape from my simulated dynamic model), not fitted to data or taken from any source.

Shape for a policy with surrender charge period (SCP) of N years:
    years 1..N   : rises linearly from SC_START_RATE to SC_END_RATE as the charge declines
    year N+1     : the cliff, the first year with no surrender charge
    after cliff  : ULTIMATE_RATE
Scenario multipliers scale every year's rate (capped at 100%).
"""
import os
import numpy as np
import pandas as pd

# ---------------- assumptions ----------------
SC_PERIODS     = [5, 7, 10]
SC_START_RATE  = 0.013     # lapse in policy year 1
SC_END_RATE    = 0.053     # lapse in the last year with a surrender charge
CLIFF_RATE     = 0.25      # lapse in the first year after the charge ends
ULTIMATE_RATE  = 0.07      # lapse in later years
MAX_DURATION   = 60     # must cover (oldest current duration + projection horizon)

SCENARIOS = {"low": 0.5, "base": 1.0, "high": 1.5}   # multipliers on the base table
OUT_DIR   = "LifeRVCFTesting/Lapse"
# ---------------------------------------------


def base_lapse_rate(duration, scp):
    """Base annual lapse rate for a policy year (1-based) given the SC period."""
    if duration <= scp:
        if scp == 1:
            return SC_END_RATE
        return SC_START_RATE + (SC_END_RATE - SC_START_RATE) * (duration - 1) / (scp - 1)
    if duration == scp + 1:
        return CLIFF_RATE
    return ULTIMATE_RATE


def lapse_q(duration, scp, multiplier=1.0):
    """Annual lapse probability after applying a scenario multiplier (capped at 1)."""
    return min(1.0, base_lapse_rate(duration, scp) * multiplier)


def lapse_table(scp, multiplier=1.0, max_duration=MAX_DURATION):
    d = np.arange(1, max_duration + 1)
    return pd.Series([lapse_q(x, scp, multiplier) for x in d],
                     index=pd.Index(d, name="duration"), name="lapse_q")


def lapse_path(current_duration, scp, horizon=30, multiplier=1.0):
    """Lapse probabilities for projection years t = 1..horizon for a policy that has
    already been in force `current_duration` years. Projection year t is policy year
    current_duration + t, so the cliff lands in the right projection year."""
    return pd.Series([lapse_q(current_duration + t, scp, multiplier) for t in range(1, horizon + 1)],
                     index=pd.Index(range(1, horizon + 1), name="t"), name="lapse_q")


def persistency(scp, multiplier=1.0, max_duration=MAX_DURATION):
    """Fraction of policies still in force at the END of each policy year (lapse only)."""
    q = lapse_table(scp, multiplier, max_duration)
    return (1 - q).cumprod().rename("in_force")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # one wide CSV: base lapse rates by duration for each SC period
    base = pd.DataFrame({f"scp_{n}": lapse_table(n) for n in SC_PERIODS})
    base.to_csv(f"{OUT_DIR}/static_lapse_base.csv")
    print("Base lapse rates by policy year (first 12):")
    print(base.head(12).round(4))

    # scenario tables and persistency
    rows = []
    for n in SC_PERIODS:
        for name, mult in SCENARIOS.items():
            lapse_table(n, mult).to_csv(f"{OUT_DIR}/static_lapse_scp{n}_{name}.csv")
            pers = persistency(n, mult)
            rows.append({"scp": n, "scenario": name, "multiplier": mult,
                         "in_force_yr5": pers.loc[5], "in_force_yr10": pers.loc[10],
                         "in_force_yr20": pers.loc[20]})
    summary = pd.DataFrame(rows)
    summary.to_csv(f"{OUT_DIR}/static_lapse_scenario_summary.csv", index=False)
    print("\nShare of policies still in force (lapse only):")
    print(summary.round(3).to_string(index=False))


if __name__ == "__main__":
    main()