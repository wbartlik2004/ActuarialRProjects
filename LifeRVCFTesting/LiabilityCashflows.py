"""
Liability cash flows, present values and reserves by year for the FIA census.

Each policy is projected from its census values (as of its last anniversary, treated as the
valuation date) under N_SCEN random index paths, and the results are averaged. Decrements
come from PolicyInforce.py (improved IAM mortality, static lapse).

Projection year t, for each policy and index scenario:
  during the year  index credit min(cap, max(floor, participation x return)) on the indexed
                   share, fixed rate on the rest; rider fee (fee x benefit base) taken from
                   the account value; benefit base rolls up (deferral years) then ratchets
  end of year      deaths pay max(premiums less withdrawals, account value);
                   surrenders pay max(AV x (1 - surrender charge), MGSV); a policy with no
                   account value left cannot surrender
  anniversary      at maturity_age the account value is paid out (rider policies whose
                   account is used up keep receiving withdrawals for life); planned premiums
                   come in; withdrawals go out (rider: benefit base x withdrawal %, paid by
                   the insurer once the account is empty; no rider: % of account value)

Net liability outflow = death benefits + surrender payouts + maturity payouts
                        + withdrawals - premiums.
Rider fees and surrender charges are not separate cash flows: they are the part of the
account value the insurer keeps.

Liability measures (each run, each rate curve):
  PVL               present value of net outflows + account value still in force at the horizon
  reserve_end       the same calculation done at each year end (value_by_year), i.e. the
                    liability still held at the end of year t
  av_in_force_end   account value owed to policies still in force (the "account value" view)
  csv_in_force_end  what they could take today if they surrendered
  CTE70             average PVL over the worst 30% of index scenarios

SIMPLIFICATIONS: caps, fees and the fixed rate stay at current levels in every scenario
(in practice caps reset with interest rates); lapse is static and the same with or without
the rider; no excess withdrawals; index scenarios are lognormal with assumed drift and
volatility, the same paths for every run.
"""
import os
import numpy as np
import pandas as pd

import CensusTables as ct
import Discounting as d
import PolicyInforce as pi

# ---------------- settings ----------------
OUT_DIR   = "LifeRVCFTesting/Projections"
HORIZON   = d.HORIZON          # 50 years, so nearly every policy dies, lapses or matures
N_SCEN    = 200                # index scenarios
SEED      = 2019
EQ_MU     = 0.055              # assumed expected annual PRICE return of the index
EQ_SIGMA  = 0.16               # assumed annual volatility
CHUNK     = 2000               # policies projected at a time (memory)
CTE_LEVEL = 0.70
# ------------------------------------------

ITEMS = ["premiums", "death_benefits", "surrender_payouts", "maturity_payouts",
         "withdrawals_from_av", "withdrawals_insurer_paid", "rider_fees",
         "surrender_charges_kept", "deaths", "surrenders", "maturities",
         "lives_end", "av_in_force_end", "csv_in_force_end", "benefit_base_in_force_end"]
OUTFLOWS = ["death_benefits", "surrender_payouts", "maturity_payouts",
            "withdrawals_from_av", "withdrawals_insurer_paid"]


def index_returns(n_scen=N_SCEN, horizon=HORIZON, seed=SEED):
    """Annual index price returns, lognormal: shape (n_scen, horizon)."""
    rng = np.random.default_rng(seed)
    mu_log = np.log1p(EQ_MU) - 0.5 * EQ_SIGMA ** 2
    return np.expm1(rng.normal(mu_log, EQ_SIGMA, size=(n_scen, horizon)))


def sc_matrix(census, horizon):
    """Surrender charge fraction by policy and projection year (0 after the schedule ends)."""
    sched = ct.load_surrender_charges()
    pol_year = census["current_duration"].to_numpy(dtype=int)[:, None] + np.arange(1, horizon + 1)[None, :]
    out = np.zeros(pol_year.shape)
    for prod, s in sched.items():
        m = (census["product"] == prod).to_numpy()
        lookup = np.zeros(max(int(s.index.max()), int(pol_year.max())) + 1)
        lookup[s.index.to_numpy(dtype=int)] = s.to_numpy()
        out[m] = lookup[pol_year[m]]
    return out


def project_chunk(c, q_d, q_w, sc, R):
    """Project policies c (P rows) under index returns R (S x T).
    Returns {item: array S x T}, summed over the policies."""
    P, (S, T) = len(c), R.shape
    col = lambda name, dt=float: c[name].to_numpy(dtype=dt)[:, None]     # P x 1

    rider = c["has_income_rider"].to_numpy(dtype=bool)[:, None]
    attained, maturity = col("attained_age", int), col("maturity_age", int)
    wd_age = col("wd_start_age")
    takes_wd = ~np.isnan(wd_age)
    wd_age = np.nan_to_num(wd_age, nan=999.0)
    cap, floor, part = col("cap_rate"), col("floor_rate"), col("participation_rate")
    alloc, fixed = col("index_alloc_pct"), col("fixed_rate")
    fee_pct, rollup = col("rider_fee_pct"), col("rollup_rate")
    roll_left, wd_pct = col("rollup_years_left", int), col("wd_pct")
    nr_pct = col("nonrider_wd_pct")
    planned = col("planned_premium")
    prem_years, dur0 = col("premium_years", int), col("current_duration", int)
    mg_pct, mg_rate = col("mgsv_pct"), col("mgsv_rate")

    ones = np.ones((1, S))
    av = col("account_value") * ones
    bb = col("benefit_base") * ones
    prem_basis = np.maximum(col("cumulative_premiums") - col("cumulative_withdrawals"), 0.0) * ones
    mgsv = col("mgsv") * ones
    live = np.ones((P, S))
    started = c["withdrawals_started"].to_numpy(dtype=bool)[:, None]

    out = {k: np.zeros((S, T)) for k in ITEMS}
    add = lambda k, t, x: out[k].__setitem__((slice(None), t), out[k][:, t] + x.sum(axis=0))

    for t in range(T):
        # ---- during the year ----
        credit = np.minimum(cap, np.maximum(floor, part * R[:, t][None, :]))
        av = av * (alloc * (1 + credit) + (1 - alloc) * (1 + fixed))
        mgsv = mgsv * (1 + mg_rate)
        fee = np.where(rider, np.minimum(fee_pct * bb, av), 0.0)
        av = av - fee
        add("rider_fees", t, live * fee)
        roll = rider & ~started & (t + 1 <= roll_left)
        bb = np.where(roll, bb * (1 + rollup), bb)
        bb = np.where(rider, np.maximum(bb, av), bb)

        # ---- end of year: deaths, then surrenders ----
        qd = q_d[:, t:t + 1]
        qw = q_w[:, t:t + 1] * (av > 0)
        deaths = live * qd
        surr = live * (1 - qd) * qw
        csv = np.where(av > 0, np.maximum(av * (1 - sc[:, t:t + 1]), mgsv), 0.0)
        add("deaths", t, deaths)
        add("death_benefits", t, deaths * np.maximum(prem_basis, av))
        add("surrenders", t, surr)
        add("surrender_payouts", t, surr * csv)
        add("surrender_charges_kept", t, surr * np.maximum(av - csv, 0.0))
        live = live - deaths - surr

        # ---- anniversary ----
        age_k = attained + t + 1
        mature = (age_k >= maturity) & (av > 0)
        add("maturities", t, live * mature)
        add("maturity_payouts", t, live * mature * np.maximum(av, mgsv))
        live = np.where(mature, 0.0, live)

        wd_now = takes_wd & (age_k >= wd_age)
        prem = np.where((dur0 + t + 2 <= prem_years) & ~wd_now, planned, 0.0) * ones
        av, prem_basis, mgsv = av + prem, prem_basis + prem, mgsv + mg_pct * prem
        bb = np.where(rider, bb + prem, bb)
        add("premiums", t, live * prem)

        started = started | wd_now
        wd = np.where(wd_now, np.where(rider, bb * wd_pct, nr_pct * av), 0.0)
        from_av = np.minimum(wd, av)
        av = av - from_av
        add("withdrawals_from_av", t, live * from_av)
        add("withdrawals_insurer_paid", t, live * (wd - from_av))
        prem_basis = np.maximum(prem_basis - wd, 0.0)
        mgsv = np.maximum(mgsv - wd, 0.0)

        next_sc = sc[:, min(t + 1, T - 1)][:, None]
        add("lives_end", t, live)
        add("av_in_force_end", t, live * av)
        add("csv_in_force_end", t, live * np.where(av > 0, np.maximum(av * (1 - next_sc), mgsv), 0.0))
        add("benefit_base_in_force_end", t, live * np.where(rider, bb, 0.0))
    return out


def project_run(census, a, R, lapse_scenario="base", improve=True):
    """All policies, one assumption set. Returns {item: S x T} summed over policies."""
    T = R.shape[1]
    total = {k: np.zeros(R.shape) for k in ITEMS}
    for i in range(0, len(census), CHUNK):
        c = census.iloc[i:i + CHUNK]
        res = project_chunk(c, pi.mortality_matrix(c, a, T, improve),
                            pi.lapse_matrix(c, a, T, lapse_scenario), sc_matrix(c, T), R)
        for k in ITEMS:
            total[k] += res[k]
    total["net_outflow"] = sum(total[k] for k in OUTFLOWS) - total["premiums"]
    return total


def summarize(run, sims, curves):
    """Mean cash flows by year, reserves by year on each curve, and PV statistics."""
    T = sims["net_outflow"].shape[1]
    t = np.arange(1, T + 1)
    cf = pd.DataFrame({"t": t, "calendar_year": pi.VAL_YEAR + t})
    for k in ITEMS + ["net_outflow"]:
        cf[k] = sims[k].mean(axis=0)

    terminal_s = sims["av_in_force_end"][:, -1]          # account value still owed at H, per scenario
    reserves = pd.DataFrame({"t": np.arange(0, T + 1)})
    rows = []
    for rate, curve in curves.items():
        res = d.value_by_year(cf["net_outflow"].to_numpy(), curve, terminal_s.mean())
        reserves[f"reserve_{rate}"] = res
        df = d.discount_factors(curve)
        pv_s = (sims["net_outflow"] * df).sum(axis=1) + terminal_s * df[-1]
        worst = np.sort(pv_s)[int(np.floor(CTE_LEVEL * len(pv_s))):]
        rows.append({"run": run, "rates": rate, "PVL": res[0], "PVL_CTE70": worst.mean(),
                     "PVL_min": pv_s.min(), "PVL_max": pv_s.max(),
                     "PV_insurer_paid_wd": d.pv(cf["withdrawals_insurer_paid"], curve),
                     "PV_premiums": d.pv(cf["premiums"], curve)})
    reserves["av_in_force_end"] = np.concatenate([[np.nan], cf["av_in_force_end"].to_numpy()])
    reserves["csv_in_force_end"] = np.concatenate([[np.nan], cf["csv_in_force_end"].to_numpy()])
    reserves["reserve_to_av"] = reserves["reserve_base"] / reserves["av_in_force_end"]
    return cf, reserves, rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pd.set_option("display.width", 200)
    census = ct.load_census()
    a = pi.load_assumptions()
    R = index_returns()
    curves = d.build_curves(HORIZON)
    av0 = census["account_value"].sum()
    print(f"{len(census):,} policies, account value {av0:,.0f}; {N_SCEN} index scenarios, "
          f"{HORIZON}-year horizon; mortality 2012 IAM {a.basis} + {a.improvement}")
    credit = np.minimum(census["cap_rate"].iloc[0], np.maximum(census["floor_rate"].iloc[0], R))
    print(f"index credit across scenarios: mean {credit.mean():.2%}, "
          f"capped {np.mean(credit >= census['cap_rate'].iloc[0]):.0%} of years, floored {np.mean(R <= 0):.0%}")

    runs = {name: dict(lapse_scenario=name) for name in a.scenarios}
    runs["base_no_improvement"] = dict(lapse_scenario="base", improve=False)
    all_rows, summary = [], []
    for name, kw in runs.items():
        sims = project_run(census, a, R, **kw)
        cf, reserves, rows = summarize(name, sims, curves)
        cf.to_csv(f"{OUT_DIR}/liability_cf_{name}.csv", index=False)
        reserves.to_csv(f"{OUT_DIR}/reserves_{name}.csv", index=False)
        all_rows += rows
        summary.append({"run": name, **{k: cf[k].sum() for k in OUTFLOWS + ["premiums", "rider_fees"]},
                        "lives_left_at_end": cf["lives_end"].iloc[-1],
                        "av_left_at_end": cf["av_in_force_end"].iloc[-1]})
        if name == "base":
            print("\nBase run, expected cash flows (first 8 years):")
            print(cf[["t", "premiums", "death_benefits", "surrender_payouts", "withdrawals_from_av",
                      "withdrawals_insurer_paid", "net_outflow", "av_in_force_end"]].head(8).round(0).to_string(index=False))
            print("\nBase run, liability at each year end (reserve on the base curve vs account value):")
            print(reserves.loc[[0, 1, 2, 5, 10, 20, 30, 40, HORIZON],
                               ["t", "reserve_base", "av_in_force_end", "csv_in_force_end", "reserve_to_av"]]
                  .round(3).to_string(index=False))

    results = pd.DataFrame(all_rows)
    results.to_csv(f"{OUT_DIR}/liability_pv_results.csv", index=False)
    pd.DataFrame(summary).to_csv(f"{OUT_DIR}/liability_cf_summary.csv", index=False)

    grid = results[results["run"] != "base_no_improvement"].pivot(index="run", columns="rates", values="PVL")
    print("\nPV of liabilities, lapse x rates:")
    print(grid.loc[["low", "base", "high"], ["down", "base", "up"]].round(0).to_string())
    # plain dicts keyed by (run, rates), so every value is a float
    b = {(r["run"], r["rates"]): r for r in all_rows}
    base, noimp = b[("base", "base")], b[("base_no_improvement", "base")]
    print(f"\nbase / base: PVL {base['PVL']:,.0f} = {base['PVL'] / av0:.3f} x account value; "
          f"CTE70 {base['PVL_CTE70']:,.0f}; range {base['PVL_min']:,.0f} to {base['PVL_max']:,.0f}")
    print(f"PV of insurer-paid rider withdrawals {base['PV_insurer_paid_wd']:,.0f}; "
          f"mortality improvement changes PVL by {base['PVL'] / noimp['PVL'] - 1:+.2%}")
    dur = d.effective_duration(b[("base", "down")]["PVL"], b[("base", "up")]["PVL"], base["PVL"])
    print(f"effective duration of liabilities (base lapse): {dur:.2f} years")
    left = next(row for row in summary if row["run"] == "base")
    print(f"still in force after {HORIZON} years: {left['lives_left_at_end']:.1f} expected policies, "
          f"account value {left['av_left_at_end']:,.0f} (counted as a terminal liability)")
    print(f"\nwrote liability_cf_<run>.csv, reserves_<run>.csv and liability_pv_results.csv to {OUT_DIR}/")


if __name__ == "__main__":
    main()