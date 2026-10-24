# pip install pymort pandas
import pandas as pd
from pymort import MortXML

# Look up the real IDs at https://mort.soa.org (search "2015 VBT") and fill in.
# The name check below stops a wrong ID from being saved under the wrong filename.
TABLES = {
    3247: "2015_VBT_Male_Nonsmoker_ALB.csv",
    3248: "2015_VBT_Male_Smoker_ALB.csv",
    3251: "2015_VBT_Female_Nonsmoker_ALB.csv",
    3252: "2015_VBT_Female_Smoker_ALB.csv",
}

def fetch_2015_vbt_tables():
    for table_id, filename in TABLES.items():
        print(f"Fetching table {table_id}...")
        try:
            xml = MortXML.from_id(table_id)
        except Exception as e:
            print(f"  Failed: {e}")
            continue

        name = xml.ContentClassification.TableName
        print(f"  Table name: {name}")

        # Select-and-ultimate tables may come back as several sub-tables
        dfs = [t.Values for t in xml.Tables]
        df = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]

        df.to_csv(filename, index=False)
        print(f"  Saved {filename} ({len(df)} rows)")

if __name__ == "__main__":
    fetch_2015_vbt_tables()