"""
fetch_zillow.py — Download and load Zillow ZHVI data
=====================================================
Zillow publishes free CSV files at https://www.zillow.com/research/data/

We pull:
  - ZHVI All Homes (SFR+Condo) by State   — national median prices
  - ZHVI All Homes by County               — county-level prices
  - ZHVI All Homes by ZIP                  — zip-level (for MA towns)

All files are monthly, updated ~mid-month for prior month.
"""

import io
import sqlite3
from pathlib import Path

import pandas as pd
import requests

DB_PATH  = Path(__file__).parent.parent / "housing.db"
RAW_DIR  = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Zillow Research CSV endpoints
ZILLOW_URLS = {
    "state":  "https://files.zillowstatic.com/research/public_csvs/zhvi/State_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "county": "https://files.zillowstatic.com/research/public_csvs/zhvi/County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zip":    "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (research/data download)"}


def get_db():
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS zhvi_state (
            state       TEXT NOT NULL,
            date        TEXT NOT NULL,
            median_price INTEGER,
            yoy_pct     REAL,
            PRIMARY KEY (state, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS zhvi_county (
            state       TEXT,
            county      TEXT,
            fips        TEXT,
            date        TEXT NOT NULL,
            median_price INTEGER,
            yoy_pct     REAL,
            PRIMARY KEY (fips, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS zhvi_zip (
            state       TEXT,
            county      TEXT,
            city        TEXT,
            zip         TEXT,
            date        TEXT NOT NULL,
            median_price INTEGER,
            yoy_pct     REAL,
            PRIMARY KEY (zip, date)
        )
    """)
    con.commit()
    return con


def _download_csv(url: str, cache_name: str) -> pd.DataFrame:
    """Download CSV with local cache."""
    cache_path = RAW_DIR / cache_name
    print(f"  Zillow: downloading {cache_name}...")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    cache_path.write_bytes(r.content)
    return pd.read_csv(io.BytesIO(r.content))


def _melt_zhvi(df: pd.DataFrame, id_cols: list[str]) -> pd.DataFrame:
    """Melt wide ZHVI format (date columns) to long format."""
    date_cols = [c for c in df.columns if c.startswith("20")]
    melted = df[id_cols + date_cols].melt(
        id_vars=id_cols, var_name="date", value_name="median_price"
    )
    melted["median_price"] = pd.to_numeric(melted["median_price"], errors="coerce")
    melted = melted.dropna(subset=["median_price"])
    melted["median_price"] = melted["median_price"].astype(int)
    return melted.sort_values("date")


def _add_yoy(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Add year-over-year % change column."""
    df = df.sort_values(group_cols + ["date"])
    df["yoy_pct"] = df.groupby(group_cols)["median_price"].pct_change(12) * 100
    df["yoy_pct"] = df["yoy_pct"].round(2)
    return df


def load_states(con: sqlite3.Connection, verbose: bool = True) -> int:
    df_raw = _download_csv(ZILLOW_URLS["state"], "zhvi_state.csv")
    df = _melt_zhvi(df_raw, ["RegionName"])
    df = df.rename(columns={"RegionName": "state"})
    df = _add_yoy(df, ["state"])
    # Keep last 24 months only
    df = df[df["date"] >= df["date"].max()[:4] + "-01-01"]
    rows = 0
    for _, row in df.iterrows():
        con.execute("""
            INSERT OR REPLACE INTO zhvi_state (state, date, median_price, yoy_pct)
            VALUES (?, ?, ?, ?)
        """, (row["state"], row["date"], row["median_price"], row.get("yoy_pct")))
        rows += 1
    con.commit()
    if verbose:
        latest = df[df["date"] == df["date"].max()]
        us_row = latest[latest["state"] == "Massachusetts"]
        if not us_row.empty:
            r = us_row.iloc[0]
            print(f"  Zillow states: loaded {rows} rows | MA median: ${r['median_price']:,} ({r['yoy_pct']:+.1f}% YoY)")
    return rows


def load_counties(con: sqlite3.Connection, ma_only: bool = False, verbose: bool = True) -> int:
    df_raw = _download_csv(ZILLOW_URLS["county"], "zhvi_county.csv")
    if ma_only:
        df_raw = df_raw[df_raw["State"] == "MA"]
    id_cols = ["State", "RegionName", "RegionID"]
    df = _melt_zhvi(df_raw, id_cols)
    df = df.rename(columns={"State": "state", "RegionName": "county", "RegionID": "fips"})
    df = _add_yoy(df, ["fips"])
    df = df[df["date"] >= df["date"].max()[:4] + "-01-01"]
    rows = 0
    for _, row in df.iterrows():
        con.execute("""
            INSERT OR REPLACE INTO zhvi_county (state, county, fips, date, median_price, yoy_pct)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (row["state"], row["county"], str(row["fips"]), row["date"],
              row["median_price"], row.get("yoy_pct")))
        rows += 1
    con.commit()
    if verbose:
        print(f"  Zillow counties: loaded {rows} rows ({'MA only' if ma_only else 'all states'})")
    return rows


def load_zips(con: sqlite3.Connection, states: list[str] = None, verbose: bool = True) -> int:
    """Load ZIP-level data, optionally filtered to specific states."""
    df_raw = _download_csv(ZILLOW_URLS["zip"], "zhvi_zip.csv")
    if states:
        df_raw = df_raw[df_raw["State"].isin(states)]
    id_cols = ["State", "CountyName", "City", "RegionName"]
    df = _melt_zhvi(df_raw, id_cols)
    df = df.rename(columns={"State": "state", "CountyName": "county",
                             "City": "city", "RegionName": "zip"})
    df = _add_yoy(df, ["zip"])
    df = df[df["date"] >= df["date"].max()[:4] + "-01-01"]
    rows = 0
    for _, row in df.iterrows():
        con.execute("""
            INSERT OR REPLACE INTO zhvi_zip (state, county, city, zip, date, median_price, yoy_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (row["state"], row["county"], row["city"], str(row["zip"]),
              row["date"], row["median_price"], row.get("yoy_pct")))
        rows += 1
    con.commit()
    if verbose:
        print(f"  Zillow ZIPs: loaded {rows} rows")
    return rows


def run(ma_only: bool = True, verbose: bool = True):
    """Main entry point."""
    con = get_db()
    load_states(con, verbose)
    load_counties(con, ma_only=ma_only, verbose=verbose)
    load_zips(con, states=["MA"] if ma_only else None, verbose=verbose)
    con.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-states", action="store_true", help="Load all states (large)")
    args = parser.parse_args()
    run(ma_only=not args.all_states)
