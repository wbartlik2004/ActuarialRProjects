# pip install pymort pandas
"""
Fetch the SOA 2012 individual annuity mortality tables from mort.soa.org.

  2012 IAM Basic  (2581 male, 2582 female): experience mortality brought to 2012, NO margin
                   -> best estimate, the table to use for CFT and to apply Lee-Carter to
  Scale G2        (2583 male, 2584 female): annual mortality improvement rates by age
  2012 IAM Period (2585 male, 2586 female): the Basic table plus the NAIC margins
                   -> starting point of the 2012 IAR reserving table
  2012 IAR        : not stored as one table; it is Period q x (1 - G2)^(year - 2012),
                    built by IARBuild.py

All are age nearest birthday (ANB) and aggregate (no select period). The IAM tables run
to age 120; the G2 tables on mort.soa.org stop at 105 (the rates are 0 from 104 up).
The name check stops a wrong ID being saved under the wrong filename.
"""
import os
import pandas as pd
from pymort import MortXML

OUT_DIR = "LifeRVCFTesting/TablesFromSOA"

# (table id, filename, text that must be in the table name, sex)
TABLES = [
    (2581, "2012_IAM_Basic_Male_ANB.csv",    "IAM Basic",  "male"),
    (2582, "2012_IAM_Basic_Female_ANB.csv",  "IAM Basic",  "female"),
    (2583, "Scale_G2_Male_ANB.csv",          "G2",         "male"),
    (2584, "Scale_G2_Female_ANB.csv",        "G2",         "female"),
    (2585, "2012_IAM_Period_Male_ANB.csv",   "IAM Period", "male"),
    (2586, "2012_IAM_Period_Female_ANB.csv", "IAM Period", "female"),
]


def name_matches(name, kind, sex):
    n = name.lower()
    female = "female" in n
    right_sex = female if sex == "female" else ("male" in n and not female)
    return kind.lower() in n and right_sex


def to_frame(xml):
    """First table as two columns: age, value."""
    df = xml.Tables[0].Values.reset_index()
    if df.shape[1] == 2:
        df.columns = ["age", "value"]
    return df


def fetch():
    os.makedirs(OUT_DIR, exist_ok=True)
    for tid, filename, kind, sex in TABLES:
        try:
            xml = MortXML.from_id(tid)
        except Exception as e:
            print(f"{tid}: failed: {e}")
            continue
        name = xml.ContentClassification.TableName
        if not name_matches(name, kind, sex):
            print(f"{tid}: '{name}' does not look like {kind} {sex}; NOT saved")
            continue
        if len(xml.Tables) > 1:
            print(f"  note: {tid} has {len(xml.Tables)} sub-tables; saving the first")
        df = to_frame(xml)
        df.to_csv(f"{OUT_DIR}/{filename}", index=False)
        print(f"{tid}: {name} -> {filename} ({len(df)} rows, "
              f"ages {df['age'].min()}-{df['age'].max()})")


if __name__ == "__main__":
    fetch()