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


# Actuarial Data Cleanup

Policy data rarely arrives clean. Codes are inconsistent, ages are impossible, dates are out of order, and values are missing. How you handle that changes the experience study built on top of it. This project simulates a messy life insurance extract, cleans it, fills in missing values four different ways, and checks which method gets closest to the truth, both in the data itself and in the mortality rates a model estimates from it.

The data is simulated and is written in R with the tidyverse. Run the scripts in order from the folder that contains CleaningLifeData.

## GenerateRawData.R

Simulates 25,000 policies issued from 2010 to 2023 and pulled from the admin system on 12/31/2025.

Each policy gets a true issue age, gender, smoker status and face amount. Mortality follows a Gompertz-Makeham curve by age, multiplied by 1.25 for males and 2.1 for smokers. Premium is the cost of insurance plus a 30% loading with some random variation, so it depends on face amount and the policyholder's mortality. Each policy is then run forward year by year until it dies, lapses or surrenders, or reaches the extract date still in force. Active policies have no termination date, and terminated policies end on the date of their event.

The true values are saved to ground_truth.csv. The extract (enterprise_policy_extract.csv) then gets the kinds of problems real extracts have:

gender and smoker status recorded in mixed formats ("M", "Male", "NS", "Non-Smoker"), with 14% of genders and 20% of smoker statuses unknown
15% of statuses replaced by system error codes (99, ERR, NULL, EXPIRED)
termination dates before issue dates, ages of -99 and 130, and negative premiums
missing face amounts, premiums and dates

All of the missing values are removed completely at random, which matters for which method is unbiased (see below).

## CleaningRawData.R

Cleaning. Standardizes the codes, then applies one rule at a time and records how many policies each removes in cleaning_log.csv, so every dropped record is accounted for. The rules remove duplicate IDs, impossible ages, negative premiums, missing issue dates, invalid status codes, terminated policies with no termination date, termination before issue, and active policies that have a termination date. I treat EXPIRED as an error code rather than a lapse, because in this data it is one. After cleaning, a set of checks stops the script if any rule is still broken.

Four ways to handle missing values. Each one writes its own file:

1DropNA.csv, complete-case: drops any policy with a missing face amount, premium, gender or smoker status.
2MeanModeReplacement.csv, mean/mode: fills numbers with the average and categories with the most common value, both calculated from the data.
3DeterministicRegression.csv, regression: predicts missing face amounts from premium and age, and missing premiums from face amount and age. Both models are on the log scale, since premium is roughly proportional to face amount. Gender and smoker status use the mode.
4StochasticImputation.csv, stochastic regression: the same regressions plus random error the size of each model's typical miss, so the filled-in values vary the way real ones do. Working on the log scale keeps every value positive. Gender and smoker status are drawn at random in proportion to the known mix instead of all being set to the most common value.

Exposure. Each table gets exposure for a 2019 to 2023 study. Active policies are exposed through the end of the study. Terminated policies are exposed to their termination date, and the termination counts as an event only if it happens inside the window.

## GlmCleanData.R

Compares the methods three ways:

Distribution. A density plot of face amounts for each method (imputation_plot.png).
Mortality. A Poisson GLM of deaths with a log link and log(exposure) as an offset, fitted to each table, so the coefficients are mortality multipliers that can be compared with the true 1.25 and 2.1 (glm_multipliers.png, glm_multipliers.csv).
Accuracy. Filled-in values compared with ground_truth.csv: average error, how much of the true spread each method keeps, and how often the filled-in gender and smoker status are right (imputation_accuracy.csv).
Results
<!-- Fill these in after rerunning all three scripts. The file each number comes from is in brackets. -->

Cleaning. Of 25,000 policies, ___ passed cleaning [cleaning_log.csv]. The biggest single cut was ___, which removed ___.

Distributions. <!-- Look at imputation_plot.png and spread_ratio in imputation_accuracy.csv (1.0 = same spread as the truth). Expect mean/mode to show a spike at the average face amount with almost no spread. Check whether regression narrows the spread and whether stochastic keeps it. --> ___

Accuracy of filled-in values. <!-- imputation_accuracy.csv: mean_error shows bias, mean_absolute_error shows how far off a typical value is. Compare gender_correct and smoker_correct for mode (methods 2 and 3) against random draws (method 4). --> ___

Mortality multipliers. <!-- glm_multipliers.csv. Check which method's smoker and male multipliers land closest to 2.1 and 1.25, and whether the dashed line falls inside each interval. Methods 2 to 4 all label some true smokers as non-smokers, which should pull the smoker multiplier toward 1. --> ___

What I'd recommend. <!-- Because the data is missing completely at random, complete-case should be unbiased, at the cost of fewer policies and wider intervals. Say whether the results bear that out. --> ___

## What I'd do differently with real data
Find out why values are missing before choosing a method. Here they are missing completely at random, so dropping incomplete records is unbiased. If larger policies were more likely to be missing, dropping them or filling in the average would understate face amounts, and only a method that uses related fields, like premium, could recover them.
Use multiple imputation instead of one random draw. Filling in the gaps several times and combining the results shows how uncertain the imputed values are. R's mice package with predictive mean matching would be the next step.
Fix errors at the source. If a large share of records fails the same check, that is a system problem to raise with IT, not just something to delete. Some errors can be repaired, for example rebuilding an age from date of birth.
Study face-amount-weighted mortality too. Life insurers usually weight deaths by face amount, and that is where how you fill in face amounts really matters.






# Stochastic Loss Reserving in R

A reserve estimate depends on the method you use and the judgments that go into it. This project applies the standard reserving methods to one loss triangle and compares the estimates, how uncertain they are, and which assumptions move them the most.

**Data:** `GenIns`, the 10 x 10 cumulative general insurance claims triangle from Taylor & Ashe (1983), included in the `ChainLadder` package. Because it is a published benchmark, the results can be checked: the chain-ladder reserve and Mack standard error here match the published figures.

Everything is in `LossReserving.R`. It prints the results, writes the summary tables to CSV, and saves the charts to `LossReservingGraphs/`.

## Methods

| Method | What it does |
|---|---|
| Chain-ladder          | Projects each accident year to ultimate with volume-weighted age-to-age factors |

| Mack                  | The same estimate as chain-ladder, plus a standard error from process risk and from the uncertainty in the estimated factors |

| Bootstrap             | 5,000 resampled versions of the triangle (over-dispersed Poisson with gamma process error), giving a full distribution of the reserve |

| Bornhuetter-Ferguson  | Claims to date plus an expected amount for the part not yet reported, so less developed years lean on the expectation rather than their own data |

GenIns has no premium, so BF needs its expected losses from somewhere. I estimated them with the **Cape Cod** method: total claims to date divided by the total share reported, assuming the same exposure every year. Each year counts in proportion to how developed it is, so the expectation rests mostly on the mature years. With premium data, the same calculation would give an expected loss ratio.

## Checks on the assumptions

- **Calendar-year effects.** Chain-ladder assumes claims develop the same way at each age regardless of calendar year. I tested that by fitting log incremental claims on accident year and development year, then checking whether adding calendar year improved the fit.
- **Tail factor.** Reserves re-estimated with tail factors of 1.00, 1.02, 1.05 and 1.10 for development after year 10.
- **BF a priori.** BF re-run with the Cape Cod expectation 10% lower and 10% higher.

## Results

| | Reserve |
|---|---|
| Chain-ladder best estimate            | 18.68M |
| Mack standard error                   | 2.45M (CV 13.1%) |
| Bootstrap 90th percentile             | 22.81M |
| BF (Cape Cod a priori of 5.18M per year) | 17.47M |
| BF with the a priori 10% lower/higher | 15.72M / 19.22M |
| Tail factor 1.02/1.05/1.10            | 19.74M / 21.33M / 23.98M |

![What moves the reserve](LossReservingGraphs/6_what_moves_the_reserve.png)

**The tail factor matters more than the choice of method.** Allowing 10% more development after year 10 raises the reserve by 5.3 million, or 28%. That is far more than 10% because the tail applies to the whole ultimate, while claims already paid stay fixed, so the entire increase lands on the reserve. It is more than four times the gap between chain-ladder and BF. The tail is also the assumption with the least data behind it, since the triangle ends at year 10.

**The uncertainty is mostly in the recent years.** Mack puts one standard error at 13% of the reserve. In dollars, most of it comes from the most recent accident years, which have the largest reserves because they have the most development still to come. In percentage terms, the highest CVs are actually in old years with tiny reserves: accident year 2's reserve is under 100 thousand, so a small amount of uncertainty is a large share of it. The bootstrap gives a 90th percentile 4.1 million above the best estimate.

**BF comes in 6.5% below chain-ladder.** The difference is almost all in the least developed years. Chain-ladder multiplies their small amount of data by large factors (accident year 10 has a factor of about 14 to ultimate), while BF replaces most of that projection with the Cape Cod expectation. Moving that expectation 10% either way shifts BF by about 1.75 million, so for BF the a priori is the key assumption.

**No significant calendar-year effect** (F test p ≈ 0.39). Once development year is in the model, adding calendar year doesn't improve the fit, so the data gives no strong evidence against chain-ladder's assumption. My first version of this test left development year out and found a highly significant effect, but that was calendar year standing in for normal development, not a real diagonal pattern.

![Bootstrap distribution](LossReservingGraphs/5_bootstrap_distribution.png)

## Other charts

- `1_claims_development.png`: cumulative claims by accident year, actual and projected
- `2_development_factors.png`: each year's age-to-age factors against the selected factors, which is the variation Mack turns into a standard error
- `3_reserve_by_year_mack.png`: reserve by accident year with one standard error either side
- `4_chain_ladder_vs_bf.png`: chain-ladder and BF reserves by accident year

## Limitations

- **The tail factors are chosen scenarios, not fitted.** A fitted tail, for example from an exponential decay or inverse power curve through the later factors, would be the next step.
- **The BF a priori comes from the same triangle.** Cape Cod is a consistent way to set it without premium, but a real BF would use an independent expectation from pricing, plans or industry data.
- **Flat exposure.** Cape Cod assumes every accident year had the same volume of business. Real premium or policy counts would fix that.
- **Mack assumes** that development is proportional to claims to date, that the variance is proportional too, and that accident years are independent.
- **One triangle, one line of business,** with no inflation adjustment, reinsurance, discounting or risk margin.