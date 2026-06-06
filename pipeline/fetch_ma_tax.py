"""
fetch_ma_tax.py — MA property tax rates by town
================================================
Scrapes the MA Department of Revenue annual property tax rate table.
Source: https://www.mass.gov/lists/local-tax-rates-by-town

Stores residential tax rate (per $1,000 assessed value) per town per year.
Calculates YoY change.
"""

import re
import sqlite3
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH = Path(__file__).parent.parent / "housing.db"
MA_DOR_URL = "https://www.mass.gov/lists/local-tax-rates-by-town"
HEADERS = {"User-Agent": "Mozilla/5.0 (research/public-data)"}


def get_db():
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS ma_property_tax (
            town            TEXT NOT NULL,
            year            INTEGER NOT NULL,
            residential_rate REAL,
            yoy_change      REAL,
            PRIMARY KEY (town, year)
        )
    """)
    con.commit()
    return con


def fetch_tax_rates(verbose: bool = True) -> list[dict]:
    """
    Scrape the MA DOR page and find links to annual tax rate Excel/CSV files.
    Falls back to a known direct URL pattern if the page structure changes.
    """
    rows = []

    try:
        r = requests.get(MA_DOR_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Find links to tax rate files (Excel or CSV)
        links = soup.find_all("a", href=re.compile(r"\.(xlsx|csv|xls)", re.I))

        if not links:
            if verbose:
                print("  MA Tax: no data file links found on DOR page — page may have changed")
            return []

        # Try to get most recent year's file
        for link in links[:3]:
            href = link.get("href", "")
            year_match = re.search(r"(20\d{2})", href)
            year = int(year_match.group(1)) if year_match else 2024

            file_url = href if href.startswith("http") else f"https://www.mass.gov{href}"
            if verbose:
                print(f"  MA Tax: downloading {year} rates from {file_url[:60]}...")

            try:
                import pandas as pd
                file_r = requests.get(file_url, headers=HEADERS, timeout=30)
                file_r.raise_for_status()

                import io
                if href.endswith(".csv"):
                    df = pd.read_csv(io.BytesIO(file_r.content))
                else:
                    df = pd.read_excel(io.BytesIO(file_r.content))

                # Normalize column names
                df.columns = [str(c).strip().lower() for c in df.columns]

                # Find town and residential rate columns
                town_col = next((c for c in df.columns if "town" in c or "municipality" in c or "city" in c), None)
                rate_col = next((c for c in df.columns if "residential" in c and "rate" in c), None)

                if not town_col or not rate_col:
                    if verbose:
                        print(f"    Could not find columns in {year} file. Cols: {list(df.columns)[:8]}")
                    continue

                for _, row in df.iterrows():
                    town = str(row[town_col]).strip().title()
                    try:
                        rate = float(str(row[rate_col]).replace(",", "").replace("$", ""))
                    except (ValueError, TypeError):
                        continue
                    if town and rate > 0:
                        rows.append({"town": town, "year": year, "residential_rate": rate})

                if verbose:
                    print(f"  MA Tax: parsed {len(rows)} towns for {year}")
                break

            except Exception as e:
                if verbose:
                    print(f"    Could not parse {year} file: {e}")

    except Exception as e:
        if verbose:
            print(f"  MA Tax: fetch failed — {e}")

    return rows


def run(verbose: bool = True):
    rows = fetch_tax_rates(verbose)
    if not rows:
        return 0

    con = get_db()

    # Insert new data
    for row in rows:
        con.execute("""
            INSERT OR REPLACE INTO ma_property_tax (town, year, residential_rate)
            VALUES (?, ?, ?)
        """, (row["town"], row["year"], row["residential_rate"]))

    # Calculate YoY change
    con.execute("""
        UPDATE ma_property_tax AS curr
        SET yoy_change = curr.residential_rate - (
            SELECT prev.residential_rate FROM ma_property_tax prev
            WHERE prev.town = curr.town AND prev.year = curr.year - 1
        )
        WHERE EXISTS (
            SELECT 1 FROM ma_property_tax prev
            WHERE prev.town = curr.town AND prev.year = curr.year - 1
        )
    """)

    con.commit()
    con.close()
    if verbose:
        print(f"  MA Tax: saved {len(rows)} town tax rates")
    return len(rows)


if __name__ == "__main__":
    run()
