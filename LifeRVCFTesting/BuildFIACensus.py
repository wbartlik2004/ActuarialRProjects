"""
Build an in-force FIXED INDEX ANNUITY (FIA) census from the actxps sample data, with an
optional guaranteed lifetime income rider.

Kept from actxps (census_dat, exported as CensusData.csv): pol_num, gender, issue_date,
issue age, qual, premium (used as the initial premium), inc_guar (who has the income
rider) and wd_age (the age withdrawals start). The actxps data is SIMULATED; everything
else is an ASSUMED product design, and every policy is rebuilt from issue to the
valuation date using actual index history (sp500.csv from MarketData.py).

On each policy anniversary, in this order:
  1. Index credit on the indexed share: min(cap, max(floor, participation x index return
     over the policy year)), annual point-to-point. Fixed share earns FIXED_RATE.
  2. Rider fee (rider policies): RIDER_FEE x benefit base, taken from the account value.
  3. Benefit base (rider policies): rolls up at ROLLUP_RATE (compound) for the first
     ROLLUP_YEARS years while no withdrawals have been taken, then steps up to the account
     value if that is higher (annual ratchet).
  4. Planned premium, if still in the premium-paying years and not yet withdrawing.
     Premiums are added to the benefit base too.
  5. Withdrawal, once the age at the anniversary reaches wd_age:
       rider:    guaranteed amount = benefit base x withdrawal % (the % is set by age at the
                 first withdrawal and then locked). If the account value runs out, the
                 insurer keeps paying it (insurer_paid_withdrawals).
       no rider: NONRIDER_WD_PCT x account value (inside the free withdrawal allowance).
     Guaranteed withdrawals do not reduce the benefit base and are not charged.
  6. Rebalance to INDEX_ALLOC indexed / the rest fixed.

Death benefit = max(premiums paid less withdrawals, account value).
MGSV, simplified: 87.5% of premiums accumulated at MGSV_RATE, less withdrawals.

The rider is a guaranteed lifetime WITHDRAWAL benefit (GLWB): income comes from
withdrawals. A GMIB instead guarantees income on annuitization; see the write-up notes.
Values are as of the last anniversary on or before the valuation date (2019-12-31).
"""
import numpy as np
import pandas as pd

import CensusTables as ct

# ---------------- settings ----------------
DIR       = "LifeRVCFTesting/ActxpsPolicyInfo"    # actxps CensusData.csv lives here
INDEX_CSV = "LifeRVCFTesting/Market/sp500.csv"    # from MarketData.py: date, close
OUT_DIR   = ct.CENSUS_DIR                         # the split census tables go here
WRITE_WIDE_CSV = False                            # True also writes the old one-file version
WIDE_CSV  = "LifeRVCFTesting/FIACensus.csv"
VAL_DATE  = pd.Timestamp("2019-12-31")
SEED      = 42

# assumed base contract terms
PRODUCT            = "FIA_10"
INDEX_NAME         = "S&P 500 (price return)"
CREDITING_METHOD   = "annual point-to-point"
CAP_RATE           = 0.05      # current annual cap (applied to all history: an assumption)
CAP_GUARANTEED_MIN = 0.01
FLOOR_RATE         = 0.00
PARTICIPATION      = 1.00
INDEX_ALLOC        = 0.80
FIXED_RATE         = 0.02
SC_PERIOD          = 10        # matches the lapse table's scp_10 column
SC0                = 7.0       # initial surrender charge %, declining linearly
FREE_WD_PCT        = 0.10
MATURITY_AGE       = 95
MGSV_PCT, MGSV_RATE = 0.875, 0.01

# assumed premium behavior
PREMIUM_YEARS      = 10        # planned premiums in policy years 2..PREMIUM_YEARS
PLANNED_PCT        = 0.10      # planned annual premium = this x initial premium
PAYER_SHARE        = 0.60      # share of policies that pay planned premiums

# assumed income rider (GLWB) terms
RIDER_TYPE         = "GLWB"
RIDER_FEE          = 0.0095    # annual fee, % of benefit base
ROLLUP_RATE        = 0.06      # compound roll-up while deferring
ROLLUP_YEARS       = 10
WD_PCT_BANDS       = [(55, 0.040), (60, 0.045), (65, 0.050), (70, 0.055), (75, 0.060), (80, 0.065)]
DEFAULT_WD_AGE     = 70        # rider policies with no wd_age in the data
NONRIDER_WD_PCT    = 0.05      # non-rider withdrawals, % of account value, from wd_age
MAX_YEARS          = 60
# ------------------------------------------


def index_lookup(index_csv):
    """Returns f(dates) -> index level on or before each date (as-of lookup)."""
    idx = pd.read_csv(index_csv, parse_dates=["date"]).sort_values("date")
    dates, levels = idx["date"].to_numpy(), idx["close"].to_numpy(dtype=float)

    def level(d):
        pos = np.searchsorted(dates, pd.DatetimeIndex(d).to_numpy(), side="right") - 1
        if (pos < 0).any():
            raise ValueError(f"index data starts {pd.Timestamp(dates[0]).date()}, but a policy "
                             f"needs {pd.DatetimeIndex(d)[pos < 0].min().date()} (set START in MarketData.py)")
        return levels[pos]

    if pd.Timestamp(dates[-1]) < VAL_DATE - pd.Timedelta(days=31):
        raise ValueError(f"index data ends {pd.Timestamp(dates[-1]).date()}, before {VAL_DATE.date()}")
    return level


def wd_pct_for_age(age):
    """Lifetime withdrawal % by age at first withdrawal (0 below the first band)."""
    age = np.asarray(age, dtype=float)
    pct = np.zeros_like(age)
    for lo, p in WD_PCT_BANDS:
        pct = np.where(age >= lo, p, pct)
    return pct


def as_bool(s):
    return s.astype(str).str.strip().str.upper().isin(["TRUE", "T", "1", "YES", "Y"]).to_numpy()


def terms_tables():
    """The product, surrender charge, rider and withdrawal-band tables, from the settings."""
    product = pd.DataFrame([{
        "product": PRODUCT, "index_name": INDEX_NAME, "crediting_method": CREDITING_METHOD,
        "index_alloc_pct": INDEX_ALLOC, "cap_rate": CAP_RATE, "cap_guaranteed_min": CAP_GUARANTEED_MIN,
        "floor_rate": FLOOR_RATE, "participation_rate": PARTICIPATION, "fixed_rate": FIXED_RATE,
        "sc_period": SC_PERIOD, "free_withdrawal_pct": FREE_WD_PCT, "maturity_age": MATURITY_AGE,
        "mgsv_pct": MGSV_PCT, "mgsv_rate": MGSV_RATE, "premium_years": PREMIUM_YEARS,
        "nonrider_wd_pct": NONRIDER_WD_PCT}])
    years = np.arange(1, SC_PERIOD + 1)
    sc = pd.DataFrame({"product": PRODUCT, "policy_year": years,
                       "sc_pct": SC0 * (SC_PERIOD - years + 1) / SC_PERIOD})
    rider = pd.DataFrame([{"rider_type": RIDER_TYPE, "rider_fee_pct": RIDER_FEE,
                           "rollup_rate": ROLLUP_RATE, "rollup_years": ROLLUP_YEARS,
                           "default_wd_age": DEFAULT_WD_AGE}])
    bands = pd.DataFrame([{"rider_type": RIDER_TYPE, "min_age": a, "wd_pct": pct}
                          for a, pct in WD_PCT_BANDS])
    return product, sc, rider, bands


def main():
    rng = np.random.default_rng(SEED)
    level = index_lookup(INDEX_CSV)
    c = pd.read_csv(f"{DIR}/CensusData.csv", parse_dates=["issue_date", "term_date"])

    p = c[(c["issue_date"] <= VAL_DATE) &
          (c["term_date"].isna() | (c["term_date"] > VAL_DATE))].copy().reset_index(drop=True)
    n = len(p)
    issue, issue_age = p["issue_date"], p["age"].to_numpy(dtype=int)
    anniv = lambda k: issue + pd.DateOffset(years=k)

    rider = as_bool(p["inc_guar"])
    wd_col = p["wd_age"] if "wd_age" in p.columns else pd.Series(np.nan, index=p.index)
    wd_age = pd.to_numeric(wd_col, errors="coerce").to_numpy(dtype=float)
    wd_age = np.where(rider & np.isnan(wd_age), DEFAULT_WD_AGE, wd_age)
    # rider withdrawals can't start before the youngest withdrawal-% band
    wd_age = np.where(rider, np.maximum(wd_age, WD_PCT_BANDS[0][0]), wd_age)
    takes_wd = ~np.isnan(wd_age)

    done = np.zeros(n, dtype=int)                  # completed policy years
    for k in range(1, MAX_YEARS + 1):
        passed = (anniv(k) <= VAL_DATE).to_numpy()
        if not passed.any():
            break
        done += passed

    init = p["premium"].to_numpy(dtype=float)
    planned = np.where(rng.random(n) < PAYER_SHARE, np.round(PLANNED_PCT * init, 2), 0.0)

    av = init.copy()
    bb = np.where(rider, init, 0.0)
    cum_prem, cum_wd = init.copy(), np.zeros(n)
    cum_fee, insurer_paid = np.zeros(n), np.zeros(n)
    mgsv = MGSV_PCT * init
    started = np.zeros(n, dtype=bool)
    wd_pct = np.zeros(n)
    last_wd = np.zeros(n)

    for k in range(1, done.max() + 1):
        act = done >= k
        age_k = issue_age + k                       # age at anniversary k

        # 1. crediting
        r = level(anniv(k)) / level(anniv(k - 1)) - 1.0
        credit = np.minimum(CAP_RATE, np.maximum(FLOOR_RATE, PARTICIPATION * r))
        growth = INDEX_ALLOC * (1 + credit) + (1 - INDEX_ALLOC) * (1 + FIXED_RATE)
        av = np.where(act, av * growth, av)
        mgsv = np.where(act, mgsv * (1 + MGSV_RATE), mgsv)

        # 2. rider fee
        fee = np.where(act & rider, np.minimum(RIDER_FEE * bb, av), 0.0)
        av -= fee
        cum_fee += fee

        # 3. benefit base: roll-up (deferral years only), then ratchet to account value
        roll = act & rider & ~started & (k <= ROLLUP_YEARS)
        bb = np.where(roll, bb * (1 + ROLLUP_RATE), bb)
        bb = np.where(act & rider, np.maximum(bb, av), bb)

        # 4. planned premium
        wd_now = act & takes_wd & (age_k >= wd_age)
        prem = np.where(act & (k + 1 <= PREMIUM_YEARS) & ~wd_now, planned, 0.0)
        av += prem
        bb += np.where(rider, prem, 0.0)
        cum_prem += prem
        mgsv += MGSV_PCT * prem

        # 5. withdrawals
        first = wd_now & ~started
        wd_pct = np.where(first & rider, wd_pct_for_age(age_k), wd_pct)
        started |= wd_now
        wd = np.where(wd_now, np.where(rider, bb * wd_pct, NONRIDER_WD_PCT * av), 0.0)
        from_av = np.minimum(wd, av)
        av -= from_av
        insurer_paid += wd - from_av
        cum_wd += wd
        last_wd = np.where(wd_now, wd, last_wd)
        mgsv = np.maximum(0.0, mgsv - wd)

    attained = issue_age + done
    last_anniv = pd.Series([d + pd.DateOffset(years=int(k)) for d, k in zip(issue, done)])
    policy_year = done + 1

    # estimated benefit base and withdrawal at the start of withdrawals (not yet started):
    # rolls up the current benefit base for the roll-up years left before wd_age; ignores
    # future premiums, fees and ratchets
    yrs_to_wd = np.where(takes_wd, np.maximum(0, np.ceil(np.nan_to_num(wd_age) - attained)), 0).astype(int)
    roll_left = np.clip(np.minimum(ROLLUP_YEARS, done + yrs_to_wd) - done, 0, None)
    est_bb = np.where(rider & ~started, bb * (1 + ROLLUP_RATE) ** roll_left, bb)
    start_age = np.maximum(np.nan_to_num(wd_age), attained + 1)
    est_pct = np.where(started, wd_pct, wd_pct_for_age(start_age))
    est_wd = np.where(rider, est_bb * est_pct, 0.0)

    out = pd.DataFrame({
        "pol_num": p["pol_num"], "product": PRODUCT, "gender": p["gender"],
        "issue_date": issue.dt.date, "issue_age": issue_age, "attained_age": attained,
        "current_duration": done, "qual": p["qual"],
        # premiums and deferral
        "initial_premium": init, "planned_premium": planned, "premium_mode": "annual",
        "premium_end_age": issue_age + PREMIUM_YEARS, "cumulative_premiums": cum_prem,
        "maturity_age": MATURITY_AGE,
        # index crediting
        "index_name": INDEX_NAME, "crediting_method": CREDITING_METHOD,
        "index_alloc_pct": INDEX_ALLOC, "cap_rate": CAP_RATE, "cap_guaranteed_min": CAP_GUARANTEED_MIN,
        "floor_rate": FLOOR_RATE, "participation_rate": PARTICIPATION, "fixed_rate": FIXED_RATE,
        "last_anniv_date": last_anniv.dt.date, "index_value_last_anniv": level(last_anniv),
        # values
        "account_value": av, "index_account_value": av * INDEX_ALLOC,
        "fixed_account_value": av * (1 - INDEX_ALLOC),
        "cumulative_withdrawals": cum_wd,
        "death_benefit": np.maximum(cum_prem - cum_wd, av),
        "mgsv": mgsv, "mgsv_rate": MGSV_RATE,
        # surrender terms
        "sc_period": SC_PERIOD,
        "sc_pct_current": np.where(policy_year <= SC_PERIOD, SC0 * (SC_PERIOD - policy_year + 1) / SC_PERIOD, 0.0),
        "free_withdrawal_pct": FREE_WD_PCT,
        # income rider and withdrawals
        "has_income_rider": rider, "rider_type": np.where(rider, RIDER_TYPE, ""),
        "rider_fee_pct": np.where(rider, RIDER_FEE, 0.0),
        "rollup_rate": np.where(rider, ROLLUP_RATE, 0.0),
        "rollup_years_left": np.where(rider & ~started, np.clip(ROLLUP_YEARS - done, 0, None), 0),
        "benefit_base": bb, "cumulative_rider_fees": cum_fee,
        "wd_start_age": wd_age, "withdrawals_started": started,
        "wd_pct": np.where(rider, est_pct, np.where(takes_wd, NONRIDER_WD_PCT, 0.0)),
        "current_annual_wd": np.where(started, last_wd, 0.0),
        "est_benefit_base_at_wd_start": np.where(rider, est_bb, 0.0),
        "est_annual_wd": np.where(rider, np.where(started, last_wd, est_wd),
                                  np.where(takes_wd, NONRIDER_WD_PCT * av, 0.0)),
        "insurer_paid_withdrawals": insurer_paid,
        "av_exhausted": rider & (av <= 1e-9) & started,
    })
    out.insert(0, "valuation_date", VAL_DATE.date())
    sizes = ct.write_tables(out, *terms_tables(), census_dir=OUT_DIR)
    if WRITE_WIDE_CSV:
        out.to_csv(WIDE_CSV, index=False)

    # ---- checks ----
    print(f"{n:,} in-force FIA policies at {VAL_DATE.date()} -> {OUT_DIR}/")
    for name, (rows, cols) in sizes.items():
        print(f"  {name + '.csv':24s} {rows:>7,} rows x {cols:>2} columns")
    print(f"with income rider: {rider.mean():.0%}; withdrawing: {started.mean():.0%} "
          f"(rider {started[rider].mean():.0%}, no rider {started[~rider].mean() if (~rider).any() else 0:.0%})")
    g = out.groupby("has_income_rider")
    print(g[["account_value", "benefit_base", "cumulative_premiums", "cumulative_withdrawals",
             "death_benefit"]].mean().round(0).to_string())
    rid = out[out["has_income_rider"]]
    if len(rid):
        print(f"\nrider policies: benefit base / account value, median {(rid['benefit_base'] / rid['account_value'].clip(lower=1)).median():.2f}; "
              f"withdrawal % used: {sorted(rid['wd_pct'].unique().round(3))}")
        print(f"death benefit above account value (premium guarantee binding): "
              f"{(out['death_benefit'] > out['account_value'] + 1e-6).mean():.1%} of policies")
    assert (av >= -1e-9).all() and (out["death_benefit"] >= av - 1e-9).all()
    assert (bb[rider] >= init[rider] - 1e-9).all(), "benefit base fell below the initial premium"


if __name__ == "__main__":
    main()