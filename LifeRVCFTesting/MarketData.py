# pip install yfinance pandas
"""
Download S&P 500 price history for the FIA crediting and save it as
LifeRVCFTesting/Market/sp500.csv with columns: date, close.

Uses the PRICE index (^GSPC close), not total return: FIA index credits are normally
based on the price return, without dividends. Tries Yahoo Finance first (yfinance), then
Stooq as a backup. Run this on your own machine; it needs internet access.
"""
import os
import pandas as pd

OUT_CSV = "LifeRVCFTesting/Market/sp500.csv"
START   = "1990-01-01"          # must be on or before the census's earliest issue date
END     = None                  # None = up to today

# calendar-year price returns to check the download against
KNOWN_RETURNS = {2008: -0.3849, 2018: -0.0624, 2019: 0.2888}


def from_yahoo():
    import yfinance as yf
    df = yf.download("^GSPC", start=START, end=END, auto_adjust=False, progress=False)
    if df is None or df.empty:                 # yfinance can return None on failure
        raise RuntimeError("Yahoo returned no data")
    # "Close" is one column, or one column per ticker in newer yfinance: take the first either way
    values = df["Close"].to_numpy().reshape(len(df), -1)[:, 0]
    dates = pd.DatetimeIndex(df.index)
    if dates.tz is not None:
        dates = dates.tz_localize(None)        # drop the time zone, keep the local date
    return pd.DataFrame({"date": dates.normalize(), "close": values})


def from_stooq():
    df = pd.read_csv("https://stooq.com/q/d/l/?s=^spx&i=d", parse_dates=["Date"])
    df = df[df["Date"] >= START]
    if END:
        df = df[df["Date"] <= END]
    return pd.DataFrame({"date": df["Date"], "close": df["Close"]})


def main():
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    data = None
    for name, fn in (("Yahoo Finance", from_yahoo), ("Stooq", from_stooq)):
        try:
            data = fn()
            print(f"downloaded from {name}")
            break
        except Exception as e:
            print(f"{name} failed: {e}")
    if data is None:
        raise SystemExit("no source worked; download ^GSPC history manually and save date, close")

    data = data.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
    data.to_csv(OUT_CSV, index=False)
    print(f"{len(data):,} rows, {data['date'].min().date()} to {data['date'].max().date()} -> {OUT_CSV}")

    # checks
    gaps = data["date"].diff().dt.days.fillna(0).to_numpy()
    if gaps.max() > 7:
        i = int(gaps.argmax())
        print(f"WARNING: largest gap between dates is {int(gaps[i])} days "
              f"(ending {data['date'].iloc[i].date()})")
    year_end = data.set_index("date")["close"].resample("YE").last()
    yearly = year_end.pct_change()
    yearly.index = pd.DatetimeIndex(yearly.index).year
    for y, expected in KNOWN_RETURNS.items():
        if y in yearly.index:
            ok = abs(yearly[y] - expected) < 0.002
            print(f"  {y}: {yearly[y]:+.2%} (published {expected:+.2%}) {'ok' if ok else 'CHECK'}")


if __name__ == "__main__":
    main()