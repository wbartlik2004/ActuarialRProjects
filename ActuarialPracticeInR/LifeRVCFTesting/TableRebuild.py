import pandas as pd

FILES = {
    "male_ns":   "LifeRVCFTesting/2015_VBT_Male_Nonsmoker_ALB.csv",
    "male_s":    "LifeRVCFTesting/2015_VBT_Male_Smoker_ALB.csv",
    "female_ns": "LifeRVCFTesting/2015_VBT_Female_Nonsmoker_ALB.csv",
    "female_s":  "LifeRVCFTesting/2015_VBT_Female_Smoker_ALB.csv",
}

N_AGES, N_DUR, N_ULT = 78, 25, 103
EXPECTED = N_AGES * N_DUR + N_ULT 

select, ultimate = {}, {}

for key, path in FILES.items():
    vals = pd.read_csv(path)["vals"].to_numpy()
    if len(vals) != EXPECTED:
        print(f"{key}: expected {EXPECTED} values, got {len(vals)}, skipping")
        continue

    select[key] = pd.DataFrame(
        vals[: N_AGES * N_DUR].reshape(N_AGES, N_DUR),
        index=pd.Index(range(18, 96), name="IssueAge"),
        columns=pd.Index(range(1, 26), name="Duration"),
    )
    ultimate[key] = pd.Series(
        vals[N_AGES * N_DUR :],
        index=pd.Index(range(18, 121), name="AttainedAge"),
        name="q_ultimate",
    )

    # sanity check: select rates merge into ultimate at the oldest ages
    assert select[key].loc[95, 2] == ultimate[key].loc[96], f"{key}: select/ultimate mismatch"

    select[key].to_csv(f"vbt_{key}_alb_select.csv")
    ultimate[key].to_csv(f"vbt_{key}_alb_ultimate.csv")
    print(f"{key}: ok | q(18,1)={select[key].loc[18, 1]}, q(40,1)={select[key].loc[40, 1]}, "
          f"q(40,25)={select[key].loc[40, 25]}, ult(65)={ultimate[key].loc[65]}")

def q(table, issue_age, duration):
    """One-year death probability. table is a key like 'male_ns'."""
    if duration <= 25:
        return select[table].loc[issue_age, duration]
    return ultimate[table].loc[issue_age + duration - 1]
