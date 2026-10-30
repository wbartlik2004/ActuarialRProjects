library(tidyverse)
library(lubridate)

raw_df <- read_csv("CleaningLifeData/enterprise_policy_extract.csv")

# 1. CLEANING PIPELINE
cleaned_df <- raw_df %>%
  mutate(
    Gender_Clean = case_when(
      Gender %in% c("M", "Male") ~ "Male",
      Gender %in% c("F", "Female") ~ "Female",
      TRUE ~ NA_character_ # Convert text unknowns to explicit NA for proper imputation testing
    ),
    Smoker_Clean = case_when(
      SmokerStatus %in% c("S", "Smoker") ~ "Smoker",
      SmokerStatus %in% c("NS", "Non-Smoker", "Non-smoker") ~ "Non-Smoker",
      TRUE ~ NA_character_
    ),
    Status_Clean = case_when(
      PolicyStatusRaw == "Active" ~ "Active",
      PolicyStatusRaw == "Surrendered" ~ "Surrender",
      PolicyStatusRaw == "Deceased" ~ "Death",
      PolicyStatusRaw %in% c("Lapsed", "EXPIRED") ~ "Lapse",
      TRUE ~ "Unknown/Other"
    )
  ) %>%
  # Domain Boundary Checks & Temporal Logic Audit
  filter(
    IssueAge >= 18 & IssueAge <= 90,
    AnnualPremium > 0,                     # Removes negative financial glitches
    !is.na(IssueDate), !is.na(TerminationDate),
    TerminationDate >= IssueDate
  ) %>%
  mutate(
    EffectiveDate = pmax(EffectiveDate, IssueDate, na.rm = TRUE)
  )

# 2. IMPLEMENTING 4 IMPUTATION METHODS

# Method 1: Complete-Case Analysis (Drop all rows with any NAs)
df_method1_complete <- cleaned_df %>%
  drop_na(FaceAmount, AnnualPremium, Gender_Clean, Smoker_Clean)

# Method 2: Single Imputation (Mean/Mode Replacement)
mean_face <- mean(cleaned_df$FaceAmount, na.rm = TRUE)
mean_prem <- mean(cleaned_df$AnnualPremium, na.rm = TRUE)
mode_gender <- "Male" # Most frequent category
mode_smoker <- "Non-Smoker"

df_method2_single <- cleaned_df %>%
  mutate(
    FaceAmount = ifelse(is.na(FaceAmount), mean_face, FaceAmount),
    AnnualPremium = ifelse(is.na(AnnualPremium), mean_prem, AnnualPremium),
    Gender_Clean = replace_na(Gender_Clean, mode_gender),
    Smoker_Clean = replace_na(Smoker_Clean, mode_smoker)
  )

# Method 3: Deterministic Regression Imputation
# A predictive linear model for FaceAmount based on premium and age using complete cases
fit_face <- lm(FaceAmount ~ AnnualPremium + IssueAge, data = cleaned_df)

df_method3_regression <- cleaned_df %>%
  mutate(
    # Predict missing FaceAmounts using the regression model
    pred_face = predict(fit_face, newdata = .),
    FaceAmount = ifelse(is.na(FaceAmount), pmax(pred_face, 10000), FaceAmount),
    AnnualPremium = ifelse(is.na(AnnualPremium), mean_prem, AnnualPremium),
    Gender_Clean = replace_na(Gender_Clean, mode_gender),
    Smoker_Clean = replace_na(Smoker_Clean, mode_smoker)
  ) %>%
  select(-pred_face)

# Method 4: Stochastic Imputation (Regression + Residual Error Noise)
set.seed(2026)
residual_sd <- summary(fit_face)$sigma

df_method4_stochastic <- cleaned_df %>%
  mutate(
    pred_face = predict(fit_face, newdata = .),
    # Add random normal error term to preserve data variance / spread
    stochastic_noise = rnorm(n(), mean = 0, sd = residual_sd),
    imputed_face = pred_face + stochastic_noise,
    FaceAmount = ifelse(is.na(FaceAmount),
                        pmax(imputed_face, 10000),
                        FaceAmount),
    AnnualPremium = ifelse(is.na(AnnualPremium), mean_prem, AnnualPremium),
    Gender_Clean = replace_na(Gender_Clean, mode_gender),
    Smoker_Clean = replace_na(Smoker_Clean, mode_smoker)
  ) %>%
  select(-pred_face, -stochastic_noise, -imputed_face)

# 3. CALCULATE EXPOSURE WINDOW & EXPORT TABLES
study_start <- as.Date("2023-01-01")
study_end <- as.Date("2023-12-31")

process_exposure <- function(df) {
  df %>% # nolint
    mutate(
      exposure_start_date = pmax(IssueDate, study_start),
      exposure_end_date = pmin(TerminationDate, study_end),
      DaysExposed = as.numeric(exposure_end_date - exposure_start_date),
      Exposure = ifelse(DaysExposed > 0, DaysExposed / 365.25, 0)
    ) %>%
    filter(Exposure > 0)
}

# Produce the 4 final analytical tables
table_complete <- process_exposure(df_method1_complete)
table_single   <- process_exposure(df_method2_single)
table_reg      <- process_exposure(df_method3_regression)
table_stoch    <- process_exposure(df_method4_stochastic)

# Export to individual CSV files for your portfolio records
write_csv(table_complete, "CleaningLifeData/1DropNA.csv")
write_csv(table_single,   "CleaningLifeData/2MeanModeReplacement.csv")
write_csv(table_reg,      "CleaningLifeData/3DeterministicRegression.csv")
write_csv(table_stoch,    "CleaningLifeData/4StochasticImputation.csv")

print("All 4 imputation methodology tables generated and exported successfully")