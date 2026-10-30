"""
Lee-Carter fit on HMD period life table death rates (mx) -> improvement factors,
then applies those factors to the SOA 2012 IAM annuity tables.

Step 1: fits Lee-Carter per sex and writes improvement factor CSVs, measured from
        BASE_YEAR = 2012 (the year the 2012 IAM tables represent).
Step 2: reads the 2012 IAM Basic and Period tables saved by SOATableQueryAnnuity.py
        and writes projected (generational) tables for 2012-2100:
            best estimate: q(x, Y) = IAM Basic q(x)  x factor(x, Y)
            loaded:        q(x, Y) = IAM Period q(x) x factor(x, Y)
        Period = Basic x margin, so the loaded table is the Basic table with the NAIC
        margin applied, improved with Lee-Carter instead of Scale G2.

The fit still uses data through 2019 (COVID kept out). Factors for 2013-2019 come from the
fitted drift, not the year-by-year k(t), so they are smoothed rather than actual history.
Mortality is NOT improved above age 100 (factor = 1.0 there).
"""
import os
import numpy as np
import pandas as pd

# ---------------- settings ----------------
FILES = {                              # HMD life table files (paths relative to where you run python)
    "male":   "LifeRVCFTesting/HMDTables/HMDMale.csv",
    "female": "LifeRVCFTesting/HMDTables/HMDFemale.csv",
}
TABLE_DIR    = "LifeRVCFTesting/TablesFromSOA"    # 2012 IAM CSVs from SOATableQueryAnnuity.py
IAM_FILES    = {"male":   ("2012_IAM_Basic_Male_ANB.csv",   "2012_IAM_Period_Male_ANB.csv"),
                "female": ("2012_IAM_Basic_Female_ANB.csv", "2012_IAM_Period_Female_ANB.csv")}
LC_OUT_DIR   = "LifeRVCFTesting/LCMultipliers"    # PolicyInforce reads the factors from here
PROJ_OUT_DIR = "LifeRVCFTesting/AnnuityTables"    # projected IAM tables
FIT_AGES         = (18, 100)           # ages used in the fit (inclusive)
FIT_YEARS        = (1990, 2019)        # stop at 2019 to keep COVID out of the fit
BASE_YEAR        = 2012                # the 2012 IAM tables' base year
PROJ_YEARS       = range(2012, 2101)
MAX_AGE          = 120                 # IAM tables run to 120
NO_IMPROVE_ABOVE = 100                 # death rates unchanged above this age
Q_CAP            = 1.0                 # IAM rates reach 1.0 at age 120, so no 0.5 cap
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


# ---------------- applying factors to the 2012 IAM tables ----------------

def load_iam(filename):
    """One 2012 IAM table as a Series of q by age, ages FIT_AGES[0]-MAX_AGE."""
    s = pd.read_csv(f"{TABLE_DIR}/{filename}").set_index("age")["value"]
    s.index = s.index.astype(int)
    assert s.index.min() <= FIT_AGES[0] and s.index.max() == MAX_AGE, \
        f"{filename}: ages {s.index.min()}-{s.index.max()}"
    return s.loc[FIT_AGES[0]:MAX_AGE]


def project_table(base_q, factors):
    """Generational table: q(x, Y) = base q(x) for 2012 x improvement factor(x, Y)."""
    assert (base_q.index == factors.index).all(), "table and factor ages don't line up"
    return factors.mul(base_q.to_numpy(), axis=0).clip(upper=Q_CAP)


def apply_to_iam(all_factors):
    for sex, (basic_file, period_file) in IAM_FILES.items():
        f = all_factors[sex]
        basic, period = load_iam(basic_file), load_iam(period_file)

        # 2012 base tables in the q_ultimate layout PolicyInforce reads
        for name, q in (("basic", basic), ("period", period)):
            q.rename("q_ultimate").rename_axis("AttainedAge") \
             .to_csv(f"{PROJ_OUT_DIR}/iam_{name}_{sex}_anb.csv")

        best = project_table(basic, f)
        loaded = project_table(period, f)
        best.to_csv(f"{PROJ_OUT_DIR}/iam_basic_lc_projected_{sex}.csv")
        loaded.to_csv(f"{PROJ_OUT_DIR}/iam_loaded_lc_projected_{sex}.csv")

        margin = period / basic
        print(f"\n{sex}: margin (Period / Basic) at 40, 65, 85: "
              f"{margin.loc[40]:.3f}, {margin.loc[65]:.3f}, {margin.loc[85]:.3f}")
        for age in (65, 85):
            print(f"  best-estimate q({age}): 2012 {best.loc[age, 2012]:.5f}, "
                  f"2019 {best.loc[age, 2019]:.5f}, 2049 {best.loc[age, 2049]:.5f}  "
                  f"(x{f.loc[age, 2049]:.3f} by 2049)")
        assert np.allclose(best[BASE_YEAR], basic), "2012 column should equal the 2012 table"
        # rates should rise with age from 50 up; a dip usually means b(x) jumps between
        # neighbouring ages, or the switch to no improvement at NO_IMPROVE_ABOVE
        old = best.loc[50:, 2049]
        dips = list(old.index[1:][old.diff().dropna().to_numpy() < 0])
        if dips:
            print(f"  note: 2049 rates dip with age at {dips}")


if __name__ == "__main__":
    os.makedirs(LC_OUT_DIR, exist_ok=True)
    os.makedirs(PROJ_OUT_DIR, exist_ok=True)
    all_factors = {sex: run_fit(sex, path) for sex, path in FILES.items()}
    apply_to_iam(all_factors)
    print(f"\nwrote factors to {LC_OUT_DIR}/ and projected tables to {PROJ_OUT_DIR}/")