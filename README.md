# Actuarial Data Cleanup & Missing Value Imputation

This project explores how different data cleaning and missing value techniques impact life insurance policy data and downstream actuarial models.

It uses a synthetic dataset of enterprise policy records to walk through data hygiene, chronological audits, and a comparison of four missingness strategies.

## `GenerateRawData.R`

Creates a realistic, messy insurance policy extract (`enterprise_policy_extract.csv`). It simulates fields like Issue Date, Effective Date, Termination Date, Smoker Status, Gender, and Face Amount—intentionally mixing in bad values, formatting inconsistencies, and missing data:

* Gender entries formatted as `"M"`, `"F"`, `"Male"`, `"Female"`, `"U"`, or left blank/`NA`.
* Temporal issues where termination dates occur before issue dates.
* Negative premiums and missing face amounts.

## `CleaningRawData.R`

Cleans the raw extract, standardizes string values, fixes date logic, and focuses the dataset specifically on a 2023 policy experience study window.

It then applies four different missing data strategies and outputs four distinct CSV files:

* `1DropNA.csv` (Complete-Case): Drops any row containing missing or unknown values.
* `2MeanModeReplacement.csv` (Single Imputation): Replaces missing numerical values with the column mean and categorical blanks with the most frequent value (mode).
* `3DeterministicRegression.csv` (Regression Imputation): Uses a linear model to calculate replacement values directly off a predicted formula line based on known policy features.
* `4StochasticImputation.csv` (Stochastic Imputation): Uses regression predictions but adds random residual noise back in to better match realistic variation in unknown values.

## `GlmCleanData.R`

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






# LifeRVCFTesting

Cash flow testing for a block of fixed index annuities (FIAs), written in Python with an R version of the charts. The model rebuilds each policy's history from issue to a 12/31/2019 valuation date, projects it 50 years forward under 200 equity scenarios, values the liabilities at every year end, builds a bond portfolio to match them, and checks whether the assets hold up under interest rate and lapse stresses.

The policy data is simulated (see Data) and most product terms are my own assumptions, so treat this as a modeling exercise rather than a view on any real block. Amounts are in the scaled units of the source data, not dollars.

## The product

Everything here is assumed unless it says otherwise.

Premiums~Flexible: an initial premium, then 60% of policyholders add 10% of it each year through policy year 10. Premiums stop once withdrawals start.

Crediting~80% in an S&P 500 annual point-to-point strategy with a 5% cap, 0% floor and 100% participation; 20% in a fixed account at 2%

Surrender charge~10 years, starting at 7% and falling to zero

Death benefit~Greater of premiums paid less withdrawals, and account value

Minimum guaranteed surrender value~87.5% of premiums accumulated at 1%, less withdrawals

Maturity~Age 95

Income rider~(GLWB)	On the policies the source data flags with an income guarantee. 0.95% annual fee on the benefit base, 6% compound roll-up for up to 10 years while deferring, annual step-up to account value, lifetime withdrawals of 4.0% to 6.5% of the benefit base depending on age at the first withdrawal

Withdrawals without the rider~5% of account value a year from the withdrawal age in the data

The rider is a guaranteed lifetime withdrawal benefit. Once a policyholder starts withdrawing, the insurer owes the guaranteed amount every year for life, even after the account value is gone. That is where most of the rider's cost shows up.

## Pipeline

Run from the folder that contains LifeRVCFTesting, in this order.

1. SOATableQueryAnnuity.py:     Downloads the 2012 IAM Basic and Period tables and Projection Scale G2 from mort.soa.org 
2. IARBuild.py:     Builds the 2012 IAR generational table (Period x G2) as a benchmark, and the G2 factors in the same layout as the Lee-Carter factors
3. LeeCarterImprovement.py:     Fits Lee-Carter to US population mortality and applies the improvement to the IAM tables
4. StaticLapse.py:      Writes the lapse table and the low, base and high scenarios
5. MarketData.py:       Downloads S&P 500 price history
6. BuildFIACensus.py:       Rebuilds every in-force policy from issue to 12/31/2019 and writes the census as seven linked tables (CensusTables.py handles reading and writing)
7. LiabilityCashflows.py:       Projects the census under 200 index scenarios and calculates present values and reserves by year (uses PolicyInforce.py for decrements and Discounting.py for the curves)
8. AssetPortfolio.py:       Builds a cash flow matched bond portfolio and runs the year-by-year surplus test
9. Graphs.R:       Saves the charts to Graphs/

Python packages: pandas, numpy, matplotlib, pymort, yfinance. The R charts need ggplot2.

## Data

The policy data comes from the actxps R package, which describes it as simulated data for a theoretical deferred annuity. It has 20,000 policies issued from 2005 to 2019. 

From that data I kept the policy number, issue date, issue age, gender, qualified status, premium (used as the initial premium), whether the policy has an income guarantee, and the age withdrawals start. I rebuilt everything else. The account values in the package come from a different product design, so they would not be consistent with FIA crediting. Instead, each policy is rolled forward anniversary by anniversary using actual S&P 500 returns, with premiums, fees, roll-ups and withdrawals applied in order. A policy counts as in force if it was issued by 12/31/2019 and had not terminated by then, which gives 15,361 policies.

Other sources: the 2012 IAM tables and Scale G2 from the SOA's table site, US mortality rates from the Human Mortality Database, the 12/31/2019 Treasury spot curve from the FDIC Quarterly Banking Profile graph book, and S&P 500 price history from Yahoo Finance.

## Assumptions and why I made them

Mortality. The base table is the 2012 IAM Basic table, the SOA's best estimate for individual annuitants with no safety margin. I use Basic rather than Period because cash flow testing is about expected results; the Period table (Basic plus the NAIC margin) is available as a sensitivity. The IAM was built from payout annuity experience, and people who buy payout annuities tend to live longer than deferred annuity owners, so this probably understates deaths a little.

Improvement comes from a Lee-Carter model fit to US population data for 1990 to 2019, ages 18 to 100. I stopped the fit at 2019 so COVID deaths would not distort the trend, and measured improvement from 2012 because that is the year the IAM tables represent. There is no improvement above age 100, where the data is thin. The rate of improvement fades from full speed in 2035 to half speed by 2055, because a constant trend compounded over 50 years gets aggressive. That fade is a judgment call and is a setting in the script. Scale G2 can be swapped in for comparison, and the SOA's own 2012 IAR table is built as a benchmark.

I used a plain SVD fit rather than the Poisson version of Lee-Carter. It is easier to follow and good enough here.

Lapse. A static table by policy year: about 1.3% in year 1 rising to 5.3% in the last year with a surrender charge, 25% in the year the charge ends, and 7% after that. The scenarios multiply every rate by 0.5, 1.0 and 1.5. There is no real lapse data to fit a rate-sensitive model to, but a static table still captures the surrender charge cliff, which the actxps data shows in policy year 11. A policy whose account value has run out cannot surrender.

Index returns. 200 random paths with an expected price return of 5.5% and 16% volatility (lognormal). The same paths are used for every scenario, so differences between scenarios come from the assumptions being tested, not from noise. With a 5% cap and 0% floor, the average credit is a bit under 3%.

Discounting. The 12/31/2019 Treasury spot curve, with straight-line interpolation between published maturities and flat past 30 years. I have not checked the FDIC figures against Treasury's own data. Stresses are parallel shifts of plus and minus 100bp, floored at zero.

Reserves by year. The reserve at the end of each year is the value of all remaining expected cash flows on the same curve, using its forward rates, plus any account value still owed at the end of the horizon. I report it next to the account value and cash surrender value in force, so you can see how far the liability sits above what policyholders could walk away with. I also report CTE70, the average liability across the worst 30% of index scenarios.

Assets. Starting assets equal the time-0 reserve. The portfolio is built by cash flow matching: working back from 30 years, I buy enough of each maturity (60% corporate, 40% Treasury) for coupons and principal to cover that year's expected net outflow. Liabilities past year 30 are folded into the 30-year bond. Corporates yield more than the Treasury curve the reserve is discounted at, so the matched bonds cost less than the reserve, and the difference starts out as cash. The corporate spreads (40 to 150bp) are assumptions.

Surplus test. For each of 12 scenarios (three lapse levels times three rate curves, plus base lapse without mortality improvement), bond cash flows are fixed, the cash account rolls forward at that scenario's one-year forward rates, and each year I compare assets (cash plus bond market value) with the reserve.

## Results

Liabilities. Under base assumptions the PV of liabilities is 24.6 million, and CTE70 across the index scenarios is 25.7 million. Effective duration is 8.5 years. Over the 50-year projection the block pays out 30.7 million (undiscounted): 15.4 million in surrenders, 9.6 million in withdrawals from account value, 4.0 million in death benefits, 1.4 million in withdrawals the insurer pays after accounts run dry, and 0.3 million at maturity. Premiums bring in 1.5 million.

PV of liabilities (millions)	Rates down 100bp	Baseline	Rates up 100bp
Low lapse	                          28.23	         25.24	       22.73
Base lapse	                          26.89	         24.65	       22.71
High lapse	                          26.12	         24.35	       22.77

Low lapse is the most expensive case when rates fall, but the order flips when rates rise and the three lapse scenarios end up within 0.3% of each other. Lapse mostly changes when money is paid, and a higher discount rate shrinks the cost of paying later.

The rider. The rider's cost in this model is the PV of withdrawals paid after the account value is gone: 0.86 million under base assumptions, about 3.5% of the liability. It depends heavily on lapse. It roughly doubles to 1.65 million under low lapse and halves to 0.45 million under high lapse, because every policy that stays in force is another lifetime of guaranteed payments. Under low lapse, undiscounted insurer-paid withdrawals (2.7 million) exceed the rider fees collected (2.5 million), so the rider loses money on its own terms. Under base and high lapse the fees cover it.

Mortality improvement raises the base PVL by 0.4%. That is the opposite direction from a plain deferred annuity, where longer lives barely matter because the death benefit is just the account value. Here people who live longer keep drawing their guaranteed withdrawals.

Surplus. Matching the bonds to the base cash flows left 5.6% of the reserve as starting cash, because the corporates yield more than the Treasury curve the reserve is discounted at. That spread is effectively the block's cushion.

Ending surplus stayed positive in all 12 scenarios, but four of them start in a hole. The assets were sized to the base reserve, and these scenarios need a bigger one: low lapse with rates down starts 1.58 million short (5.6% of its reserve), low lapse at baseline rates 0.59 million, base lapse with rates down 0.24 million, and base lapse without improvement and rates down 0.08 million. In every scenario the low point is at time 0, and the extra yield on the corporates closes the gap from there. That happens within a year or two in the milder cases, by year 5 for low lapse at baseline rates, and not until year 26 for low lapse with rates down.

PV of ending surplus as a share of the baseline reserve:

Ending surplus  	Rates down 100bp	Baseline	Rates up 100bp
Low lapse            	0.09%	          3.20%	        5.55%
Base lapse	            5.53%	          5.59%	        5.62%
High lapse	            8.64%	          6.82%     	5.37%
Base lapse, no improvement	6.17%	      6.00%	        5.85%

Under base lapse a 100bp shift barely moves the result, since the portfolio was matched to those cash flows. Lapse is what moves it. The worst case is low lapse with rates down, where the cushion is almost entirely used up (0.09%, about 21 thousand). More policies stay in force than the bonds were bought for, their payments run longer, and the cash covering them earns less. High lapse goes the other way: surrenders arrive before the bonds mature, so the portfolio borrows for 12 years, but it finishes with the most surplus because fewer policies are left to draw on the rider.

Assets vs reserve by scenario
(See in Graphs)

## Limitations
Caps, fees and the fixed rate stay at today's levels in every scenario. In practice insurers reset caps when rates move, and that is their main lever for managing an FIA block.
Lapse is static and the same with or without the rider. Policyholders whose rider is worth more than their account rarely lapse, so this understates the rider's cost. A dynamic lapse that depends on how far the rider is in the money is the next thing I would add.
Rate shocks change discount and reinvestment rates but not policyholder behavior, so the model cannot show true disintermediation.
The hedge is not modeled. A real FIA writer buys call options to fund index credits; here the credits are simply paid.
Bonds have no defaults, calls or sales.
No expenses, commissions, taxes or capital requirements.
The valuation date is 12/31/2019, so 2020 onward is projected even though it has happened, including COVID mortality.
Index scenarios are a simple lognormal model, and the parallel rate shocks are not a full regulatory scenario set such as the New York 7.
The policy data is simulated and most product terms are assumed, so the results say nothing about a real block.
