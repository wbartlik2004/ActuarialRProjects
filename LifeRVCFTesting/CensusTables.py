"""
Write and read the FIA census as a set of smaller tables instead of one wide file.

Files in CENSUS_DIR, and what joins them:

  policies.csv          one row per policy, things fixed at issue        key: pol_num
  inforce_values.csv    one row per policy, values at the valuation date key: pol_num
  rider_values.csv      rider policies only, benefit base and withdrawals key: pol_num
  product_terms.csv     one row per product: crediting, surrender, MGSV   key: product
  surrender_charges.csv surrender charge % by product and policy year    key: product, policy_year
  rider_terms.csv       one row per rider type: fee, roll-up             key: rider_type
  withdrawal_bands.csv  lifetime withdrawal % by age at first withdrawal key: rider_type, min_age

Each valuation only rewrites inforce_values.csv and rider_values.csv; the terms tables
change only when the product design changes.

load_census() joins them back into the one-row-per-policy layout the projection uses.
"""
import os
import numpy as np
import pandas as pd

CENSUS_DIR = "LifeRVCFTesting/FIACensus"   # change the folder here; BuildFIACensus uses it too

POLICY_COLS = ["pol_num", "product", "gender", "issue_date", "issue_age", "qual",
               "has_income_rider", "rider_type", "initial_premium", "planned_premium",
               "premium_mode", "premium_end_age", "wd_start_age"]
VALUE_COLS = ["pol_num", "valuation_date", "attained_age", "current_duration",
              "last_anniv_date", "index_value_last_anniv", "account_value",
              "index_account_value", "fixed_account_value", "cumulative_premiums",
              "cumulative_withdrawals", "withdrawals_started", "current_annual_wd",
              "death_benefit", "mgsv", "sc_pct_current"]
RIDER_VALUE_COLS = ["pol_num", "benefit_base", "rollup_years_left",
                    "wd_pct", "est_benefit_base_at_wd_start",
                    "est_annual_wd", "cumulative_rider_fees", "insurer_paid_withdrawals",
                    "av_exhausted"]
# what a policy without the rider gets in the rider columns after the join
NO_RIDER_FILL = {"benefit_base": 0.0, "rollup_years_left": 0,
                 "est_benefit_base_at_wd_start": 0.0,
                 "cumulative_rider_fees": 0.0, "insurer_paid_withdrawals": 0.0,
                 "av_exhausted": False, "rider_fee_pct": 0.0, "rollup_rate": 0.0,
                 "rollup_years": 0}


def write_tables(wide, product_terms, sc_schedule, rider_terms, wd_bands, census_dir=CENSUS_DIR):
    """wide: the one-row-per-policy census from BuildFIACensus. The other four are small
    DataFrames of terms. Withdrawals apply to every policy, so withdrawals_started and
    current_annual_wd live in inforce_values; rider_values holds only rider amounts."""
    os.makedirs(census_dir, exist_ok=True)
    rider = wide["has_income_rider"].to_numpy(dtype=bool)

    values = wide[VALUE_COLS].copy()
    values["nonrider_annual_wd"] = np.where(rider, 0.0, wide["est_annual_wd"])
    rider_values = wide.loc[rider, RIDER_VALUE_COLS]

    tables = {
        "policies": wide[POLICY_COLS],
        "inforce_values": values,
        "rider_values": rider_values,
        "product_terms": product_terms,
        "surrender_charges": sc_schedule,
        "rider_terms": rider_terms,
        "withdrawal_bands": wd_bands,
    }
    for name, df in tables.items():
        df.to_csv(f"{census_dir}/{name}.csv", index=False)
    return {name: (len(df), df.shape[1]) for name, df in tables.items()}


def load_census(census_dir=CENSUS_DIR):
    """Join the tables into one row per policy (policy + values + product terms + rider)."""
    read = lambda name, **kw: pd.read_csv(f"{census_dir}/{name}.csv", **kw)
    pol = read("policies", parse_dates=["issue_date"])
    pol["rider_type"] = pol["rider_type"].fillna("").astype(str)
    vals = read("inforce_values", parse_dates=["valuation_date", "last_anniv_date"])
    prod = read("product_terms")
    riders = read("rider_terms")
    rv = read("rider_values")

    df = (pol.merge(vals, on="pol_num", how="left", validate="one_to_one")
             .merge(prod, on="product", how="left", validate="many_to_one")
             .merge(riders, on="rider_type", how="left", validate="many_to_one")
             .merge(rv, on="pol_num", how="left", validate="one_to_one"))

    for col, val in NO_RIDER_FILL.items():
        if col in df:
            df[col] = df[col].fillna(val)
    no_rider = ~df["has_income_rider"].astype(bool)
    df["wd_pct"] = np.where(no_rider, np.where(df["wd_start_age"].notna(), df["nonrider_wd_pct"], 0.0),
                            df["wd_pct"])
    df["est_annual_wd"] = np.where(no_rider, df["nonrider_annual_wd"], df["est_annual_wd"])
    for col in ("withdrawals_started", "av_exhausted"):
        df[col] = df[col].astype(bool)

    missing = df["account_value"].isna().sum() + df["cap_rate"].isna().sum()
    assert missing == 0, "some policies have no values row or no product terms row"
    return df


def load_surrender_charges(census_dir=CENSUS_DIR):
    """{product: Series of SC fraction indexed by policy year}; 0 after the last listed year."""
    sc = pd.read_csv(f"{census_dir}/surrender_charges.csv")
    return {p: g.set_index("policy_year")["sc_pct"] / 100.0 for p, g in sc.groupby("product")}


def load_withdrawal_bands(census_dir=CENSUS_DIR):
    """{rider_type: [(min_age, wd_pct), ...]} sorted by age."""
    b = pd.read_csv(f"{census_dir}/withdrawal_bands.csv").sort_values("min_age")
    return {r: list(zip(g["min_age"], g["wd_pct"])) for r, g in b.groupby("rider_type")}


if __name__ == "__main__":
    # Running this file on its own does not build anything: BuildFIACensus.py builds the
    # census and calls write_tables(). This just checks what is already in CENSUS_DIR.
    if not os.path.exists(f"{CENSUS_DIR}/policies.csv"):
        raise SystemExit(f"no census in {CENSUS_DIR}/ yet: run BuildFIACensus.py first "
                         "(it writes the 7 tables)")
    for name in ["policies", "inforce_values", "rider_values", "product_terms",
                 "surrender_charges", "rider_terms", "withdrawal_bands"]:
        t = pd.read_csv(f"{CENSUS_DIR}/{name}.csv")
        print(f"{name + '.csv':24s} {len(t):>7,} rows x {t.shape[1]:>2} columns")
    df = load_census()
    print(f"\nload_census(): {len(df):,} policies x {df.shape[1]} columns, "
          f"{df['has_income_rider'].astype(bool).mean():.0%} with the income rider")