# ==========================================================
# ADVANCED P&C STOCHASTIC LOSS RESERVING & DIAGNOSTICS SUITE
# ==========================================================
library(ChainLadder)
library(tidyverse)
library(scales)

# ---------------- settings ----------------
OUT_DIR   <- "Loss Reserving"                          # CSV outputs (relative to where you run R)
GRAPH_DIR <- file.path(OUT_DIR, "LossReservingGraphs")  # chart images
# ------------------------------------------
dir.create(GRAPH_DIR, recursive = TRUE, showWarnings = FALSE)   # creates both folders if needed

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
# 3. BORNHUETTER-FERGUSON WITH A CAPE COD A PRIORI
# ==========================================================
# BF needs an expected loss for each accident year that does not come from that
# year's own chain-ladder result. GenIns has no premium, so the expected losses are
# estimated with the Cape Cod (Stanard-Buhlmann) method:
#
#   expected loss per unit of exposure = sum(latest claims) / sum(exposure / CDF)
#
# Each year counts in proportion to how much of its ultimate has been reported
# (1 / CDF), so mature years carry most of the weight and the volatile recent years
# very little. With no premium the exposure is assumed flat (1 per year). If earned
# premium were available, it would go in `exposure` and the result would be an
# expected loss ratio.
latest_actual <- as.numeric(getLatestCumulative(triangle))
cl_ultimate   <- as.numeric(mack_fit$FullTriangle[, ncol(mack_fit$FullTriangle)])
cdf           <- cl_ultimate / latest_actual        # age-to-ultimate factors
pct_reported  <- 1 / cdf
pct_unreported <- 1 - pct_reported

exposure            <- rep(1, nrow(triangle))       # replace with earned premium if available
cape_cod_rate       <- sum(latest_actual) / sum(exposure * pct_reported)
expected_losses     <- cape_cod_rate * exposure     # a priori expected ultimate by year

bf_ultimate_vector <- latest_actual + expected_losses * pct_unreported
bf_reserve         <- sum(bf_ultimate_vector) - sum(latest_actual)

# How much the BF reserve depends on the a priori
bf_sensitivity <- tibble(
  A_Priori_Scale = c(0.90, 1.00, 1.10),
  A_Priori_Per_Year = cape_cod_rate * A_Priori_Scale,
  BF_Reserve = map_dbl(A_Priori_Scale, ~ sum(expected_losses * .x * pct_unreported))
)

bf_by_year <- tibble(
  AccidentYear = rownames(triangle),
  Latest = latest_actual,
  CDF = cdf,
  Pct_Reported = pct_reported,
  CL_Ultimate = cl_ultimate,
  A_Priori = expected_losses,
  BF_Ultimate = bf_ultimate_vector
)

# ==========================================================
# 4. ANOVA TEST FOR CALENDAR YEAR EFFECT
# ==========================================================
# Chain-ladder assumes claims develop the same way at each age, whatever calendar year
# it is. A calendar-year (diagonal) effect, such as a burst of inflation or a change in
# claims handling, would break that. The test fits log incremental claims on accident
# year and development year, then checks whether adding calendar year improves the fit.
# Development year has to be in the model: within an accident year, calendar year rises
# with development year, so without it a "calendar year" term just picks up normal
# development and always looks significant.
# Calendar year = accident year + development year - 1, so two calendar-year terms are
# redundant; lm() drops them and the F test uses the remaining 8.
incr_df <- as.data.frame(cum2incr(triangle))
colnames(incr_df) <- c("Origin", "Development", "Incremental")

tri_df <- incr_df %>%
  filter(!is.na(Incremental), Incremental > 0) %>%   # log needs positive values (all are, for GenIns)
  mutate(
    AccidentYear = as.factor(Origin),
    DevYear      = as.factor(Development),
    CalendarYear = as.factor(as.numeric(as.character(Origin)) +
                             as.numeric(as.character(Development)) - 1)
  )

base_model     <- lm(log(Incremental) ~ AccidentYear + DevYear, data = tri_df)
cy_anova_model <- lm(log(Incremental) ~ AccidentYear + DevYear + CalendarYear, data = tri_df)
anova_results  <- anova(base_model, cy_anova_model)     # F test: does calendar year add anything?
cy_p_value     <- anova_results[["Pr(>F)"]][2]

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
  Reserving_Method = c("Chain-Ladder (Mack standard error)",
                       "Bornhuetter-Ferguson (Cape Cod a priori)",
                       "Bootstrap VaR (90%)"),
  Estimated_Reserve = c(mack_reserve_val, bf_reserve, as.numeric(var_90)),
  Standard_Error_CV = c(
    paste0(dollar(mack_se_val), " (CV: ", round(mack_cv_val, 3), ")"),
    "N/A (depends on the a priori; see bf_sensitivity.csv)",
    "Empirical Tail Distribution"
  )
)

cat("\n=== 2. CORE METHOD COMPARISON & CAPITAL MARGINS ===\n")
print(master_comparison_table, row.names = FALSE)

cat("\n=== BORNHUETTER-FERGUSON BY ACCIDENT YEAR ===\n")
cat("Cape Cod expected losses per accident year:", dollar(cape_cod_rate), "\n")
print(bf_by_year %>% mutate(across(c(Latest, CL_Ultimate, A_Priori, BF_Ultimate), dollar),
                            across(c(CDF, Pct_Reported), ~ round(.x, 3))))
cat("\n=== BF SENSITIVITY TO THE A PRIORI ===\n")
print(bf_sensitivity)

cat("\n=== 3. TAIL FACTOR SENSITIVITY STRESS TEST ===\n")
print(tail_sensitivity_results, row.names = FALSE)

cat("\n=== 4. ANOVA CALENDAR YEAR EFFECT DIAGNOSTIC ===\n")
print(anova_results)
cat("Calendar year effect p-value:", signif(cy_p_value, 3),
    ifelse(cy_p_value < 0.05, "(significant at 5%)", "(not significant at 5%)"), "\n")

# ==========================================================
# 7. EXPORT
# ==========================================================
write_csv(master_comparison_table, file.path(OUT_DIR, "loss_reserving_master_summary.csv"))
write_csv(tail_sensitivity_results, file.path(OUT_DIR, "tail_factor_sensitivity.csv"))
write_csv(bf_by_year, file.path(OUT_DIR, "bf_by_accident_year.csv"))
write_csv(bf_sensitivity, file.path(OUT_DIR, "bf_sensitivity.csv"))
cat("\n[SUCCESS] All summary tables printed and exported to CSV files!\n")

# ==========================================================
# 8. CHARTS (saved to GRAPH_DIR)
# ==========================================================
origin_levels <- rownames(triangle)

# --- 1. Claims development: actual triangle and chain-ladder projection ---
actual_df <- as.data.frame(triangle)
colnames(actual_df) <- c("Origin", "Development", "Value")
actual_df <- actual_df %>%
  filter(!is.na(Value)) %>%
  mutate(Origin = factor(as.character(Origin), levels = origin_levels),
         Development = as.numeric(as.character(Development)))

latest_dev <- actual_df %>% group_by(Origin) %>% summarise(last_dev = max(Development), .groups = "drop")

projected_df <- as.data.frame(mack_fit$FullTriangle)
colnames(projected_df) <- c("Origin", "Development", "Value")
projected_df <- projected_df %>%
  mutate(Origin = factor(as.character(Origin), levels = origin_levels),
         Development = as.numeric(as.character(Development))) %>%
  inner_join(latest_dev, by = "Origin") %>%
  filter(Development >= last_dev)              # starts at the latest actual value, so the lines join

development_plot <- ggplot() +
  geom_line(data = projected_df, aes(Development, Value, colour = Origin), linetype = "dashed") +
  geom_line(data = actual_df, aes(Development, Value, colour = Origin), linewidth = 0.9) +
  geom_point(data = actual_df, aes(Development, Value, colour = Origin), size = 1.2) +
  scale_y_continuous(labels = dollar) +
  scale_x_continuous(breaks = 1:ncol(triangle)) +
  labs(title = "Cumulative claims by accident year",
       subtitle = "Solid = actual, dashed = chain-ladder projection to ultimate",
       x = "Development year", y = "Cumulative claims", colour = "Accident year") +
  theme_minimal()
ggsave(file.path(GRAPH_DIR, "1_claims_development.png"), development_plot,
       width = 9, height = 5.5, dpi = 300, bg = "white")

# --- 2. Age-to-age factors: how much they vary across accident years ---
ata_tri <- ata(triangle)
ata_mat <- matrix(ata_tri, nrow = nrow(ata_tri), dimnames = unname(dimnames(ata_tri)))
ata_df  <- as.data.frame(as.table(ata_mat)) %>%
  rename(Origin = Var1, Period = Var2, Factor = Freq) %>%
  filter(!is.na(Factor))
selected_df <- tibble(Period = factor(colnames(ata_mat), levels = colnames(ata_mat)),
                      Factor = as.numeric(attr(ata_tri, "vwtd")))

ata_plot <- ggplot(ata_df, aes(Period, Factor)) +
  geom_jitter(width = 0.1, height = 0, alpha = 0.6, colour = "grey30") +
  geom_point(data = selected_df, colour = "#c05621", size = 3, shape = 18) +
  scale_y_log10() +
  labs(title = "Age-to-age development factors",
       subtitle = "Grey = each accident year, orange = volume-weighted factor used by chain-ladder (log scale)",
       x = "Development period", y = "Factor") +
  theme_minimal()
ggsave(file.path(GRAPH_DIR, "2_development_factors.png"), ata_plot,
       width = 9, height = 5, dpi = 300, bg = "white")

# --- 3. Reserve by accident year with Mack standard error ---
mack_se_by_year <- as.numeric(mack_fit$Mack.S.E[, ncol(mack_fit$Mack.S.E)])
reserve_by_year <- bf_by_year %>%
  mutate(AccidentYear = factor(AccidentYear, levels = origin_levels),
         CL_Reserve = CL_Ultimate - Latest,
         BF_Reserve = BF_Ultimate - Latest,
         Mack_SE = mack_se_by_year,
         CV = ifelse(CL_Reserve > 0, Mack_SE / CL_Reserve, NA))

mack_plot <- ggplot(reserve_by_year, aes(AccidentYear, CL_Reserve)) +
  geom_col(fill = "#2b6cb0", alpha = 0.8) +
  geom_errorbar(aes(ymin = pmax(CL_Reserve - Mack_SE, 0), ymax = CL_Reserve + Mack_SE), width = 0.3) +
  geom_text(aes(y = CL_Reserve + Mack_SE, label = ifelse(is.na(CV), "", paste0("CV ", percent(CV, 1)))),
            vjust = -0.6, size = 3) +
  scale_y_continuous(labels = dollar, expand = expansion(mult = c(0, 0.1))) +
  labs(title = "Chain-ladder reserve by accident year",
       subtitle = "Error bars = plus or minus one Mack standard error",
       x = "Accident year", y = "Reserve") +
  theme_minimal()
ggsave(file.path(GRAPH_DIR, "3_reserve_by_year_mack.png"), mack_plot,
       width = 9, height = 5, dpi = 300, bg = "white")

# --- 4. Chain-ladder vs Bornhuetter-Ferguson by accident year ---
cl_bf_df <- reserve_by_year %>%
  select(AccidentYear, `Chain-ladder` = CL_Reserve, `Bornhuetter-Ferguson` = BF_Reserve) %>%
  pivot_longer(-AccidentYear, names_to = "Method", values_to = "Reserve")

cl_bf_plot <- ggplot(cl_bf_df, aes(AccidentYear, Reserve, fill = Method)) +
  geom_col(position = "dodge") +
  scale_y_continuous(labels = dollar) +
  scale_fill_manual(values = c("Chain-ladder" = "#2b6cb0", "Bornhuetter-Ferguson" = "#c05621")) +
  labs(title = "Reserve by accident year: chain-ladder vs Bornhuetter-Ferguson",
       subtitle = "BF leans on the Cape Cod a priori for the least developed years",
       x = "Accident year", y = "Reserve", fill = NULL) +
  theme_minimal() +
  theme(legend.position = "bottom")
ggsave(file.path(GRAPH_DIR, "4_chain_ladder_vs_bf.png"), cl_bf_plot,
       width = 9, height = 5, dpi = 300, bg = "white")

# --- 5. Bootstrap distribution of the total reserve ---
boot_lines <- tibble(
  label = c("Chain-ladder best estimate", "75th percentile", "90th percentile", "95th percentile"),
  value = c(mack_reserve_val, as.numeric(var_75), as.numeric(var_90), as.numeric(var_95))
) %>% mutate(label = factor(label, levels = label))

boot_plot <- ggplot(tibble(Reserve = as.numeric(boot_reserves)), aes(Reserve)) +
  geom_histogram(bins = 60, fill = "grey75", colour = "white") +
  geom_vline(data = boot_lines, aes(xintercept = value, colour = label, linetype = label), linewidth = 0.8) +
  scale_colour_manual(values = c("black", "#2f855a", "#c05621", "#c53030")) +
  scale_linetype_manual(values = c("solid", "dashed", "dashed", "dashed")) +
  scale_x_continuous(labels = dollar) +
  labs(title = "Bootstrap distribution of the total reserve",
       subtitle = paste0(format(length(boot_reserves), big.mark = ","), " simulations, gamma process distribution"),
       x = "Total reserve", y = "Simulations", colour = NULL, linetype = NULL) +
  theme_minimal() +
  theme(legend.position = "bottom")
ggsave(file.path(GRAPH_DIR, "5_bootstrap_distribution.png"), boot_plot,
       width = 9, height = 5, dpi = 300, bg = "white")

# --- 6. What moves the reserve: every estimate and sensitivity against the best estimate ---
reserve_range <- bind_rows(
  tibble(group = "Method", scenario = "Chain-ladder (best estimate)", reserve = mack_reserve_val),
  tibble(group = "Method", scenario = "Bornhuetter-Ferguson (Cape Cod)", reserve = bf_reserve),
  tibble(group = "BF a priori",
         scenario = paste0("BF, a priori ", ifelse(bf_sensitivity$A_Priori_Scale < 1, "-10%", "+10%")),
         reserve = bf_sensitivity$BF_Reserve)[bf_sensitivity$A_Priori_Scale != 1, ],
  tibble(group = "Tail factor",
         scenario = paste0("Tail factor ", tail_sensitivity_results$Tail_Factor),
         reserve = tail_sensitivity_results$Total_Reserve)[tail_sensitivity_results$Tail_Factor != 1, ],
  tibble(group = "Bootstrap percentile",
         scenario = c("Bootstrap 75th", "Bootstrap 90th", "Bootstrap 95th"),
         reserve = c(as.numeric(var_75), as.numeric(var_90), as.numeric(var_95)))
) %>%
  mutate(scenario = factor(scenario, levels = rev(scenario)))

range_plot <- ggplot(reserve_range, aes(reserve, scenario, fill = group)) +
  geom_col() +
  geom_vline(xintercept = mack_reserve_val, linetype = "dashed") +
  geom_text(aes(label = dollar(round(reserve / 1e5) * 1e5)), hjust = -0.1, size = 3) +
  scale_x_continuous(labels = dollar, expand = expansion(mult = c(0, 0.15))) +
  scale_fill_manual(values = c("Method" = "#2b6cb0", "BF a priori" = "#805ad5",
                               "Tail factor" = "#c05621", "Bootstrap percentile" = "#718096")) +
  labs(title = "What moves the reserve",
       subtitle = "Dashed line = chain-ladder best estimate",
       x = "Total reserve", y = NULL, fill = NULL) +
  theme_minimal() +
  theme(legend.position = "bottom")
ggsave(file.path(GRAPH_DIR, "6_what_moves_the_reserve.png"), range_plot,
       width = 9, height = 6, dpi = 300, bg = "white")

cat("[SUCCESS] Charts saved to", GRAPH_DIR, "\n")