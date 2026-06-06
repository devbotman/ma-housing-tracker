"""
fetch_zillow_market.py — Zillow market activity datasets for MA
===============================================================
Fetches from Zillow Research public CSVs (confirmed working URLs):
  - For-sale inventory (invt_fs): county + state
  - New listings (new_listings): county + state
  - % sold above list (pct_sold_above_list): county + state
  - Median list price (mlp): county + state
  - Rent index ZORI (zori): county only

All datasets are wide-format (columns = date strings); melted to long.
Filters to MA. Stores in housing.db.

Column conventions in Zillow wide CSVs:
  County files: RegionID, SizeRank, RegionName ("Middlesex County"),
                RegionType, StateName ("MA"), State ("MA"), Metro,
                StateCodeFIPS, MunicipalCodeFIPS, then date cols
  State files:  RegionID, SizeRank, RegionName ("Massachusetts"),
                RegionType, StateName (NaN), then date cols
"""

import io
import sqlite3
from pathlib import Path

import pandas as pd
import requests

DB_PATH = Path(__file__).parent.parent / "housing.db"
HEADERS = {"User-Agent": "Mozilla/5.0 (research/data)"}
BASE    = "https://files.zillowstatic.com/research/public_csvs/"

# (table_name, url_path, geo_level, metric_col)
DATASETS = [
    # inventory
    ("market_invt_county",    "invt_fs/County_invt_fs_uc_sfrcondo_sm_month.csv",                  "county", "inventory"),
    ("market_invt_state",     "invt_fs/State_invt_fs_uc_sfrcondo_sm_month.csv",                   "state",  "inventory"),
    # new listings
    ("market_newlist_county", "new_listings/County_new_listings_uc_sfrcondo_sm_month.csv",        "county", "new_listings"),
    ("market_newlist_state",  "new_listings/State_new_listings_uc_sfrcondo_sm_month.csv",         "state",  "new_listings"),
    # % sold above list
    ("market_pct_above_county","pct_sold_above_list/County_pct_sold_above_list_uc_sfrcondo_sm_month.csv","county","pct_above_list"),
    ("market_pct_above_state", "pct_sold_above_list/State_pct_sold_above_list_uc_sfrcondo_sm_month.csv","state", "pct_above_list"),
    # median list price
    ("market_mlp_county",     "mlp/County_mlp_uc_sfrcondo_sm_month.csv",                         "county", "median_list_price"),
    ("market_mlp_state",      "mlp/State_mlp_uc_sfrcondo_sm_month.csv",                          "state",  "median_list_price"),
    # ZORI rent index (county only; state ZORI URL 404s)
    ("market_zori_county",    "zori/County_zori_uc_sfrcondomfr_sm_month.csv",                    "county", "rent_index"),
]


def get_db():
    con = sqlite3.connect(str(DB_PATH))
    for table, _, geo, metric in DATASETS:
        if geo == "county":
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    state    TEXT,
                    county   TEXT,
                    date     TEXT,
                    {metric} REAL,
                    PRIMARY KEY (state, county, date)
                )
            """)
        else:
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    state    TEXT,
                    date     TEXT,
                    {metric} REAL,
                    PRIMARY KEY (state, date)
                )
            """)
    con.commit()
    return con


def _date_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if str(c)[:4].isdigit() and "-" in str(c)]


def _fetch_county(con, table: str, url_path: str, metric: str, verbose: bool) -> int:
    """Fetch a county-level Zillow wide CSV, filter to MA, store."""
    r = requests.get(BASE + url_path, headers=HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))

    # Filter MA rows (StateName == "MA" for county files)
    state_col = next((c for c in df.columns if c in ("StateName", "State")), None)
    if state_col:
        ma_df = df[df[state_col] == "MA"].copy()
    else:
        ma_df = df  # can't filter, take all

    date_cols = _date_cols(df)
    county_col = next((c for c in df.columns if c in ("RegionName",)), "RegionName")

    rows = []
    for _, row in ma_df.iterrows():
        county = str(row[county_col]).replace(" County", "").strip()
        for dc in date_cols:
            val = row[dc]
            if pd.notna(val):
                try:
                    rows.append(("MA", county, dc, float(val)))
                except (ValueError, TypeError):
                    pass

    con.executemany(f"""
        INSERT OR REPLACE INTO {table} (state, county, date, {metric})
        VALUES (?, ?, ?, ?)
    """, rows)
    con.commit()

    if verbose:
        counties = ma_df[county_col].nunique()
        print(f"    {table}: {len(rows)} rows ({counties} MA counties)")
    return len(rows)


def _fetch_state(con, table: str, url_path: str, metric: str, verbose: bool) -> int:
    """Fetch a state-level Zillow wide CSV, filter to MA, store."""
    r = requests.get(BASE + url_path, headers=HEADERS, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))

    # State files use RegionName = full state name
    ma_df = df[df["RegionName"] == "Massachusetts"].copy()

    date_cols = _date_cols(df)
    rows = []
    for _, row in ma_df.iterrows():
        for dc in date_cols:
            val = row[dc]
            if pd.notna(val):
                try:
                    rows.append(("Massachusetts", dc, float(val)))
                except (ValueError, TypeError):
                    pass

    con.executemany(f"""
        INSERT OR REPLACE INTO {table} (state, date, {metric})
        VALUES (?, ?, ?)
    """, rows)
    con.commit()

    if verbose:
        print(f"    {table}: {len(rows)} MA rows")
    return len(rows)


def run(verbose: bool = True) -> int:
    if verbose:
        print("\nFetching Zillow market activity datasets...")

    con = get_db()
    total = 0
    for table, url_path, geo, metric in DATASETS:
        try:
            if geo == "county":
                n = _fetch_county(con, table, url_path, metric, verbose)
            else:
                n = _fetch_state(con, table, url_path, metric, verbose)
            total += n
        except Exception as e:
            if verbose:
                print(f"    {table}: failed — {e}")

    con.close()
    if verbose:
        print(f"  Zillow market: {total} total rows across {len(DATASETS)} datasets")
    return total


if __name__ == "__main__":
    run()
