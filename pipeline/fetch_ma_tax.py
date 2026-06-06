"""
fetch_ma_tax.py — MA property tax rates by town
================================================
Source: https://www.mass.gov/lists/local-tax-rates-by-town

mass.gov blocks automated downloads (403). Best approach:
  1. Go to the URL above in your browser
  2. Download the most recent Excel file
  3. Save it to data/raw/ma_tax_rates.xlsx (or .csv)
  4. Run the pipeline — it will read the local file

Stores residential tax rate (per $1,000 assessed value) per town per year.
Calculates YoY change.
"""

import io
import re
import sqlite3
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH  = Path(__file__).parent.parent / "housing.db"
RAW_DIR  = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

MA_DOR_URL = "https://www.mass.gov/lists/local-tax-rates-by-town"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.mass.gov/",
}


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


def _parse_df(df, year: int, verbose: bool) -> list[dict]:
    """Parse a tax rate DataFrame into row dicts."""
    df.columns = [str(c).strip().lower() for c in df.columns]
    town_col = next((c for c in df.columns if "town" in c or "municipality" in c or "city" in c), None)
    rate_col = next((c for c in df.columns if "residential" in c and "rate" in c), None)

    if not town_col or not rate_col:
        if verbose:
            print(f"    Could not find columns. Cols: {list(df.columns)[:10]}")
        return []

    rows = []
    for _, row in df.iterrows():
        town = str(row[town_col]).strip().title()
        try:
            rate = float(str(row[rate_col]).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            continue
        if town and rate > 0:
            rows.append({"town": town, "year": year, "residential_rate": rate})
    return rows


def _try_local_files(verbose: bool) -> list[dict]:
    """Check data/raw/ for manually downloaded MA tax files."""
    import pandas as pd
    candidates = sorted(RAW_DIR.glob("ma_tax*.*"), reverse=True)
    for path in candidates:
        year_match = re.search(r"(20\d{2})", path.stem)
        year = int(year_match.group(1)) if year_match else 2024
        if verbose:
            print(f"  MA Tax: reading local file {path.name} (year={year})...")
        try:
            df = pd.read_csv(path) if path.suffix == ".csv" else pd.read_excel(path)
            rows = _parse_df(df, year, verbose)
            if rows:
                if verbose:
                    print(f"  MA Tax: parsed {len(rows)} towns from local file")
                return rows
        except Exception as e:
            if verbose:
                print(f"    Could not parse {path.name}: {e}")
    return []


def fetch_tax_rates(verbose: bool = True) -> list[dict]:
    """
    Try to fetch MA tax rate data:
      1. Check data/raw/ for locally saved files first
      2. Try scraping mass.gov (often blocked)
    """
    import pandas as pd

    # 1. Local file first
    rows = _try_local_files(verbose)
    if rows:
        return rows

    # 2. Try live scrape
    if verbose:
        print(f"  MA Tax: no local file found, trying mass.gov scrape...")
    try:
        r = requests.get(MA_DOR_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r"\.(xlsx|csv|xls)", re.I))
        if not links:
            raise ValueError("No file links found on page")

        for link in links[:3]:
            href = link.get("href", "")
            year_match = re.search(r"(20\d{2})", href)
            year = int(year_match.group(1)) if year_match else 2024
            file_url = href if href.startswith("http") else f"https://www.mass.gov{href}"
            if verbose:
                print(f"  MA Tax: downloading {year} rates from {file_url[:60]}...")
            try:
                file_r = requests.get(file_url, headers=HEADERS, timeout=30)
                file_r.raise_for_status()
                df = pd.read_csv(io.BytesIO(file_r.content)) if file_url.endswith(".csv") else pd.read_excel(io.BytesIO(file_r.content))
                rows = _parse_df(df, year, verbose)
                if rows:
                    if verbose:
                        print(f"  MA Tax: parsed {len(rows)} towns for {year}")
                    return rows
            except Exception as e:
                if verbose:
                    print(f"    Could not parse {year} file: {e}")

    except Exception as e:
        if verbose:
            print(f"  MA Tax: scrape failed ({e})")
            print(f"  MA Tax: To add tax data manually:")
            print(f"    1. Download Excel from: {MA_DOR_URL}")
            print(f"    2. Save to: {RAW_DIR / 'ma_tax_rates_2025.xlsx'}")
            print(f"    3. Re-run pipeline")

    return []


def run(verbose: bool = True):
    rows = fetch_tax_rates(verbose)
    if not rows:
        return 0

    con = get_db()
    for row in rows:
        con.execute("""
            INSERT OR REPLACE INTO ma_property_tax (town, year, residential_rate)
            VALUES (?, ?, ?)
        """, (row["town"], row["year"], row["residential_rate"]))

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
