library(tidyverse)

# Cleans the raw extract, records how many policies each rule removes, checks the result,
# fills in missing values four different ways, and builds an exposure table for each.
#
# Run from the folder that contains CleaningLifeData, after GenerateRawData.R.

# ---------------- settings ----------------
DATA_DIR    <- "Actuarial Data Cleanup/CleaningLifeData"
STUDY_START <- as.Date("2019-01-01")
STUDY_END   <- as.Date("2023-12-31")
MIN_AGE     <- 18
MAX_AGE     <- 90
# ------------------------------------------

raw_df <- read_csv(file.path(DATA_DIR, "enterprise_policy_extract.csv"),
                   col_types = cols(.default = col_guess(),
                                    Gender = col_character(),
                                    SmokerStatus = col_character(),
                                    PolicyStatusRaw = col_character()))

# 1. STANDARDIZE CODES
standardized_df <- raw_df %>%
  mutate(
    Gender_Clean = case_when(
      Gender %in% c("M", "Male")   ~ "Male",
      Gender %in% c("F", "Female") ~ "Female",
      TRUE ~ NA_character_            # "U", blanks and NA become explicit missing values
    ),
    Smoker_Clean = case_when(
      SmokerStatus %in% c("S", "Smoker")                     ~ "Smoker",
      SmokerStatus %in% c("NS", "Non-Smoker", "Non-smoker")  ~ "Non-Smoker",
      TRUE ~ NA_character_            # "Unknown", "N/A" and NA
    ),
    Status_Clean = case_when(
      PolicyStatusRaw == "Active"      ~ "Active",
      PolicyStatusRaw == "Surrendered" ~ "Surrender",
      PolicyStatusRaw == "Deceased"    ~ "Death",
      PolicyStatusRaw == "Lapsed"      ~ "Lapse",
      TRUE ~ "Unknown/Other"          # 99, ERR, NULL and EXPIRED are system error codes
    )
  )

# 2. CLEANING RULES, one at a time so every removed policy is accounted for
step1 <- standardized_df %>% distinct(PolicyID, .keep_all = TRUE)
step2 <- step1 %>% filter(between(IssueAge, MIN_AGE, MAX_AGE))
step3 <- step2 %>% filter(is.na(AnnualPremium) | AnnualPremium > 0)   # keep missing premiums for imputation
step4 <- step3 %>% filter(!is.na(IssueDate))
step5 <- step4 %>% filter(Status_Clean != "Unknown/Other")
step6 <- step5 %>% filter(Status_Clean == "Active" | !is.na(TerminationDate))   # an event needs a date
step7 <- step6 %>% filter(is.na(TerminationDate) | TerminationDate >= IssueDate)
step8 <- step7 %>% filter(!(Status_Clean == "Active" & !is.na(TerminationDate))) # status and date must agree

cleaning_log <- tibble(
  step = c("Raw extract",
           "Remove duplicate policy IDs",
           paste0("Issue age between ", MIN_AGE, " and ", MAX_AGE),
           "Premium positive or missing",
           "Issue date present",
           "Status is a valid code",
           "Terminated policies have a termination date",
           "Termination on or after issue",
           "Active policies have no termination date"),
  policies_left = c(nrow(raw_df), nrow(step1), nrow(step2), nrow(step3), nrow(step4),
                    nrow(step5), nrow(step6), nrow(step7), nrow(step8))
) %>%
  mutate(removed = lag(policies_left) - policies_left)

cleaned_df <- step8 %>%
  mutate(
    EffectiveDate = pmax(EffectiveDate, IssueDate, na.rm = TRUE),
    # flags so the imputed values can be checked against the truth later
    Face_Missing   = is.na(FaceAmount),
    Prem_Missing   = is.na(AnnualPremium),
    Gender_Missing = is.na(Gender_Clean),
    Smoker_Missing = is.na(Smoker_Clean)
  )

# 3. VALIDATION CHECKS: stop if any rule is broken after cleaning
stopifnot(
  !anyDuplicated(cleaned_df$PolicyID),
  all(between(cleaned_df$IssueAge, MIN_AGE, MAX_AGE)),
  all(is.na(cleaned_df$AnnualPremium) | cleaned_df$AnnualPremium > 0),
  all(!is.na(cleaned_df$IssueDate)),
  all(is.na(cleaned_df$TerminationDate) | cleaned_df$TerminationDate >= cleaned_df$IssueDate),
  all((cleaned_df$Status_Clean == "Active") == is.na(cleaned_df$TerminationDate)),
  all(cleaned_df$Gender_Clean %in% c("Male", "Female", NA)),
  all(cleaned_df$Smoker_Clean %in% c("Smoker", "Non-Smoker", NA))
)

# 4. VALUES USED TO FILL GAPS, all computed from the cleaned data
mean_face <- mean(cleaned_df$FaceAmount, na.rm = TRUE)
mean_prem <- mean(cleaned_df$AnnualPremium, na.rm = TRUE)

# Most common non-missing gender
mode_gender <- cleaned_df %>%
  filter(!is.na(Gender_Clean)) %>%
  count(Gender_Clean) %>%
  slice_max(n, n = 1, with_ties = FALSE) %>%
  pull(Gender_Clean)

# Most common non-missing smoker status
mode_smoker <- cleaned_df %>%
  filter(!is.na(Smoker_Clean)) %>%
  count(Smoker_Clean) %>%
  slice_max(n, n = 1, with_ties = FALSE) %>%
  pull(Smoker_Clean)

# Shares used for random draws in Method 4
share_male   <- mean(cleaned_df$Gender_Clean == "Male", na.rm = TRUE)
share_smoker <- mean(cleaned_df$Smoker_Clean == "Smoker", na.rm = TRUE)

# Regressions on the log scale: face amounts and premiums are positive and skewed, and
# premium is roughly proportional to face amount, so log(face) ~ log(premium) is close
# to a straight line. lm() leaves out rows with a missing value automatically.
fit_face <- lm(log(FaceAmount) ~ log(AnnualPremium) + IssueAge, data = cleaned_df)
fit_prem <- lm(log(AnnualPremium) ~ log(FaceAmount) + IssueAge, data = cleaned_df)
sd_face  <- summary(fit_face)$sigma
sd_prem  <- summary(fit_prem)$sigma

cat("Mode used for gender:", mode_gender, "| smoker:", mode_smoker, "\n")
cat("R-squared, face amount model:", round(summary(fit_face)$r.squared, 3),
    "| premium model:", round(summary(fit_prem)$r.squared, 3), "\n")

# 5. FOUR WAYS OF HANDLING MISSING VALUES

# Method 1: Complete-case analysis (drop rows with any missing value)
df_method1_complete <- cleaned_df %>%
  drop_na(FaceAmount, AnnualPremium, Gender_Clean, Smoker_Clean)

# Method 2: Single imputation (mean for numbers, mode for categories)
df_method2_single <- cleaned_df %>%
  mutate(
    FaceAmount    = coalesce(FaceAmount, mean_face),
    AnnualPremium = coalesce(AnnualPremium, mean_prem),
    Gender_Clean  = replace_na(Gender_Clean, mode_gender),
    Smoker_Clean  = replace_na(Smoker_Clean, mode_smoker)
  )

# Method 3: Deterministic regression imputation
# Face amount first (from premium), then premium (from the filled-in face amount).
# exp(prediction + sd^2 / 2) is the average on the original scale, not the median.
# A policy missing both falls back to the mean face amount.
df_method3_regression <- cleaned_df %>%
  mutate(
    face_pred  = exp(predict(fit_face, newdata = .) + sd_face^2 / 2),
    FaceAmount = coalesce(FaceAmount, face_pred, mean_face)
  ) %>%
  mutate(
    prem_pred     = exp(predict(fit_prem, newdata = .) + sd_prem^2 / 2),
    AnnualPremium = coalesce(AnnualPremium, prem_pred),
    Gender_Clean  = replace_na(Gender_Clean, mode_gender),
    Smoker_Clean  = replace_na(Smoker_Clean, mode_smoker)
  ) %>%
  select(-face_pred, -prem_pred)

# Method 4: Stochastic imputation
# Regression prediction plus random error the size of the model's typical miss. On the
# log scale the result is always positive, so no floor is needed. A policy missing both
# face and premium gets a randomly chosen observed face amount. Gender and smoker status
# are drawn at random in proportion to the known mix, rather than all set to the mode.
set.seed(2026)
observed_faces <- cleaned_df$FaceAmount[!is.na(cleaned_df$FaceAmount)]

df_method4_stochastic <- cleaned_df %>%
  mutate(
    face_draw  = exp(predict(fit_face, newdata = .) + rnorm(n(), 0, sd_face)),
    face_donor = sample(observed_faces, n(), replace = TRUE),
    FaceAmount = coalesce(FaceAmount, face_draw, face_donor)
  ) %>%
  mutate(
    prem_draw     = exp(predict(fit_prem, newdata = .) + rnorm(n(), 0, sd_prem)),
    AnnualPremium = coalesce(AnnualPremium, prem_draw),
    Gender_Clean  = if_else(is.na(Gender_Clean),
                            if_else(runif(n()) < share_male, "Male", "Female"),
                            Gender_Clean),
    Smoker_Clean  = if_else(is.na(Smoker_Clean),
                            if_else(runif(n()) < share_smoker, "Smoker", "Non-Smoker"),
                            Smoker_Clean)
  ) %>%
  select(-face_draw, -face_donor, -prem_draw)

# 6. EXPOSURE FOR THE STUDY WINDOW
# Active policies are exposed to the end of the study. Terminated policies are exposed to
# their termination date, and the termination counts as an event only if it falls inside
# the study window. Exposure is in years; +1 counts both the first and last day.
process_exposure <- function(df) {
  df %>%
    mutate(
      exposure_start_date = pmax(IssueDate, STUDY_START),
      exposure_end_date   = if_else(is.na(TerminationDate), STUDY_END,
                                    pmin(TerminationDate, STUDY_END)),
      DaysExposed = as.numeric(exposure_end_date - exposure_start_date) + 1,
      Exposure    = DaysExposed / 365.25,
      Event_Type  = case_when(
        !is.na(TerminationDate) & TerminationDate >= STUDY_START &
          TerminationDate <= STUDY_END ~ Status_Clean,
        TRUE ~ "None"
      )
    ) %>%
    filter(DaysExposed > 0)
}

table_complete <- process_exposure(df_method1_complete)
table_single   <- process_exposure(df_method2_single)
table_reg      <- process_exposure(df_method3_regression)
table_stoch    <- process_exposure(df_method4_stochastic)

# 7. EXPORT
write_csv(cleaning_log,   file.path(DATA_DIR, "cleaning_log.csv"))
write_csv(table_complete, file.path(DATA_DIR, "1DropNA.csv"))
write_csv(table_single,   file.path(DATA_DIR, "2MeanModeReplacement.csv"))
write_csv(table_reg,      file.path(DATA_DIR, "3DeterministicRegression.csv"))
write_csv(table_stoch,    file.path(DATA_DIR, "4StochasticImputation.csv"))

print(cleaning_log)

study_summary <- bind_rows(
  table_complete %>% mutate(Method = "1. Complete-case"),
  table_single   %>% mutate(Method = "2. Mean/mode"),
  table_reg      %>% mutate(Method = "3. Regression"),
  table_stoch    %>% mutate(Method = "4. Stochastic")
) %>%
  group_by(Method) %>%
  summarise(policies = n(),
            exposure_years = sum(Exposure),
            deaths = sum(Event_Type == "Death"),
            lapses_and_surrenders = sum(Event_Type %in% c("Lapse", "Surrender")),
            .groups = "drop") %>%
  mutate(deaths_per_1000 = 1000 * deaths / exposure_years)
print(study_summary)
cat("All 4 imputation tables written to", DATA_DIR, "\n")