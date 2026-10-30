"""
Decrement assumptions for the FIA census: improved annuity mortality + static lapse.

Mortality: 2012 IAM Basic (best estimate, age nearest birthday) at the attained age in each
projection year, times the improvement factor for that calendar year:
    q_death(x, Y) = IAM q(x) x factor(x, Y),   capped at 1, and q = 1 past age 120.
  * MORTALITY_BASIS "basic" = IAM Basic; "period" = IAM Period (Basic plus the NAIC margin).
  * IMPROVEMENT "lc" = Lee-Carter factors (LeeCarterImprovement.py), "g2" = Scale G2
    (IARBuild.py), "none" = 2012 rates with no improvement. Factors are measured from 2012.
  * The 2012 IAM is built from payout annuity experience; it may understate mortality for
    deferred annuity owners. The census has no smoker status or underwriting class.

Lapse: the same static table as before (StaticLapse.py), by policy year and surrender
charge period, times the scenario multiplier. Years past the end of the table keep the
table's last (ultimate) rate.

Time convention: valuation date 12/31/VAL_YEAR; projection year t is calendar year
VAL_YEAR + t and policy year current_duration + t. The age during year t is
attained_age + t - 1. Both decrements happen at the END of the year, deaths first.

The matrices here are probabilities only. Whether a policy can still lapse (it can't once
its account value is gone) depends on the cash flow projection, so LiabilityCashflows.py
applies that.
"""
from dataclasses import dataclass
import os
import numpy as np
import pandas as pd

import CensusTables as ct

# ---------------- settings ----------------
TABLE_DIR       = "LifeRVCFTesting/AnnuityTables"    # iam_basic_<sex>_anb.csv (LeeCarterImprovement.py)
LC_DIR          = "LifeRVCFTesting/LCMultipliers"    # lc_improvement_factors_<sex>.csv
LAPSE_DIR       = "LifeRVCFTesting/Lapse"            # static_lapse_base.csv, static_lapse_scenarios.csv
OUT_DIR         = "LifeRVCFTesting/Projections"
VAL_YEAR        = 2019
MORTALITY_BASIS = "basic"
IMPROVEMENT     = "lc"
FACTOR_FILES    = {"lc": f"{LC_DIR}/lc_improvement_factors_{{sex}}.csv",
                   "g2": f"{TABLE_DIR}/g2_improvement_factors_{{sex}}.csv"}
Q_CAP           = 1.0
MIN_AGE, MAX_AGE = 18, 120
# ------------------------------------------

SEX = {"M": "male", "F": "female"}


@dataclass
class Assumptions:
    q_base: dict             # sex -> q by age MIN_AGE..MAX_AGE (2012)
    factors: dict            # sex -> (2D array [age, year - first_year], first_year)
    lapse_base: pd.DataFrame  # index = policy year, columns = SC period
    scenarios: dict          # {"low": 0.5, "base": 1.0, "high": 1.5}
    basis: str
    improvement: str


def load_assumptions(basis=MORTALITY_BASIS, improvement=IMPROVEMENT):
    q, f = {}, {}
    for sex in ("male", "female"):
        u = pd.read_csv(f"{TABLE_DIR}/iam_{basis}_{sex}_anb.csv", index_col=0)["q_ultimate"]
        assert u.index.min() == MIN_AGE and u.index.max() == MAX_AGE, f"{sex}: ages {u.index.min()}-{u.index.max()}"
        q[sex] = u.to_numpy(dtype=float)
        if improvement != "none":
            t = pd.read_csv(FACTOR_FILES[improvement].format(sex=sex), index_col=0)
            t.columns = t.columns.astype(int)
            assert t.index.min() == MIN_AGE and t.index.max() == MAX_AGE, f"{sex}: factor ages must be {MIN_AGE}-{MAX_AGE}"
            assert t.columns.min() == 2012, f"{sex}: factors should start in 2012 (the IAM base year)"
            f[sex] = (t.to_numpy(dtype=float), int(t.columns.min()))
    lapse = pd.read_csv(f"{LAPSE_DIR}/static_lapse_base.csv", index_col="duration")
    lapse.columns = [int(c.split("_")[1]) for c in lapse.columns]
    scen = pd.read_csv(f"{LAPSE_DIR}/static_lapse_scenarios.csv").set_index("scenario")["multiplier"].to_dict()
    return Assumptions(q, f, lapse, scen, basis, improvement)


def mortality_matrix(census, a, horizon, improve=True):
    """q_death[policy, year] for projection years 1..horizon."""
    t = np.arange(1, horizon + 1)
    age = census["attained_age"].to_numpy(dtype=int)[:, None] + t[None, :] - 1
    cal = VAL_YEAR + t
    sex = census["gender"].map(SEX).to_numpy()
    assert pd.notna(sex).all(), "gender must be M or F"
    assert (age[:, 0] >= MIN_AGE).all(), f"attained ages below {MIN_AGE}"
    q = np.empty(age.shape)
    for s in ("male", "female"):
        m = sex == s
        if not m.any():
            continue
        row = np.minimum(age[m], MAX_AGE) - MIN_AGE
        qs = a.q_base[s][row]
        if improve and a.improvement != "none":
            F, first = a.factors[s]
            col = np.clip(cal - first, 0, F.shape[1] - 1)
            qs = qs * F[row, col[None, :]]
        q[m] = qs
    q = np.minimum(Q_CAP, q)
    return np.where(age > MAX_AGE, 1.0, q)


def lapse_matrix(census, a, horizon, scenario="base"):
    """q_lapse[policy, year] for projection years 1..horizon (static table x multiplier)."""
    dur0 = census["current_duration"].to_numpy(dtype=int)
    scp = census["sc_period"].to_numpy(dtype=int)
    pol_year = dur0[:, None] + np.arange(1, horizon + 1)[None, :]
    last = int(a.lapse_base.index.max())
    out = np.empty(pol_year.shape)
    for n in np.unique(scp):
        if n not in a.lapse_base.columns:
            raise KeyError(f"no lapse column for SC period {n}; have {list(a.lapse_base.columns)}")
        col = a.lapse_base[n].reindex(range(1, last + 1)).to_numpy(dtype=float)
        m = scp == n
        out[m] = col[np.minimum(pol_year[m], last) - 1]
    return np.minimum(1.0, out * a.scenarios[scenario])


def project_policy(policy, a, horizon=30, lapse_scenario="base", improve=True):
    """One policy's decrements year by year (assumes it can lapse every year)."""
    one = pd.DataFrame([policy])
    q_b = mortality_matrix(one, a, horizon, improve=False)[0]
    q_d = mortality_matrix(one, a, horizon, improve)[0]
    q_w = lapse_matrix(one, a, horizon, lapse_scenario)[0]
    end = np.cumprod((1 - q_d) * (1 - q_w))
    start = np.concatenate([[1.0], end[:-1]])
    t = np.arange(1, horizon + 1)
    return pd.DataFrame({
        "t": t, "calendar_year": VAL_YEAR + t,
        "attained_age": int(policy["attained_age"]) + t - 1,
        "policy_year": int(policy["current_duration"]) + t,
        "q_death_base": q_b,
        "improvement_factor": np.divide(q_d, q_b, out=np.ones_like(q_d), where=q_b > 0),
        "q_death": q_d, "q_lapse": q_w,
        "in_force_start": start, "deaths": start * q_d,
        "surrenders": start * (1 - q_d) * q_w, "in_force_end": end,
    })


def project_census(census, a, horizon=30, lapse_scenario="base", improve=True):
    """Expected policy COUNTS by projection year (decrements only, no maturity)."""
    q_d = mortality_matrix(census, a, horizon, improve)
    q_w = lapse_matrix(census, a, horizon, lapse_scenario)
    end = np.cumprod((1 - q_d) * (1 - q_w), axis=1)
    start = np.hstack([np.ones((len(census), 1)), end[:, :-1]])
    t = np.arange(1, horizon + 1)
    return pd.DataFrame({"t": t, "calendar_year": VAL_YEAR + t,
                         "in_force_start": start.sum(0), "deaths": (start * q_d).sum(0),
                         "surrenders": (start * (1 - q_d) * q_w).sum(0), "in_force_end": end.sum(0)})


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    a = load_assumptions()
    census = ct.load_census()
    pd.set_option("display.width", 200)
    print(f"mortality: 2012 IAM {a.basis}, improvement: {a.improvement}")

    p = census.iloc[0]
    one = project_policy(p, a)
    one.to_csv(f"{OUT_DIR}/policy_{int(p['pol_num'])}_inforce.csv", index=False)
    print(f"\npolicy {int(p['pol_num'])} ({p['gender']}, age {int(p['attained_age'])}):")
    print(one.round(4).head(8).to_string(index=False))

    for scen in a.scenarios:
        agg = project_census(census, a, lapse_scenario=scen)
        agg.to_csv(f"{OUT_DIR}/census_decrements_{scen}.csv", index=False)
        print(f"\nlapse '{scen}': in force at t=10: {agg.loc[9, 'in_force_end']:,.0f} of {len(census):,}")
    print(f"\nwrote CSVs to {OUT_DIR}/")