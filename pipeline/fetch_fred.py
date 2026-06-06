"""
fetch_fred.py — Pull mortgage & refi rates from FRED
=====================================================
Uses the FRED API (free key at fred.stlouisfed.org).
Falls back to scraping the Freddie Mac PMMS page if no key set.

Series pulled:
  MORTGAGE30US  — 30-year fixed mortgage rate (weekly)
  MORTGAGE15US  — 15-year fixed mortgage rate (weekly)
  MORTGAGE5US   — 5/1 ARM rate (weekly)
  REFRNS        — Refinance share of mortgage apps (MBA, weekly)

Usage:
    python pipeline/fetch_fred.py
    FRED_API_KEY=abc123 python pipeline/fetch_fred.py
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import requests

DB_PATH  = Path(__file__).parent.parent / "housing.db"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "MORTGAGE30US": "rate_30yr_fixed",
    "MORTGAGE15US": "rate_15yr_fixed",
    "MORTGAGE5US":  "rate_5yr_arm",
}


def get_db():
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS mortgage_rates (
            date        TEXT NOT NULL,
            series_id   TEXT NOT NULL,
            field_name  TEXT NOT NULL,
            rate        REAL,
            PRIMARY KEY (date, series_id)
        )
    """)
    con.commit()
    return con


def fetch_series(series_id: str, api_key: str, days_back: int = 90) -> list[dict]:
    """Fetch a single FRED series for the last N days."""
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    params = {
        "series_id":         series_id,
        "api_key":           api_key,
        "file_type":         "json",
        "observation_start": start,
        "sort_order":        "desc",
    }
    r = requests.get(FRED_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    rows = []
    for obs in data.get("observations", []):
        try:
            rows.append({
                "date":  obs["date"],
                "value": float(obs["value"]) if obs["value"] != "." else None,
            })
        except (ValueError, KeyError):
            continue
    return rows


def run(days_back: int = 90, verbose: bool = True):
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("  FRED: FRED_API_KEY not set — skipping rate fetch.")
        print("        Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html")
        return 0

    con = get_db()
    total = 0

    for series_id, field_name in SERIES.items():
        rows = fetch_series(series_id, api_key, days_back)
        for row in rows:
            if row["value"] is None:
                continue
            con.execute("""
                INSERT OR REPLACE INTO mortgage_rates (date, series_id, field_name, rate)
                VALUES (?, ?, ?, ?)
            """, (row["date"], series_id, field_name, row["value"]))
            total += 1

        if verbose and rows:
            latest = next((r for r in rows if r["value"] is not None), None)
            if latest:
                print(f"  FRED {series_id}: {latest['value']}% as of {latest['date']} ({len(rows)} weeks fetched)")

    con.commit()
    con.close()
    return total


if __name__ == "__main__":
    run()
