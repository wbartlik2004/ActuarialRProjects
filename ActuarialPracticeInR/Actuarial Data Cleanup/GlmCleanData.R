library(tidyverse)
library(scales)

# 1. Load all four exported imputation tables
df_complete <- read_csv("CleaningLifeData/1DropNA.csv") %>% mutate(Method = "1. Complete-Case (Listwise Deletion)")
df_single   <- read_csv("CleaningLifeData/2MeanModeReplacement.csv")   %>% mutate(Method = "2. Single Imputation (Mean/Mode)")
df_reg      <- read_csv("CleaningLifeData/3DeterministicRegression.csv") %>% mutate(Method = "3. Regression Imputation")
df_stoch    <- read_csv("CleaningLifeData/4StochasticImputation.csv")  %>% mutate(Method = "4. Stochastic Imputation")

# 2. Combine them into a single faceted comparison dataframe
comparison_df <- bind_rows(df_complete, df_single, df_reg, df_stoch)

# 3. Plot Density Comparison of Face Amounts Across Methods
imputation_plot <- ggplot(comparison_df, aes(x = FaceAmount, fill = Method)) +
  geom_density(alpha = 0.5) +
  facet_wrap(~ Method, scales = "free_y") +
  scale_x_continuous(labels = dollar) +
  labs(
    title = "Comparison of Missing Data Imputation Methods",
    subtitle = "Impact on Portfolio Face Amount Distributions",
    x = "Policy Face Amount ($)",
    y = "Density",
    fill = "Imputation Strategy"
  ) +
  theme_minimal() +
  theme(legend.position = "none")

# Output the plot to a PNG file
ggsave("imputation_plot.png", plot = imputation_plot, width = 8, height = 8, dpi = 300)