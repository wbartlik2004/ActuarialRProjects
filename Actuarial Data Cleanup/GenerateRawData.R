library(tidyverse)

set.seed(2026)
n <- 25000

# 1. Base Policy Columns
issue_ages <- sample(18:85, n, replace = TRUE)
genders <- sample(c("M", "F", "Male", "Female", "U", "", NA), n,
                  replace = TRUE,
                  prob = c(0.35, 0.35, 0.08, 0.08, 0.04, 0.03, 0.07))
smoker_raw <- sample(c("S", "NS", "Smoker", "Non-Smoker", "Unknown", "N/A", NA),
                     n,
                     replace = TRUE,
                     prob = c(0.12, 0.48, 0.05, 0.15, 0.08, 0.04, 0.08))

issue_dates <- sample(seq(as.Date("2010/01/01"), as.Date("2023/12/31"),
                         by = "day"), n, replace = TRUE)
term_dates <- sample(seq(as.Date("2012/01/01"), as.Date("2025/12/31"),
                         by = "day"), n, replace = TRUE)

# 2. Formulaic Actuarial Mortality Model (Gompertz-Makeham Baseline)
makeham_a <- 0.0007
gompertz_b <- 0.00005
gompertz_c <- 1.085

gender_mult <- ifelse(genders %in% c("M", "Male"), 1.25, 1.0)
smoker_mult <- ifelse(smoker_raw %in% c("S", "Smoker"), 2.1, 1.0)

base_q_x <- makeham_a + gompertz_b * (gompertz_c^issue_ages)
simulated_q_x <- pmin(base_q_x * gender_mult * smoker_mult, 0.95)

event_draw <- runif(n)
policy_status <- case_when(
  event_draw < simulated_q_x ~ "Deceased",
  event_draw < simulated_q_x + 0.12 ~ "Surrendered",
  event_draw < simulated_q_x + 0.22 ~ "Lapsed",
  TRUE ~ "Active"
)

status_noise <- sample(c("99", "ERR", "NULL", "EXPIRED"),
                       n,
                       replace = TRUE,
                       prob = c(0.4, 0.2, 0.2, 0.2))
inject_mask <- runif(n) < 0.15
policy_status[inject_mask] <- status_noise[inject_mask]

# 3. Dataset
raw_enterprise_data <- data.frame(
  PolicyID = paste0("POL-", sample(100000:999999, n, replace = TRUE)),
  IssueDate = issue_dates,
  EffectiveDate = as.Date(NA),
  TerminationDate = term_dates,
  IssueAge = issue_ages,
  Gender = genders,
  SmokerStatus = smoker_raw,
  FaceAmount = runif(n, 50000, 2000000),
  AnnualPremium = runif(n, 400, 5000),
  PolicyStatusRaw = policy_status
)

# Populate EffectiveDate close to IssueDate with random lag
raw_enterprise_data$EffectiveDate <- raw_enterprise_data$IssueDate
+ sample(0:15, n, replace = TRUE)

# --- INJECT REALISTIC SYSTEM GLITCHES & ERRORS ---
# 1. Temporal Violations (Termination date occurs before Issue date)
bad_dates_idx <- sample(1:n, 2500)
raw_enterprise_data$TerminationDate[bad_dates_idx] <- raw_enterprise_data$IssueDate[bad_dates_idx] - sample(1:400, 2500, replace = TRUE)

# 2. Corrupt/Impossible Ages
raw_enterprise_data$IssueAge[sample(1:n, 1000)] <- -99
raw_enterprise_data$IssueAge[sample(1:n, 500)] <- 130

# 3. Financial Glitches (Negative premiums)
raw_enterprise_data$AnnualPremium[sample(1:n, 1250)] <- -1500.50

# 4. Missing Financials & Demographics
raw_enterprise_data$FaceAmount[sample(1:n, 2000)] <- NA
raw_enterprise_data$AnnualPremium[sample(1:n, 1350)] <- NA

# 5. Missing Dates (System sync gaps / unrecorded milestones)
raw_enterprise_data$IssueDate[sample(1:n, 800)] <- as.Date(NA)
raw_enterprise_data$EffectiveDate[sample(1:n, 1000)] <- as.Date(NA)
raw_enterprise_data$TerminationDate[sample(1:n, 900)] <- as.Date(NA)

# Export to CSV
write_csv(raw_enterprise_data, "enterprise_policy_extract.csv")
print("Dataset with missing dates generated as 'enterprise_policy_extract.csv'")
