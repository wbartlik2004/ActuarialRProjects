library(tidyverse)
library(scales)

# Compares the four imputation methods three ways:
#   1. how each one reshapes the face amount distribution (density plot)
#   2. whether a mortality GLM fitted to each one recovers the true gender and smoker
#      multipliers used to simulate the data
#   3. how close the filled-in values are to the true values in ground_truth.csv
#
# Run from the folder that contains CleaningLifeData, after CleaningRawData.R.

# ---------------- settings ----------------
DATA_DIR <- "Actuarial Data Cleanup/CleaningLifeData"
TRUE_MULTIPLIERS <- tibble(
  term = c("Gender_CleanMale", "Smoker_CleanSmoker"),
  label = c("Male vs female", "Smoker vs non-smoker"),
  true_multiplier = c(1.25, 2.1)
)
# ------------------------------------------

methods <- c(
  "1DropNA.csv"                  = "1. Complete-Case (Listwise Deletion)",
  "2MeanModeReplacement.csv"     = "2. Single Imputation (Mean/Mode)",
  "3DeterministicRegression.csv" = "3. Regression Imputation",
  "4StochasticImputation.csv"    = "4. Stochastic Imputation"
)

comparison_df <- bind_rows(lapply(names(methods), function(f) {
  read_csv(file.path(DATA_DIR, f), show_col_types = FALSE) %>% mutate(Method = methods[[f]])
})) %>%
  mutate(Gender_Clean = factor(Gender_Clean, levels = c("Female", "Male")),
         Smoker_Clean = factor(Smoker_Clean, levels = c("Non-Smoker", "Smoker")),
         Death = as.integer(Event_Type == "Death"))

truth <- read_csv(file.path(DATA_DIR, "ground_truth.csv"), show_col_types = FALSE)

# 1. DENSITY OF FACE AMOUNTS BY METHOD
imputation_plot <- ggplot(comparison_df, aes(x = FaceAmount, fill = Method)) +
  geom_density(alpha = 0.5) +
  facet_wrap(~ Method, scales = "free_y") +
  scale_x_continuous(labels = dollar) +
  labs(title = "Comparison of Missing Data Imputation Methods",
       subtitle = "Impact on Portfolio Face Amount Distributions",
       x = "Policy Face Amount ($)", y = "Density") +
  theme_minimal() +
  theme(legend.position = "none")
ggsave(file.path(DATA_DIR, "imputation_plot.png"), plot = imputation_plot,
       width = 8, height = 8, dpi = 300)

# 2. MORTALITY GLM FOR EACH METHOD
# Poisson model of deaths with a log link and log(exposure) as an offset, so each
# coefficient exponentiates to a mortality multiplier.
glm_results <- tibble()
for (m in unname(methods)) {
  df  <- comparison_df %>% filter(Method == m)
  fit <- glm(Death ~ IssueAge + Gender_Clean + Smoker_Clean,
             family = poisson(link = "log"), offset = log(Exposure), data = df)
  est <- coef(summary(fit))
  glm_results <- bind_rows(glm_results, tibble(
    Method = m,
    term = rownames(est),
    estimate = est[, "Estimate"],
    std_error = est[, "Std. Error"],
    deaths = sum(df$Death)
  ))
}
glm_results <- glm_results %>%
  mutate(multiplier = exp(estimate),
         lower_95 = exp(estimate - 1.96 * std_error),
         upper_95 = exp(estimate + 1.96 * std_error))
write_csv(glm_results, file.path(DATA_DIR, "glm_multipliers.csv"))

multiplier_compare <- glm_results %>%
  inner_join(TRUE_MULTIPLIERS, by = "term")
print(multiplier_compare %>%
        select(Method, label, true_multiplier, multiplier, lower_95, upper_95, deaths) %>%
        mutate(across(where(is.numeric), ~ round(.x, 3))))

glm_plot <- ggplot(multiplier_compare,
                   aes(x = Method, y = multiplier, ymin = lower_95, ymax = upper_95)) +
  geom_hline(aes(yintercept = true_multiplier), linetype = "dashed") +
  geom_pointrange(colour = "#2b6cb0") +
  facet_wrap(~ label, scales = "free_x") +
  coord_flip() +
  labs(title = "Mortality multipliers recovered by each imputation method",
       subtitle = "Poisson GLM with 95% intervals; dashed line = value used to simulate the data",
       x = NULL, y = "Mortality multiplier") +
  theme_minimal()
ggsave(file.path(DATA_DIR, "glm_multipliers.png"), plot = glm_plot,
       width = 9, height = 4.5, dpi = 300)

# 3. HOW CLOSE ARE THE IMPUTED VALUES TO THE TRUTH? (methods 2 to 4 fill in values)
checked <- comparison_df %>%
  filter(!str_starts(Method, "1")) %>%
  left_join(truth, by = "PolicyID")

face_accuracy <- checked %>%
  filter(Face_Missing) %>%
  group_by(Method) %>%
  summarise(imputed_face_amounts = n(),
            mean_error = mean(FaceAmount - TrueFaceAmount),
            mean_absolute_error = mean(abs(FaceAmount - TrueFaceAmount)),
            spread_ratio = sd(FaceAmount) / sd(TrueFaceAmount),  # 1 = same spread as the truth
            .groups = "drop")

category_accuracy <- checked %>%
  group_by(Method) %>%
  summarise(gender_correct = mean((Gender_Clean == TrueGender)[Gender_Missing]),
            smoker_correct = mean((Smoker_Clean == TrueSmoker)[Smoker_Missing]),
            true_smokers_labelled_non_smoker =
              mean((Smoker_Clean == "Non-Smoker")[Smoker_Missing & TrueSmoker == "Smoker"]),
            .groups = "drop")

imputation_accuracy <- face_accuracy %>% left_join(category_accuracy, by = "Method")
write_csv(imputation_accuracy, file.path(DATA_DIR, "imputation_accuracy.csv"))
print(imputation_accuracy %>% mutate(across(where(is.numeric), ~ round(.x, 3))))

cat("Wrote imputation_plot.png, glm_multipliers.png, glm_multipliers.csv and",
    "imputation_accuracy.csv to", DATA_DIR, "\n")