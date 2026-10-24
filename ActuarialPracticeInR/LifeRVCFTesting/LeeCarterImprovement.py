"""
Lee-Carter fit on HMD period life table death rates (mx) -> improvement factors,
then applies those factors to the 2015 VBT select and ultimate tables.

Step 1 (run): fits Lee-Carter per sex and writes improvement factor CSVs.
Step 2 (run): reads the VBT CSVs written by the earlier VBT script
              (vbt_<key>_alb_select.csv / vbt_<key>_alb_ultimate.csv) and writes
              improved versions for each year in IMPROVE_TO_YEARS.

Mortality is NOT improved above age 100 (factor = 1.0 there).
"""
import numpy as np
import pandas as pd

# ---------------- settings ----------------
FILES = {                              # HMD life table files (paths relative to where you run python)
    "male":   "LifeRVCFTesting/HMDMale.csv",
    "female": "LifeRVCFTesting/HMDFemale.csv",
}
SELECT_DIR   = "LifeRVCFTesting/SelectTables"     # vbt_<key>_alb_select.csv lives here
ULTIMATE_DIR = "LifeRVCFTesting/UltimateTables"   # vbt_<key>_alb_ultimate.csv lives here
LC_OUT_DIR   = "LifeRVCFTesting"                  # where lc_*.csv outputs are written
VBT_KEYS         = ["male_ns", "male_s", "female_ns", "female_s"]
FIT_AGES         = (18, 100)           # ages used in the fit (inclusive)
FIT_YEARS        = (1990, 2019)        # stop at 2019 to keep COVID out of the fit
BASE_YEAR        = 2015                # the VBT's base year
PROJ_YEARS       = range(2015, 2101)
MAX_AGE          = 120                 # VBT ultimate runs to 120
NO_IMPROVE_ABOVE = 100                 # death rates unchanged above this age
IMPROVE_TO_YEARS = [2026]              # calendar years to build improved tables for
Q_CAP            = 0.5                 # VBT caps q at 0.5
# Fade the improvement rate so factors don't compound at full speed for 80+ years.
# Full fitted rate until GRADE_START, linear fade to ULTIMATE_WEIGHT by GRADE_END,
# then that fraction of the fitted rate afterwards (0 = no further improvement).
GRADE_START      = 2035
GRADE_END        = 2055
ULTIMATE_WEIGHT  = 0.5
FACTOR_FLOOR     = 0.0                 # optional: e.g. 0.6 = never improve more than 40%
# ------------------------------------------


def load_hmd(path, column="mx"):
    df = pd.read_csv(path, sep=r"\s+", skiprows=2, na_values=".")
    df["Age"] = df["Age"].astype(str).str.replace("+", "", regex=False).astype(int)
    return df.pivot(index="Age", columns="Year", values=column)


def fit_lee_carter(m):
    """m: DataFrame of central death rates, index=age, columns=year."""
    logm = np.log(m.to_numpy())
    a = logm.mean(axis=1)
    Z = logm - a[:, None]
    U, S, Vt = np.linalg.svd(Z, full_matrices=False)
    b, k = U[:, 0], S[0] * Vt[0]
    scale = b.sum()                     # constraint: sum(b) = 1
    b, k = b / scale, k * scale         # k then has mean zero across years
    explained = S[0] ** 2 / (S ** 2).sum()
    return a, b, k, explained


def improvement_weights(base_year, last_year):
    """Cumulative 'years of full-speed improvement' C(Y) since base_year.
    C grows by 1 per year until GRADE_START, then by a fading weight."""
    years = np.arange(base_year + 1, last_year + 1)
    w = np.where(
        years <= GRADE_START, 1.0,
        np.where(years >= GRADE_END, ULTIMATE_WEIGHT,
                 1.0 - (1.0 - ULTIMATE_WEIGHT) * (years - GRADE_START) / (GRADE_END - GRADE_START)))
    return pd.Series(np.concatenate([[0.0], np.cumsum(w)]),
                     index=np.arange(base_year, last_year + 1))


def improvement_factors(b, drift, ages, proj_years, base_year, max_age):
    """factor(x, Y) = exp(b_x * drift * C(Y)), C(Y) = cumulative faded improvement years.
    b is held flat above the fit ages, then set to 0 above NO_IMPROVE_ABOVE."""
    all_ages = np.arange(ages[0], max_age + 1)
    b_full = np.array([b[min(x, ages[-1]) - ages[0]] for x in all_ages])
    b_full = np.where(all_ages > NO_IMPROVE_ABOVE, 0.0, b_full)   # factor = 1.0 above 100
    C = improvement_weights(base_year, max(proj_years))
    out = {Y: np.maximum(np.exp(b_full * drift * C[Y]), FACTOR_FLOOR) for Y in proj_years}
    return pd.DataFrame(out, index=pd.Index(all_ages, name="Age")), b_full


def run_fit(sex, path):
    full = load_hmd(path, "mx")
    print(f"\n{sex}: years in file {full.columns.min()}-{full.columns.max()}")
    m = full.loc[FIT_AGES[0]:FIT_AGES[1], FIT_YEARS[0]:FIT_YEARS[1]]
    assert m.columns.min() == FIT_YEARS[0] and m.columns.max() == FIT_YEARS[1], \
        f"{sex}: file doesn't cover {FIT_YEARS}, only {m.columns.min()}-{m.columns.max()}"
    assert not m.isna().any().any() and (m > 0).all().all(), "missing/zero rates in fit window"
    print(m.loc[[18, 40, 65, 90], [m.columns[0], m.columns[-1]]].round(5))

    a, b, k, explained = fit_lee_carter(m)
    drift = (k[-1] - k[0]) / (len(k) - 1)
    print(f"  variance explained by first component: {explained:.1%}")
    print(f"  drift in k(t): {drift:.4f} per year")
    print(f"  average annual improvement (ages 40-80): {1 - np.exp(b[22:63].mean() * drift):.2%}")
    if (b < 0).any():
        print(f"  WARNING: negative b(x) at ages {list(m.index[b < 0])} "
              "(those ages would get worse over time)")

    pd.DataFrame({"Age": m.index, "a": a, "b": b}).to_csv(f"{LC_OUT_DIR}/lc_parameters_{sex}.csv", index=False)
    pd.DataFrame({"Year": m.columns, "k": k}).to_csv(f"{LC_OUT_DIR}/lc_k_t_{sex}.csv", index=False)
    factors, b_full = improvement_factors(b, drift, list(m.index), PROJ_YEARS, BASE_YEAR, MAX_AGE)
    factors.to_csv(f"{LC_OUT_DIR}/lc_improvement_factors_{sex}.csv")
    pd.Series(1 - np.exp(b_full * drift), index=factors.index, name="annual_improvement") \
        .to_csv(f"{LC_OUT_DIR}/lc_annual_improvement_by_age_{sex}.csv")
    return factors


# ---------------- applying factors to the VBT tables ----------------

def load_vbt(key):
    sel = pd.read_csv(f"{SELECT_DIR}/vbt_{key}_alb_select.csv", index_col=0)
    sel.columns = sel.columns.astype(int)
    ult = pd.read_csv(f"{ULTIMATE_DIR}/vbt_{key}_alb_ultimate.csv", index_col=0)["q_ultimate"]
    return sel, ult


def improve_tables(select, ultimate, factors, year):
    """Period-style improved tables: every cell is improved to calendar `year`.
    select cell (issue age x, duration d) is attained age x + d - 1."""
    f = factors[year]
    att = pd.DataFrame(
        {d: select.index + d - 1 for d in select.columns}, index=select.index
    )
    sel_f = att.apply(lambda col: col.map(f))                  # factor for each cell
    sel_imp = (select * sel_f).clip(upper=Q_CAP)
    ult_imp = (ultimate * ultimate.index.map(f).to_numpy()).clip(upper=Q_CAP)
    return sel_imp, ult_imp


def apply_to_vbt(all_factors):
    for key in VBT_KEYS:
        sex = key.split("_")[0]
        select, ultimate = load_vbt(key)
        for year in IMPROVE_TO_YEARS:
            sel_imp, ult_imp = improve_tables(select, ultimate, all_factors[sex], year)
            sel_imp.to_csv(f"{SELECT_DIR}/vbt_{key}_alb_select_improved_{year}.csv")
            ult_imp.to_csv(f"{ULTIMATE_DIR}/vbt_{key}_alb_ultimate_improved_{year}.csv")

            ratio = ult_imp / ultimate
            print(f"{key} -> {year}: ult q(40) x{ratio.loc[40]:.3f}, q(65) x{ratio.loc[65]:.3f}, "
                  f"q(100) x{ratio.loc[100]:.3f}, q(101) x{ratio.loc[101]:.3f} "
                  f"(should be 1.000 above {NO_IMPROVE_ABOVE})")
            if not ult_imp.is_monotonic_increasing:
                print(f"  note: improved ultimate rates are not strictly increasing with age "
                      f"around {NO_IMPROVE_ABOVE}; check the 100/101 boundary")


# ---------------- cohort-style helper (policy-by-policy) ----------------

def q_improved(q_base, attained_age, calendar_year, factors):
    """Improve a single VBT q for a given attained age and calendar year."""
    return min(Q_CAP, q_base * factors.loc[attained_age, calendar_year])


if __name__ == "__main__":
    all_factors = {sex: run_fit(sex, path) for sex, path in FILES.items()}
    apply_to_vbt(all_factors)