"""
Yield curve, rate shocks and present values, used by LiabilityCashflows.py and
AssetPortfolio.py.

Baseline curve: U.S. Treasury spot yields at 12/31/2019 (the valuation date), from the FDIC
Quarterly Banking Profile graph book, "U.S. Treasury Yield Curves" table. Years between
published maturities are LINEAR INTERPOLATIONS, and years past 30 are held flat at the
30-year rate (both assumptions).

Conventions
  * Cash flows land at the END of projection year t and are discounted at the t-year spot
    rate:  DF_t = (1 + s_t + spread) ** (-t).
  * The value at the end of year t of later cash flows uses the curve's forward rates:
    DF_u / DF_t. So value_by_year()[0] is the present value, and each later entry is the
    liability (reserve) still held at that year end, on the same curve.
  * Shocks are parallel shifts in basis points, floored at RATE_FLOOR. This is a simple
    parallel test, not the New York 7 scenarios.

Run this file on its own to write and print the three curves.
"""
import os
import numpy as np
import pandas as pd

# ---------------- settings ----------------
CURVE_DIR  = "LifeRVCFTesting/Curves"
HORIZON    = 50
SHOCK_BP   = 100
RATE_FLOOR = 0.0

# (maturity in years, spot yield in percent), 12/31/2019
KNOTS = {0.25: 1.61, 0.5: 1.61, 1: 1.58, 2: 1.59, 3: 1.59, 5: 1.62, 7: 1.72, 10: 1.79, 30: 2.26}
# ------------------------------------------


def build_baseline_curve(horizon=HORIZON):
    years = np.arange(1, horizon + 1)
    x = np.array(list(KNOTS.keys()), dtype=float)
    y = np.array(list(KNOTS.values())) / 100.0
    return pd.DataFrame({"t": years, "spot_rate": np.interp(years, x, y)})   # flat past 30


def shift_curve(curve, bp, floor=RATE_FLOOR):
    out = curve.copy()
    out["spot_rate"] = np.maximum(out["spot_rate"] + bp / 10000.0, floor)
    return out


def build_curves(horizon=HORIZON, shock_bp=SHOCK_BP):
    base = build_baseline_curve(horizon)
    return {"down": shift_curve(base, -shock_bp), "base": base, "up": shift_curve(base, shock_bp)}


def discount_factors(curve, spread_bp=0.0):
    s = curve["spot_rate"].to_numpy() + spread_bp / 10000.0
    return (1.0 + s) ** (-curve["t"].to_numpy())


def forward_rates(curve, spread_bp=0.0):
    """One-year forward rate for each year t: the rate earned from t-1 to t."""
    df = np.concatenate([[1.0], discount_factors(curve, spread_bp)])
    return df[:-1] / df[1:] - 1.0


def pv(cf, curve, spread_bp=0.0):
    """Present value of cash flows at the end of years 1..len(cf)."""
    cf = np.asarray(cf, dtype=float)
    return float((cf * discount_factors(curve, spread_bp)[: len(cf)]).sum())


def value_by_year(cf, curve, terminal=0.0, spread_bp=0.0):
    """Value at the end of each year t = 0..H of the cash flows after t, plus `terminal`
    paid at H. Entry 0 is the present value; entry H is the terminal amount."""
    cf = np.asarray(cf, dtype=float)
    H = len(cf)
    df = np.concatenate([[1.0], discount_factors(curve, spread_bp)[:H]])
    disc = cf * df[1:]
    later = np.concatenate([np.cumsum(disc[::-1])[::-1], [0.0]])    # sum of disc[u] for u > t
    return (later + terminal * df[H]) / df


def par_coupon(curve, maturity, spread_bp=0.0):
    """Annual coupon that prices an annual-pay bond at par on this curve plus spread."""
    dfs = discount_factors(curve, spread_bp)[: int(maturity)]
    return float((1.0 - dfs[-1]) / dfs.sum())


def bond_cash_flows(maturity, par, coupon, horizon):
    cf = np.zeros(horizon)
    cf[: int(maturity)] = par * coupon
    cf[int(maturity) - 1] += par
    return cf


def price_bonds(bonds, curve):
    """Market value of annual-pay bonds, each discounted at the curve plus its own spread."""
    total = 0.0
    for m, par, cpn, spr in bonds[["maturity", "par", "coupon", "spread_bp"]].itertuples(index=False):
        total += pv(bond_cash_flows(m, par, cpn, int(m)), curve, spr)
    return total


def bond_values_by_year(bonds, curve, horizon):
    """Market value at the end of each year 0..horizon of each bond's remaining cash flows
    (summed over bonds), on the curve plus each bond's spread."""
    total = np.zeros(horizon + 1)
    for m, par, cpn, spr in bonds[["maturity", "par", "coupon", "spread_bp"]].itertuples(index=False):
        total += value_by_year(bond_cash_flows(m, par, cpn, horizon), curve, 0.0, spr)
    return total


def effective_duration(pv_down, pv_up, pv_base, shock_bp=SHOCK_BP):
    """Approximate effective duration from a symmetric parallel shock."""
    return (pv_down - pv_up) / (2.0 * pv_base * shock_bp / 10000.0)


def main():
    os.makedirs(CURVE_DIR, exist_ok=True)
    curves = build_curves()
    for name, c in curves.items():
        c.assign(forward_rate=forward_rates(c), discount_factor=discount_factors(c)) \
         .to_csv(f"{CURVE_DIR}/yield_curve_{name}.csv", index=False)
    show = pd.DataFrame({k: (v.set_index("t")["spot_rate"] * 100).round(2) for k, v in curves.items()})
    print("Spot curve (percent):")
    print(show.loc[[1, 5, 10, 20, 30, 50]].to_string())
    print(f"\nwrote yield_curve_down/base/up.csv to {CURVE_DIR}/")


if __name__ == "__main__":
    main()