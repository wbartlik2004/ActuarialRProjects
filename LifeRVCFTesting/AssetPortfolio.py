"""
Asset portfolio built from the liability projection, and a year-by-year cash flow test.

Design
  * Starting assets = SIZE_FACTOR x the baseline reserve at time 0 (base lapse, base curve).
  * Bonds: annual-pay, bought at par on 12/31/2019, maturities 1..BOND_MAX_MAT. Each
    maturity is split CORP_SHARE corporate (assumed spreads below) / the rest Treasury.
    Coupons are par coupons on the baseline curve plus spread.
  * CASH FLOW MATCHING: working back from the longest maturity, each maturity's par is set
    so coupons plus principal landing in a year cover that year's expected net liability
    outflow (base run). Outflows after BOND_MAX_MAT, and the account value still owed at the
    horizon, are moved to BOND_MAX_MAT at their value there. Years where premiums exceed
    outflows need no bonds.
  * Whatever the matched bonds don't use starts in a cash account. Because corporates yield
    more than the Treasury curve used for the reserve, the matched bonds usually cost less
    than the reserve: that difference is the starting cash buffer.

Cash flow test, for every lapse x rate scenario (and no mortality improvement):
  * Bond cash flows are fixed (no defaults, no sales, no calls).
  * cash_t = cash_{t-1} x (1 + one-year forward rate on that scenario's curve)
             + bond cash flows_t - net liability outflow_t   (negative cash = borrowing)
  * At each year end: assets = cash + market value of the remaining bonds (that curve plus
    each bond's spread); surplus = assets - reserve (same curve, same lapse run).
  * Ending surplus = cash left after the terminal account value is paid at the horizon.

Run after LiabilityCashflows.py. Needs Discounting.py in the same folder.
"""
import os
import numpy as np
import pandas as pd

import Discounting as d

# ---------------- settings ----------------
LIAB_DIR      = "LifeRVCFTesting/Projections"   # liability_cf_<run>.csv, reserves_<run>.csv
OUT_DIR       = "LifeRVCFTesting/Projections"
HORIZON       = d.HORIZON
SIZE_FACTOR   = 1.00                # starting assets = this x baseline reserve
BOND_MAX_MAT  = 30                  # longest bond available
CORP_SHARE    = 0.60                # share of each maturity in corporates
SPREAD_KNOTS  = {1: 40, 2: 50, 3: 60, 5: 80, 10: 110, 15: 130, 20: 140, 30: 150}   # assumed, bp
LAPSE_RUNS    = ["low", "base", "high"]
RATES         = ["down", "base", "up"]
# ------------------------------------------


def spread_bp(maturity):
    x, y = np.array(list(SPREAD_KNOTS)), np.array(list(SPREAD_KNOTS.values()), dtype=float)
    return float(np.interp(maturity, x, y))


def load_run(run):
    cf = pd.read_csv(f"{LIAB_DIR}/liability_cf_{run}.csv")
    res = pd.read_csv(f"{LIAB_DIR}/reserves_{run}.csv")
    assert len(cf) == HORIZON, f"{run}: liability file has {len(cf)} years, expected {HORIZON}"
    return cf, res


def matching_targets(cf, curve):
    """Net outflow by year 1..BOND_MAX_MAT, with everything later folded into the last year."""
    net = cf["net_outflow"].to_numpy(dtype=float)
    terminal = float(cf["av_in_force_end"].to_numpy(dtype=float)[-1])
    later = d.value_by_year(net, curve, terminal)[BOND_MAX_MAT]       # value at BOND_MAX_MAT of what follows
    target = net[:BOND_MAX_MAT].copy()
    target[-1] += later
    return target, later


def build_bonds(target, curve):
    """Bootstrap pars so each year's bond cash flows cover that year's target."""
    rows = []
    for m in range(1, BOND_MAX_MAT + 1):
        for kind, share, spr in (("Treasury", 1 - CORP_SHARE, 0.0), ("Corporate", CORP_SHARE, spread_bp(m))):
            rows.append({"type": kind, "maturity": m, "share": share, "spread_bp": spr,
                         "coupon": d.par_coupon(curve, m, spr)})
    bonds = pd.DataFrame(rows)
    blend = (bonds["share"] * bonds["coupon"]).groupby(bonds["maturity"]).sum()   # coupon per 1 of par at m

    need = target.astype(float).copy()
    par_m = np.zeros(BOND_MAX_MAT + 1)
    for m in range(BOND_MAX_MAT, 0, -1):
        par_m[m] = max(0.0, need[m - 1]) / (1.0 + blend[m])
        need[: m - 1] -= par_m[m] * blend[m]
    bonds["par"] = bonds["share"] * par_m[bonds["maturity"].to_numpy()]
    bonds = bonds[bonds["par"] > 0].drop(columns="share").reset_index(drop=True)
    bonds.insert(0, "bond_id", [f"B{i + 1:02d}" for i in range(len(bonds))])
    return bonds


def asset_cash_flows(bonds, horizon=HORIZON):
    coupons, principal = np.zeros(horizon), np.zeros(horizon)
    for m, par, cpn in bonds[["maturity", "par", "coupon"]].itertuples(index=False):
        coupons[: int(m)] += par * cpn
        principal[int(m) - 1] += par
    return coupons, principal


def cash_flow_test(bonds, start_cash, cf, res, curve, rate):
    """Year-by-year cash, asset market value, reserve and surplus for one scenario."""
    coupons, principal = asset_cash_flows(bonds)
    bond_cf = coupons + principal
    liab = cf["net_outflow"].to_numpy(dtype=float).copy()
    liab[-1] += float(cf["av_in_force_end"].to_numpy(dtype=float)[-1])                # terminal account value paid at H
    fwd = d.forward_rates(curve)

    cash = np.zeros(HORIZON + 1)
    cash[0] = start_cash
    for t in range(1, HORIZON + 1):
        cash[t] = cash[t - 1] * (1 + fwd[t - 1]) + bond_cf[t - 1] - liab[t - 1]
    bonds_mv = d.bond_values_by_year(bonds, curve, HORIZON)
    reserve = res[f"reserve_{rate}"].to_numpy(dtype=float).copy()
    reserve[-1] = 0.0                                                  # terminal already paid out of cash
    assets = cash + bonds_mv
    return pd.DataFrame({"t": np.arange(HORIZON + 1), "bond_cash_flow": np.concatenate([[0], bond_cf]),
                         "net_liability_outflow": np.concatenate([[0], liab]), "cash": cash,
                         "bond_market_value": bonds_mv, "assets": assets, "reserve": reserve,
                         "surplus": assets - reserve})


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pd.set_option("display.width", 200)
    curves = d.build_curves(HORIZON)
    base_cf, base_res = load_run("base")

    reserve0 = float(base_res["reserve_base"].to_numpy(dtype=float)[0])
    start_assets = SIZE_FACTOR * reserve0
    target, later = matching_targets(base_cf, curves["base"])
    bonds = build_bonds(target, curves["base"])
    cost = bonds["par"].sum()
    if cost > start_assets:
        print(f"NOTE: matched bonds cost {cost:,.0f} > starting assets {start_assets:,.0f}; scaling them down")
        bonds["par"] *= start_assets / cost
        cost = start_assets
    start_cash = start_assets - cost

    coupons, principal = asset_cash_flows(bonds)
    bonds.to_csv(f"{OUT_DIR}/asset_portfolio.csv", index=False)
    pd.DataFrame({"t": np.arange(1, HORIZON + 1), "coupons": coupons, "principal": principal,
                  "cash_flow": coupons + principal}).to_csv(f"{OUT_DIR}/asset_cf.csv", index=False)

    print(f"baseline reserve {reserve0:,.0f}; starting assets {start_assets:,.0f} "
          f"(SIZE_FACTOR {SIZE_FACTOR})")
    print(f"matched bonds: {len(bonds)} bonds, cost {cost:,.0f}; starting cash {start_cash:,.0f} "
          f"({start_cash / reserve0:.2%} of reserve)")
    print(f"liabilities after year {BOND_MAX_MAT} (value {later:,.0f} at year {BOND_MAX_MAT}) are "
          f"funded by the {BOND_MAX_MAT}-year bonds and reinvested cash")
    pva = {r: d.price_bonds(bonds, c) + start_cash for r, c in curves.items()}
    pvl = {r: float(base_res[f"reserve_{r}"].to_numpy(dtype=float)[0]) for r in RATES}
    print(f"effective duration: assets {d.effective_duration(pva['down'], pva['up'], pva['base']):.2f}, "
          f"liabilities {d.effective_duration(pvl['down'], pvl['up'], pvl['base']):.2f}")

    scenarios = [(lapse, "with improvement", rate) for lapse in LAPSE_RUNS for rate in RATES] + \
                [("base", "no improvement", rate) for rate in RATES]
    detail, summary = [], []
    for lapse, mort, rate in scenarios:
        run = lapse if mort == "with improvement" else "base_no_improvement"
        cf, res = (base_cf, base_res) if run == "base" else load_run(run)
        test = cash_flow_test(bonds, start_cash, cf, res, curves[rate], rate)
        detail.append(test.assign(lapse=lapse, mortality=mort, rates=rate))
        df_h = d.discount_factors(curves[rate])[-1]
        surplus = test["surplus"].to_numpy(dtype=float)
        cash = test["cash"].to_numpy(dtype=float)
        i_min = int(surplus[:-1].argmin())                 # row number = year
        summary.append({"lapse": lapse, "mortality": mort, "rates": rate,
                        "surplus_t0": surplus[0],
                        "min_surplus": surplus[i_min], "min_surplus_year": i_min,
                        "years_borrowing": int((cash[1:] < 0).sum()),
                        "ending_surplus": cash[-1],
                        "pv_ending_surplus": cash[-1] * df_h,
                        "pv_ending_pct_of_reserve": cash[-1] * df_h / reserve0})
    pd.concat(detail, ignore_index=True).to_csv(f"{OUT_DIR}/surplus_by_year.csv", index=False)
    summ = pd.DataFrame(summary)
    summ.to_csv(f"{OUT_DIR}/cft_summary.csv", index=False)

    base_test = detail[LAPSE_RUNS.index("base") * len(RATES) + RATES.index("base")]
    print("\nBase lapse, base rates: assets vs reserve by year")
    print(base_test.loc[[0, 1, 2, 5, 10, 20, 29, 30, 40, HORIZON],
                        ["t", "bond_cash_flow", "net_liability_outflow", "cash", "assets", "reserve", "surplus"]]
          .round(0).to_string(index=False))
    print("\nCash flow test summary:")
    print(summ.round({"surplus_t0": 0, "min_surplus": 0, "ending_surplus": 0, "pv_ending_surplus": 0,
                      "pv_ending_pct_of_reserve": 4}).to_string(index=False))
    worst = summary[int(summ["pv_ending_surplus"].to_numpy(dtype=float).argmin())]
    print(f"\nworst PV of ending surplus: {worst['pv_ending_surplus']:,.0f} "
          f"({worst['pv_ending_pct_of_reserve']:.2%} of reserve) at lapse={worst['lapse']}, "
          f"rates={worst['rates']}, mortality={worst['mortality']}")
    print(f"ending surplus negative in {(summ['ending_surplus'] < 0).sum()} of {len(summ)} scenarios")
    print(f"\nwrote asset_portfolio.csv, asset_cf.csv, surplus_by_year.csv and cft_summary.csv to {OUT_DIR}/")


if __name__ == "__main__":
    main()