# install.packages("ggplot2")      # needs ggplot2 3.4 or newer
#
# Charts of the liability and asset projections, saved as PNG files in GRAPH_DIR.
# R version of Graphs.py: same nine charts, read from the same CSVs.
#
# Run the Python projection first (LiabilityCashflows.py, then AssetPortfolio.py), then run
# this from the folder that CONTAINS LifeRVCFTesting, because the paths start there:
#   in a terminal:   Rscript LifeRVCFTesting/Graphs.R
#   in R:            setwd("C:/Users/willi/Downloads/ActuarialPracticeInR")
#                    source("LifeRVCFTesting/Graphs.R")
#
# Charts
#   01_reserve_vs_account_value   reserve by year on each rate curve vs account value and CSV
#   02_liability_cash_flows       what the liability pays out each year, and premiums coming in
#   03_asset_vs_liability_cf      bond cash flows vs net liability outflow (the matching)
#   04_assets_vs_reserves_grid    assets and reserve by year, every lapse x rate scenario
#   05_surplus_by_year            surplus (assets - reserve) by year, all scenarios
#   06_cash_account               cash account by year (below zero = borrowing)
#   07_pvl_grid                   PV of liabilities, lapse x rates
#   08_ending_surplus             PV of ending surplus as % of reserve, by scenario
#   09_in_force_by_lapse          policies and account value still in force, by lapse run
#
# Amounts are shown in millions of the data's units (the actxps data is scaled, not dollars).

library(ggplot2)

# ---------------- settings ----------------
PROJ_DIR    <- "LifeRVCFTesting/Projections"
GRAPH_DIR   <- "LifeRVCFTesting/Graphs"
DPI         <- 150
SCALE       <- 1e6
UNIT        <- "millions (data units)"
LAPSES      <- c("low", "base", "high")
RATES       <- c("down", "base", "up")
RATE_COLORS <- c(down = "#2b6cb0", base = "#2f855a", up = "#c05621")
LAPSE_TYPES <- c(low = "dotted", base = "solid", high = "dashed", "no improvement" = "dotdash")
# ------------------------------------------


read_proj <- function(name) {
  path <- file.path(PROJ_DIR, paste0(name, ".csv"))
  if (!file.exists(path)) {
    stop("missing ", path, ": run LiabilityCashflows.py and AssetPortfolio.py first", call. = FALSE)
  }
  read.csv(path, stringsAsFactors = FALSE)
}

save_plot <- function(p, name, width = 9, height = 5) {
  path <- file.path(GRAPH_DIR, paste0(name, ".png"))
  ggsave(path, p, width = width, height = height, dpi = DPI, bg = "white")
  cat("  ", path, "\n")
}

theme_cft <- theme_minimal(base_size = 11) +
  theme(legend.position = "bottom", plot.title = element_text(size = 11))

zero_line <- geom_hline(yintercept = 0, linewidth = 0.3)


reserve_vs_av <- function(res) {
  series <- c("reserve, rates down", "reserve, rates base", "reserve, rates up",
              "account value in force", "cash surrender value")
  long <- rbind(
    data.frame(t = res$t, value = res$reserve_down,     series = series[1]),
    data.frame(t = res$t, value = res$reserve_base,     series = series[2]),
    data.frame(t = res$t, value = res$reserve_up,       series = series[3]),
    data.frame(t = res$t, value = res$av_in_force_end,  series = series[4]),
    data.frame(t = res$t, value = res$csv_in_force_end, series = series[5]))
  long <- long[!is.na(long$value), ]
  long$series <- factor(long$series, levels = series)
  p <- ggplot(long, aes(t, value / SCALE, colour = series, linetype = series)) +
    geom_line(linewidth = 0.8) + zero_line +
    scale_colour_manual(values = setNames(c(RATE_COLORS, "black", "grey50"), series)) +
    scale_linetype_manual(values = setNames(c("solid", "solid", "solid", "solid", "dashed"), series)) +
    labs(title = "Liability by year (base lapse): reserve vs account value",
         x = "projection year", y = UNIT, colour = NULL, linetype = NULL) +
    theme_cft
  save_plot(p, "01_reserve_vs_account_value")
}


liability_cash_flows <- function(cf) {
  parts <- c(death_benefits = "death benefits", surrender_payouts = "surrenders",
             maturity_payouts = "maturities", withdrawals_from_av = "withdrawals from account",
             withdrawals_insurer_paid = "withdrawals paid by insurer", premiums = "premiums (inflow)")
  colours <- c("#4a5568", "#c05621", "#805ad5", "#2b6cb0", "#e53e3e", "#38a169")
  long <- do.call(rbind, lapply(names(parts), function(col) {
    v <- cf[[col]]
    if (col == "premiums") v <- -v
    data.frame(t = cf$t, value = v, part = parts[[col]])
  }))
  long$part <- factor(long$part, levels = unname(parts))
  p <- ggplot(long, aes(t, value / SCALE)) +
    geom_col(aes(fill = part), width = 0.85) +
    geom_line(data = cf, aes(t, net_outflow / SCALE, linetype = "net outflow"), linewidth = 0.8) +
    zero_line +
    scale_fill_manual(values = setNames(colours, unname(parts))) +
    scale_linetype_manual(values = c("net outflow" = "solid")) +
    labs(title = "Expected liability cash flows by year (base lapse, average of index scenarios)",
         x = "projection year", y = UNIT, fill = NULL, linetype = NULL) +
    theme_cft
  save_plot(p, "02_liability_cash_flows", width = 10, height = 5.5)
}


asset_vs_liability <- function(acf, cf) {
  bars <- rbind(data.frame(t = acf$t, value = acf$coupons,   part = "bond coupons"),
                data.frame(t = acf$t, value = acf$principal, part = "bond principal"))
  bars$part <- factor(bars$part, levels = c("bond principal", "bond coupons"))
  net <- cf$net_outflow
  net[length(net)] <- net[length(net)] + cf$av_in_force_end[length(net)]   # terminal paid at the horizon
  line <- data.frame(t = cf$t, value = net)
  p <- ggplot(bars, aes(t, value / SCALE)) +
    geom_col(aes(fill = part), width = 0.85) +
    geom_line(data = line, aes(t, value / SCALE, linetype = "net liability outflow"), linewidth = 0.8) +
    geom_point(data = line, aes(t, value / SCALE), size = 0.8) +
    zero_line +
    scale_fill_manual(values = c("bond coupons" = "#90cdf4", "bond principal" = "#2b6cb0")) +
    scale_linetype_manual(values = c("net liability outflow" = "solid")) +
    labs(title = "Asset cash flows vs liability outflows (base lapse): the cash flow match",
         x = "projection year", y = UNIT, fill = NULL, linetype = NULL) +
    theme_cft
  save_plot(p, "03_asset_vs_liability_cf", width = 10)
}


assets_vs_reserves_grid <- function(sby) {
  d <- sby[sby$mortality == "with improvement", ]
  d$lapse <- factor(paste("lapse", d$lapse), levels = paste("lapse", LAPSES))
  d$rates <- factor(paste("rates", d$rates), levels = paste("rates", RATES))
  long <- rbind(data.frame(d[, c("t", "lapse", "rates")], value = d$assets,  series = "assets"),
                data.frame(d[, c("t", "lapse", "rates")], value = d$reserve, series = "reserve"))
  p <- ggplot(d, aes(t)) +
    geom_ribbon(aes(ymin = reserve / SCALE, ymax = pmax(assets, reserve) / SCALE),
                fill = "#38a169", alpha = 0.25) +
    geom_ribbon(aes(ymin = pmin(assets, reserve) / SCALE, ymax = reserve / SCALE),
                fill = "#e53e3e", alpha = 0.25) +
    geom_line(data = long, aes(t, value / SCALE, colour = series), linewidth = 0.7) +
    facet_grid(lapse ~ rates) +
    scale_colour_manual(values = c(assets = "#2b6cb0", reserve = "#c05621")) +
    labs(title = "Assets vs reserve by year (green = surplus, red = shortfall)",
         x = "projection year", y = UNIT, colour = NULL) +
    theme_cft
  save_plot(p, "04_assets_vs_reserves_grid", width = 13, height = 10)
}


lines_by_scenario <- function(sby, col, title, name) {
  d <- sby
  noimp <- d$mortality == "no improvement"
  d$value <- d[[col]]
  d$style <- ifelse(noimp, "no improvement", d$lapse)
  d$scenario <- paste0("lapse ", d$lapse, ", rates ", d$rates, ifelse(noimp, ", no improvement", ""))
  d$rates <- factor(d$rates, levels = RATES)
  d$style <- factor(d$style, levels = names(LAPSE_TYPES))
  p <- ggplot(d, aes(t, value / SCALE, colour = rates, linetype = style, group = scenario)) +
    geom_line(linewidth = 0.8) + zero_line +
    scale_colour_manual(values = RATE_COLORS, labels = paste("rates", RATES)) +
    scale_linetype_manual(values = LAPSE_TYPES,
                          labels = c("low lapse", "base lapse", "high lapse", "base lapse, no improvement")) +
    labs(title = title, x = "projection year", y = UNIT, colour = NULL, linetype = NULL) +
    theme_cft
  save_plot(p, name, width = 10, height = 5.5)
}


pvl_grid <- function(pv) {
  d <- pv[pv$run %in% LAPSES, ]
  d$run <- factor(paste("lapse", d$run), levels = rev(paste("lapse", LAPSES)))
  d$rates <- factor(paste("rates", d$rates), levels = paste("rates", RATES))
  p <- ggplot(d, aes(rates, run, fill = PVL / SCALE)) +
    geom_tile(colour = "white") +
    geom_text(aes(label = formatC(PVL / SCALE, format = "f", digits = 1, big.mark = ","))) +
    scale_fill_gradient(low = "#fff5eb", high = "#d94801", name = UNIT) +
    labs(title = "PV of liabilities, lapse x rate scenario", x = NULL, y = NULL) +
    theme_minimal(base_size = 11) + theme(panel.grid = element_blank())
  save_plot(p, "07_pvl_grid", width = 7, height = 4.5)
}


ending_surplus <- function(summ) {
  d <- summ
  d$label <- paste0(d$lapse, " lapse, ", d$rates, " rates",
                    ifelse(d$mortality == "no improvement", " (no impr.)", ""))
  d$label <- factor(d$label, levels = rev(d$label))
  d$pct <- d$pv_ending_pct_of_reserve * 100
  d$sign <- ifelse(d$pct < 0, "negative", "positive")
  p <- ggplot(d, aes(pct, label, fill = sign)) +
    geom_col() +
    geom_text(aes(label = sprintf(" %.2f%%", pct)), hjust = 0, size = 3) +
    geom_vline(xintercept = 0, linewidth = 0.3) +
    scale_fill_manual(values = c(negative = "#e53e3e", positive = "#38a169"), guide = "none") +
    scale_x_continuous(expand = expansion(mult = c(0.05, 0.15))) +
    labs(title = "PV of ending surplus by scenario", x = "% of baseline reserve", y = NULL) +
    theme_cft
  save_plot(p, "08_ending_surplus", width = 9, height = 6)
}


in_force_by_lapse <- function() {
  long <- do.call(rbind, lapply(LAPSES, function(l) {
    cf <- read_proj(paste0("liability_cf_", l))
    rbind(data.frame(t = cf$t, value = cf$lives_end, lapse = l, metric = "Expected policies in force"),
          data.frame(t = cf$t, value = cf$av_in_force_end / SCALE, lapse = l,
                     metric = paste("Account value in force,", UNIT)))
  }))
  long$lapse <- factor(long$lapse, levels = LAPSES)
  p <- ggplot(long, aes(t, value, linetype = lapse)) +
    geom_line(linewidth = 0.7) +
    facet_wrap(~ metric, scales = "free_y") +
    scale_linetype_manual(values = LAPSE_TYPES[LAPSES], labels = paste("lapse", LAPSES)) +
    labs(x = "projection year", y = NULL, linetype = NULL) +
    theme_cft
  save_plot(p, "09_in_force_by_lapse", width = 12, height = 4.8)
}


main <- function() {
  dir.create(GRAPH_DIR, recursive = TRUE, showWarnings = FALSE)
  cf   <- read_proj("liability_cf_base")
  res  <- read_proj("reserves_base")
  pv   <- read_proj("liability_pv_results")
  acf  <- read_proj("asset_cf")
  sby  <- read_proj("surplus_by_year")
  summ <- read_proj("cft_summary")

  cat("writing charts to", GRAPH_DIR, "\n")
  reserve_vs_av(res)
  liability_cash_flows(cf)
  asset_vs_liability(acf, cf)
  assets_vs_reserves_grid(sby)
  lines_by_scenario(sby, "surplus", "Surplus (assets - reserve) by year, all scenarios", "05_surplus_by_year")
  lines_by_scenario(sby, "cash", "Cash account by year (below zero = borrowing)", "06_cash_account")
  pvl_grid(pv)
  ending_surplus(summ)
  in_force_by_lapse()
  cat("done\n")
}

main()