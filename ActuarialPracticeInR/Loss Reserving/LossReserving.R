# ==========================================================
# ADVANCED P&C STOCHASTIC LOSS RESERVING & DIAGNOSTICS SUITE
# ==========================================================
library(ChainLadder)
library(tidyverse)
library(scales)

data(GenIns)
triangle <- GenIns

cat("==========================================================\n")
cat(" 1. ORIGINAL CUMULATIVE LOSS TRIANGLE\n")
cat("==========================================================\n")
print(triangle)

# Helper: pull total reserve / SE / CV straight from a Mack fit
mack_totals <- function(fit) {
  latest   <- getLatestCumulative(fit$Triangle)
  ult      <- fit$FullTriangle[, ncol(fit$FullTriangle)]
  reserve  <- sum(ult - latest)
  se       <- fit$Total.Mack.S.E
  list(reserve = reserve, se = se, cv = se / reserve)
}

# ==========================================================
# 2. MACK STOCHASTIC & BOOTSTRAP CAPITAL (VaR)
# ==========================================================
mack_fit <- MackChainLadder(triangle, est.sigma = "Mack")
mt <- mack_totals(mack_fit)
mack_reserve_val <- mt$reserve
mack_se_val      <- mt$se
mack_cv_val      <- mt$cv

set.seed(2026)
boot_fit <- BootChainLadder(triangle, R = 5000, process.dist = "gamma")
boot_reserves <- boot_fit$IBNR.Totals          # simulated total reserves

var_75 <- quantile(boot_reserves, 0.75)
var_90 <- quantile(boot_reserves, 0.90)
var_95 <- quantile(boot_reserves, 0.95)

# ==========================================================
# 3. BORNHUETTER-FERGUSON
# ==========================================================
latest_actual <- as.numeric(getLatestCumulative(triangle))
cl_ultimate   <- as.numeric(mack_fit$FullTriangle[, ncol(mack_fit$FullTriangle)])
ult_factors   <- cl_ultimate / latest_actual        # age-to-ultimate CDFs

# GenIns has no premium data, so use a flat exposure base at the scale of the
# data (average CL ultimate / assumed ELR). Flat across years, so the a priori
# is independent of each year's own chain-ladder result.
assumed_elr      <- 0.65
earned_premium   <- rep(mean(cl_ultimate) / assumed_elr, nrow(triangle))
expected_losses  <- earned_premium * assumed_elr    # = mean(cl_ultimate) each year

bf_ultimate_vector <- latest_actual + expected_losses * (1 - 1 / ult_factors)
bf_ultimate <- sum(bf_ultimate_vector)
bf_reserve  <- bf_ultimate - sum(latest_actual)

# ==========================================================
# 4. ANOVA TEST FOR CALENDAR YEAR EFFECT
# ==========================================================
tri_df <- as.data.frame(triangle)
colnames(tri_df) <- c("Origin", "Development", "Value")

tri_df <- tri_df %>%
  filter(!is.na(Value)) %>%
  mutate(
    AccidentYear = as.factor(Origin),
    CalendarYear = as.factor(as.numeric(as.character(Origin)) +
                             as.numeric(as.character(Development)) - 1)
  )

cy_anova_model <- lm(Value ~ AccidentYear + CalendarYear, data = tri_df)
anova_results  <- anova(cy_anova_model)

# ==========================================================
# 5. TAIL FACTOR SENSITIVITY
# ==========================================================
tail_factors <- c(1.00, 1.02, 1.05, 1.10)

tail_sensitivity_results <- map_dfr(tail_factors, function(tf) {
  fit <- MackChainLadder(triangle, est.sigma = "Mack", tail = tf)
  data.frame(Tail_Factor = tf, Total_Reserve = mack_totals(fit)$reserve)
})

# ==========================================================
# 6. PRINTED SUMMARY TABLES
# ==========================================================
master_comparison_table <- data.frame(
  Reserving_Method = c("Standard Chain-Ladder", "Bornhuetter-Ferguson (BF)",
                       "Mack Stochastic", "Bootstrap VaR (90%)"),
  Estimated_Reserve = c(mack_reserve_val, bf_reserve, mack_reserve_val, as.numeric(var_90)),
  Standard_Error_CV = c(
    paste0(dollar(mack_se_val), " (CV: ", round(mack_cv_val, 3), ")"),
    "N/A (A-priori assumption)",
    paste0(dollar(mack_se_val), " (CV: ", round(mack_cv_val, 3), ")"),
    "Empirical Tail Distribution"
  )
)

cat("\n=== 2. CORE METHOD COMPARISON & CAPITAL MARGINS ===\n")
print(master_comparison_table, row.names = FALSE)

cat("\n=== 3. TAIL FACTOR SENSITIVITY STRESS TEST ===\n")
print(tail_sensitivity_results, row.names = FALSE)

cat("\n=== 4. ANOVA CALENDAR YEAR EFFECT DIAGNOSTIC ===\n")
print(anova_results)

# ==========================================================
# 7. EXPORT
# ==========================================================
write_csv(master_comparison_table, "loss_reserving_master_summary.csv")
write_csv(tail_sensitivity_results, "tail_factor_sensitivity.csv")
cat("\n[SUCCESS] All summary tables printed and exported to CSV files!\n")