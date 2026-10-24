# Actuarial Data Cleanup & Missing Value Imputation

This project explores how different data cleaning and missing value techniques impact life insurance policy data and downstream actuarial models.

It uses a synthetic dataset of enterprise policy records to walk through data hygiene, chronological audits, and a comparison of four missingness strategies.

`GenerateRawData.R`

Creates a realistic, messy insurance policy extract (`enterprise_policy_extract.csv`). It simulates fields like Issue Date, Effective Date, Termination Date, Smoker Status, Gender, and Face Amount—intentionally mixing in bad values, formatting inconsistencies, and missing data:

* Gender entries formatted as `"M"`, `"F"`, `"Male"`, `"Female"`, `"U"`, or left blank/`NA`.
* Temporal issues where termination dates occur before issue dates.
* Negative premiums and missing face amounts.

`CleaningRawData.R`

Cleans the raw extract, standardizes string values, fixes date logic, and focuses the dataset specifically on a 2023 policy experience study window.

It then applies four different missing data strategies and outputs four distinct CSV files:

* `1DropNA.csv` (Complete-Case): Drops any row containing missing or unknown values.
* `2MeanModeReplacement.csv` (Single Imputation): Replaces missing numerical values with the column mean and categorical blanks with the most frequent value (mode).
* `3DeterministicRegression.csv` (Regression Imputation): Uses a linear model to calculate replacement values directly off a predicted formula line based on known policy features.
* `4StochasticImputation.csv` (Stochastic Imputation): Uses regression predictions but adds random residual noise back in to better match realistic variation in unknown values.

`GlmCleanData.R`

Plots density vs. face amount across all four tables to visually show how each cleaning technique reshapes the portfolio's distribution.

What the Plots Revealed

* Methods 2 & 3 (Mean/Mode & Deterministic Regression): Show the heaviest vertical spikes and central clumping. Because Method 2 dumps all missing records right at the mean and Method 3 follows a strict formula line, values cluster artificially in the center and destroy natural data spread.
* Method 1 (Drop NA):** Gives a tamer, fairly uniform curve that matches the underlying missingness setup. However, it suffers from a reduced sample size because so many rows get thrown out.
* Method 4 (Stochastic Imputation): Looks the most stable and realistic. It preserves row count while spreading values out with statistical noise, keeping the natural curve you'd expect in an actual portfolio.


# Stochastic Loss Reserving in R

## Overview

Reserve estimates depend heavily on which method is used and which assumptions go into it. This project applies several standard reserving techniques to the same cumulative loss triangle and compares the results, the uncertainty around them, and their sensitivity to key judgments.

**Data:** `GenIns`, the 10x10 cumulative general insurance loss triangle included in the `ChainLadder` package (Taylor & Ashe, 1983).

## Methods

| Method | Type | What it does |
|---|---|---|
| Chain-Ladder | Deterministic, development-based | Projects ultimates using volume-weighted age-to-age factors |
| Bornhuetter-Ferguson | Deterministic, blended | Adds expected unreported losses (a priori ultimate x % undeveloped) to actual losses to date |
| Mack | Stochastic, distribution-free | Same mean as chain-ladder, plus process and parameter error, giving a standard error and CV |
| Bootstrap (ODP-style, gamma process error) | Stochastic, simulation | 5,000 simulations of the full reserve distribution, used to read off 75th/90th/95th percentiles |

## Diagnostics

- Calendar year effect: ANOVA on accident year and calendar year factors to test whether diagonal effects (e.g., inflation or claims-handling changes) violate chain-ladder's assumptions.
- Tail factor sensitivity: Reserves re-estimated under tail factors of 1.00, 1.02, 1.05, and 1.10. Because the tail multiplies cumulative ultimate but not paid-to-date, a small tail change moves the reserve by a much larger percentage.

## Key Findings

Mack was better than chain-ladder at giving a range of estimates instead of a single value, since it adds a standard error around the same reserve. I used bootstrapping as a separate method to simulate the whole reserve distribution, which also let me find VaR percentiles. BF gave a different estimate than chain-ladder because it blends the actual losses with an a priori assumption, so the recent years don't rely as heavily on a few early data points. It's more stable, but it's only as good as the a priori, and mine was an assumed placeholder. Chain-ladder is the one that can get caught in noise if a recent year happens to be out of the norm. The tail factors were interesting to test because raising the tail from 1.00 to 1.10 increased the reserve by 28.4%, way more than 10%. Using the ANOVA test, I found the calendar year effect to be significant with a p-value less than 0.001, which suggests chain-ladder's assumption that development only depends on age may not fully hold for this data.

## Assumptions and Limitations

- `GenIns` has no premium data, so BF uses an **assumed** earned premium and a 65% expected loss ratio. The BF result reflects those placeholder inputs and is illustrative, not a real a priori estimate.
- Tail factors are chosen scenarios, not fitted from data.
- Results are for one triangle (cumulative losses, one line of business) and ignore reinsurance, discounting, and risk margins.
- Mack assumes independence across accident years and a variance proportional to cumulative losses.

