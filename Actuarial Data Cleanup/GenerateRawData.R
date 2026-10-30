library(tidyverse)

# Creates a messy life insurance policy extract (enterprise_policy_extract.csv) and a
# ground_truth.csv with the values before any errors or gaps were added, so the cleaning
# and imputation can be checked against the truth.
#
# Run from the folder that contains CleaningLifeData.

set.seed(2026)
n <- 25000

# ---------------- settings ----------------
DATA_DIR        <- "Actuarial Data Cleanup/CleaningLifeData"
EXTRACT_DATE    <- as.Date("2025-12-31")   # the day the extract was pulled
WITHDRAWAL_RATE <- 0.10                    # annual chance of lapse or surrender
SURRENDER_SHARE <- 0.55                    # share of withdrawals that are surrenders
# ------------------------------------------

dir.create(DATA_DIR, showWarnings = FALSE)

# 1. True policy characteristics (what the admin system should have recorded)
issue_ages   <- sample(18:85, n, replace = TRUE)
true_gender  <- sample(c("Male", "Female"), n, replace = TRUE)
true_smoker  <- sample(c("Smoker", "Non-Smoker"), n, replace = TRUE, prob = c(0.2, 0.8))
issue_dates  <- sample(seq(as.Date("2010-01-01"), as.Date("2023-12-31"), by = "day"),
                       n, replace = TRUE)
face_amounts <- runif(n, 50000, 2000000)

# 2. Mortality: Gompertz-Makeham by issue age, times gender and smoker multipliers
makeham_a  <- 0.0007
gompertz_b <- 0.00005
gompertz_c <- 1.085

gender_mult   <- ifelse(true_gender == "Male", 1.25, 1.0)
smoker_mult   <- ifelse(true_smoker == "Smoker", 2.1, 1.0)
base_q_x      <- makeham_a + gompertz_b * (gompertz_c^issue_ages)
simulated_q_x <- pmin(base_q_x * gender_mult * smoker_mult, 0.95)

# Premium = cost of insurance plus a 30% loading, with some policy-level variation.
# This ties premium to face amount, age, gender and smoker status, so regression
# imputation has something real to predict from.
annual_premiums <- face_amounts * simulated_q_x * 1.3 * exp(rnorm(n, 0, 0.15))

# 3. Simulate each policy year by year: the policy year it would die in and the policy
#    year it would lapse or surrender in, whichever comes first. Anything past the
#    extract date hasn't happened yet, so that policy is still Active.
years_to_death    <- rgeom(n, simulated_q_x) + 1
years_to_withdraw <- rgeom(n, WITHDRAWAL_RATE) + 1
exit_year         <- pmin(years_to_death, years_to_withdraw)
exit_date         <- issue_dates + round((exit_year - 1 + runif(n)) * 365.25)

policy_status <- case_when(
  exit_date > EXTRACT_DATE            ~ "Active",
  years_to_death <= years_to_withdraw ~ "Deceased",
  runif(n) < SURRENDER_SHARE          ~ "Surrendered",
  TRUE                                ~ "Lapsed"
)
# Active policies have no termination date; terminated ones end on the event date
term_dates <- if_else(policy_status == "Active", as.Date(NA), exit_date)

# 4. Recorded values: the truth written in inconsistent formats, with some left unknown
genders <- if_else(true_gender == "Male",
                   sample(c("M", "Male"), n, replace = TRUE, prob = c(0.8, 0.2)),
                   sample(c("F", "Female"), n, replace = TRUE, prob = c(0.8, 0.2)))
gender_mask <- runif(n) < 0.14
genders[gender_mask] <- sample(c("U", "", NA), sum(gender_mask), replace = TRUE)

smoker_raw <- if_else(true_smoker == "Smoker",
                      sample(c("S", "Smoker"), n, replace = TRUE, prob = c(0.7, 0.3)),
                      sample(c("NS", "Non-Smoker"), n, replace = TRUE, prob = c(0.75, 0.25)))
smoker_mask <- runif(n) < 0.20
smoker_raw[smoker_mask] <- sample(c("Unknown", "N/A", NA), sum(smoker_mask), replace = TRUE)

# Status codes corrupted by the admin system (these are errors, not real statuses)
status_noise <- sample(c("99", "ERR", "NULL", "EXPIRED"), n, replace = TRUE,
                       prob = c(0.4, 0.2, 0.2, 0.2))
inject_mask <- runif(n) < 0.15
policy_status[inject_mask] <- status_noise[inject_mask]

# 5. Dataset
raw_enterprise_data <- data.frame(
  PolicyID        = paste0("POL-", sample(100000:999999, n, replace = FALSE)),  # unique IDs
  IssueDate       = issue_dates,
  EffectiveDate   = as.Date(NA),
  TerminationDate = term_dates,
  IssueAge        = issue_ages,
  Gender          = genders,
  SmokerStatus    = smoker_raw,
  FaceAmount      = face_amounts,
  AnnualPremium   = annual_premiums,
  PolicyStatusRaw = policy_status
)

# Effective date a few days after issue (the + has to end the first line, or R treats
# the second line as a separate statement and the lag is never added)
raw_enterprise_data$EffectiveDate <- raw_enterprise_data$IssueDate +
  sample(0:15, n, replace = TRUE)

# Save the true values before any errors or gaps are added
ground_truth <- tibble(
  PolicyID          = raw_enterprise_data$PolicyID,
  TrueGender        = true_gender,
  TrueSmoker        = true_smoker,
  TrueFaceAmount    = face_amounts,
  TrueAnnualPremium = annual_premiums
)
write_csv(ground_truth, file.path(DATA_DIR, "ground_truth.csv"))

# --- INJECT REALISTIC SYSTEM GLITCHES & ERRORS ---
# 1. Temporal violations (termination date before issue date)
bad_dates_idx <- sample(1:n, 2500)
raw_enterprise_data$TerminationDate[bad_dates_idx] <-
  raw_enterprise_data$IssueDate[bad_dates_idx] - sample(1:400, 2500, replace = TRUE)

# 2. Corrupt or impossible ages
raw_enterprise_data$IssueAge[sample(1:n, 1000)] <- -99
raw_enterprise_data$IssueAge[sample(1:n, 500)]  <- 130

# 3. Financial glitches (negative premiums)
raw_enterprise_data$AnnualPremium[sample(1:n, 1250)] <- -1500.50

# 4. Missing financials (removed completely at random)
raw_enterprise_data$FaceAmount[sample(1:n, 2000)]    <- NA
raw_enterprise_data$AnnualPremium[sample(1:n, 1350)] <- NA

# 5. Missing dates (system sync gaps)
raw_enterprise_data$IssueDate[sample(1:n, 800)]        <- as.Date(NA)
raw_enterprise_data$EffectiveDate[sample(1:n, 1000)]   <- as.Date(NA)
raw_enterprise_data$TerminationDate[sample(1:n, 900)]  <- as.Date(NA)

write_csv(raw_enterprise_data, file.path(DATA_DIR, "enterprise_policy_extract.csv"))
cat("Wrote enterprise_policy_extract.csv and ground_truth.csv to", DATA_DIR, "\n")
print(table(policy_status))