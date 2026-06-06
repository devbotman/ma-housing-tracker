"""
fetch_ma_tax.py — MA property tax rates by town
================================================
Source: https://dls-gw.dor.state.ma.us/reports/rdPage.aspx
        ?rdReport=PropertyTaxInformation.taxratesbyclass.taxratesbyclass_main

Scrapes the MA DOR Logi report server (paginated, session-based).
Falls back to local file in data/raw/ma_tax_rates*.xlsx if scraping fails.

Stores residential tax rate (per $1,000 assessed value) per town per year.
Calculates YoY change.
"""

import io
import re
import sqlite3
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH  = Path(__file__).parent.parent / "housing.db"
RAW_DIR  = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL  = "https://dls-gw.dor.state.ma.us/reports/"
START_URL = BASE_URL + "rdPage.aspx?rdReport=PropertyTaxInformation.taxratesbyclass.taxratesbyclass&rdSubReport=True&rdResizeFrame=True"
HEADERS   = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer":    BASE_URL + "rdPage.aspx?rdReport=PropertyTaxInformation.taxratesbyclass.taxratesbyclass_main",
}


def get_db():
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS ma_property_tax (
            town             TEXT NOT NULL,
            year             INTEGER NOT NULL,
            residential_rate REAL,
            yoy_change       REAL,
            PRIMARY KEY (town, year)
        )
    """)
    con.commit()
    return con


def _parse_page(soup) -> list[dict]:
    """Extract tax rate rows from a parsed page."""
    rows = []
    for table in soup.find_all("table"):
        tds = table.find_all("td")
        text = " ".join(td.get_text(strip=True) for td in tds[:5])
        if re.search(r"\d{3}.*202[2-9].*\d+\.\d+", text):
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if (len(cells) >= 4
                        and re.match(r"^\d{3}$", cells[0])
                        and re.match(r"20\d{2}", cells[2])):
                    try:
                        rows.append({
                            "town":             cells[1],
                            "year":             int(cells[2]),
                            "residential_rate": float(cells[3]),
                        })
                    except (ValueError, IndexError):
                        pass
            break
    return rows


def _scrape_dor(verbose: bool) -> list[dict]:
    """Paginate through the MA DOR Logi report and collect all rows."""
    session = requests.Session()
    if verbose:
        print(f"  MA Tax: fetching from DOR report server...")

    r = session.get(START_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Extract session cache key and total page count
    next_link = next(
        (a.get("href", "") for a in soup.find_all("a")
         if "SubmitForm" in a.get("href", "") and "PageNr=2" in a.get("href", "")),
        ""
    )
    cache_match = re.search(r"rdDataCache=(\d+)", next_link)
    if not cache_match:
        raise ValueError("Could not find rdDataCache session key")
    cache_key = cache_match.group(1)

    pages_match = re.search(r"Page\s*of\s*(\d+)", soup.get_text())
    total_pages = int(pages_match.group(1)) if pages_match else 36

    if verbose:
        print(f"  MA Tax: {total_pages} pages, cache={cache_key}")

    all_rows = _parse_page(soup)

    for page in range(2, total_pages + 1):
        page_url = (
            BASE_URL +
            f"rdPage.aspx?rdReport=PropertyTaxInformation.taxratesbyclass.taxratesbyclass"
            f"&tbl_taxratesbyclass-PageNr={page}&rdDataCache={cache_key}"
            f"&rdShowModes=&rdSort=&rdNewPageNr=True1&rdRequestForwarding=Form"
        )
        r = session.post(page_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        rows = _parse_page(BeautifulSoup(r.text, "html.parser"))
        all_rows.extend(rows)
        time.sleep(0.25)

    if verbose:
        print(f"  MA Tax: scraped {len(all_rows)} rows across {total_pages} pages")
    return all_rows


def _load_local_file(verbose: bool) -> list[dict]:
    """Fallback: read a manually downloaded Excel/CSV from data/raw/."""
    import pandas as pd
    candidates = sorted(RAW_DIR.glob("ma_tax*.*"), reverse=True)
    for path in candidates:
        year_match = re.search(r"(20\d{2})", path.stem)
        year = int(year_match.group(1)) if year_match else 2024
        if verbose:
            print(f"  MA Tax: reading local file {path.name} (year={year})...")
        try:
            df = pd.read_csv(path) if path.suffix == ".csv" else pd.read_excel(path)
            df.columns = [str(c).strip().lower() for c in df.columns]
            town_col = next((c for c in df.columns if "town" in c or "municipality" in c), None)
            rate_col = next((c for c in df.columns if "residential" in c and "rate" in c), None)
            if not town_col or not rate_col:
                continue
            rows = []
            for _, row in df.iterrows():
                town = str(row[town_col]).strip().title()
                try:
                    rate = float(str(row[rate_col]).replace(",", "").replace("$", ""))
                except (ValueError, TypeError):
                    continue
                if town and rate > 0:
                    rows.append({"town": town, "year": year, "residential_rate": rate})
            if rows:
                if verbose:
                    print(f"  MA Tax: parsed {len(rows)} towns from {path.name}")
                return rows
        except Exception as e:
            if verbose:
                print(f"    Could not parse {path.name}: {e}")
    return []


def fetch_tax_rates(verbose: bool = True) -> list[dict]:
    """Fetch MA town tax rates — live scrape first, local file fallback."""
    try:
        return _scrape_dor(verbose)
    except Exception as e:
        if verbose:
            print(f"  MA Tax: live scrape failed ({e}), trying local file...")
        return _load_local_file(verbose)


def run(verbose: bool = True):
    rows = fetch_tax_rates(verbose)
    if not rows:
        if verbose:
            print("  MA Tax: no data — skipping")
        return 0

    con = get_db()
    for row in rows:
        con.execute("""
            INSERT OR REPLACE INTO ma_property_tax (town, year, residential_rate)
            VALUES (?, ?, ?)
        """, (row["town"], row["year"], row["residential_rate"]))

    con.execute("""
        UPDATE ma_property_tax
        SET yoy_change = residential_rate - (
            SELECT prev.residential_rate FROM ma_property_tax prev
            WHERE prev.town = ma_property_tax.town AND prev.year = ma_property_tax.year - 1
        )
        WHERE EXISTS (
            SELECT 1 FROM ma_property_tax prev
            WHERE prev.town = ma_property_tax.town AND prev.year = ma_property_tax.year - 1
        )
    """)
    con.commit()
    con.close()
    if verbose:
        print(f"  MA Tax: saved {len(rows)} town-year records")
    return len(rows)


if __name__ == "__main__":
    run()
