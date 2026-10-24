"""
Build an in-force deferred annuity census from the actxps sample data
(census_dat.csv and account_vals.csv, exported from the actxps package).

The actxps data is SIMULATED by the package authors for a theoretical deferred annuity.
It has no credited rate and no surrender charge terms, so those columns are ASSUMED here.
Valuation date is 2019-12-31, the last issue date in the data.
"""
import numpy as np
import pandas as pd

# ---------------- settings ----------------
DIR            = "LifeRVCFTesting/Census"
VAL_DATE       = pd.Timestamp("2019-12-31")
SC_PERIOD      = 10          # the data's surrender spike is in policy year 11
SC0            = 7.0         # assumed initial surrender charge, percent
CREDITED_RATE  = 0.03        # assumed, not in the data
# ------------------------------------------


def main():
    c  = pd.read_csv(f"{DIR}/census_dat.csv", parse_dates=["issue_date", "term_date"])
    av = pd.read_csv(f"{DIR}/account_vals.csv", parse_dates=["pol_date_yr"])

    # in force at the valuation date = issued by then and not yet terminated.
    # (The data runs into 2020, so status == "Active" alone would drop policies that
    # were still in force on VAL_DATE and terminated afterward.)
    act = c[(c["issue_date"] <= VAL_DATE) &
            (c["term_date"].isna() | (c["term_date"] > VAL_DATE))].copy()
    act["current_duration"] = np.floor((VAL_DATE - act["issue_date"]).dt.days / 365.25).astype(int)
    act["attained_age"] = act["age"] + act["current_duration"]

    last = (av[av["pol_date_yr"] <= VAL_DATE].sort_values("pol_date_yr")
            .groupby("pol_num").tail(1)[["pol_num", "av_anniv"]]
            .rename(columns={"av_anniv": "account_value"}))
    act = act.merge(last, on="pol_num", how="left")
    # policies issued on the valuation date have no anniversary yet: use the premium
    act["account_value"] = act["account_value"].fillna(act["premium"])

    # assumed product terms
    act["sc_period"] = SC_PERIOD
    policy_year = act["current_duration"] + 1
    act["sc_pct_current"] = np.where(policy_year <= SC_PERIOD,
                                     SC0 * (SC_PERIOD - policy_year + 1) / SC_PERIOD, 0.0)
    act["credited_rate"] = CREDITED_RATE

    cols = ["pol_num", "product", "gender", "issue_date", "age", "attained_age",
            "current_duration", "qual", "inc_guar", "wd_age", "premium", "account_value",
            "sc_period", "sc_pct_current", "credited_rate"]
    out = act[cols].rename(columns={"age": "issue_age"})
    out.to_csv(f"{DIR}/inforce_census.csv", index=False)

    print(f"{len(out):,} in-force policies at {VAL_DATE.date()}")
    print(out[["issue_age", "attained_age", "current_duration", "premium", "account_value"]]
          .describe().round(1).T)
    print(out["current_duration"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()