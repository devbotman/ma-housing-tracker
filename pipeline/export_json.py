"""
export_json.py — Export housing.db data to static JSON for GitHub Pages dashboard
==================================================================================
Reads from housing.db and writes docs/data/*.json files.
Run after each pipeline refresh to update the public dashboard.

Usage:
    python pipeline/export_json.py
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH   = Path(__file__).parent.parent / "housing.db"
OUT_DIR   = Path(__file__).parent.parent / "docs" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"housing.db not found at {DB_PATH}. Run the pipeline first.")
    return sqlite3.connect(str(DB_PATH))


def export_mortgage_rates(con, days_back: int = 90) -> int:
    """Export mortgage rate series for last N days."""
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    cur = con.execute("""
        SELECT date, field_name, rate
        FROM mortgage_rates
        WHERE date >= ?
        ORDER BY date ASC
    """, (cutoff,))
    rows = cur.fetchall()

    # Pivot to {date, rate_30yr_fixed, rate_15yr_fixed, rate_5yr_arm}
    by_date = {}
    for date, field, rate in rows:
        if date not in by_date:
            by_date[date] = {"date": date}
        by_date[date][field] = rate

    series = sorted(by_date.values(), key=lambda x: x["date"])

    out = {
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "days_back": days_back,
        "series": series
    }
    _write("mortgage_rates.json", out)
    return len(series)


def export_ma_state(con) -> int:
    """Export MA vs national state-level ZHVI."""
    cur = con.execute("""
        SELECT state, date, median_price, yoy_pct
        FROM zhvi_state
        WHERE state IN ('Massachusetts', 'United States')
        ORDER BY state, date ASC
    """)
    rows = cur.fetchall()

    by_state = {}
    for state, date, price, yoy in rows:
        if state not in by_state:
            by_state[state] = []
        by_state[state].append({"date": date, "median_price": price, "yoy_pct": yoy})

    out = {
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "states": by_state
    }
    _write("ma_state.json", out)
    return sum(len(v) for v in by_state.values())


def export_ma_counties(con) -> int:
    """Export MA county ZHVI — latest available month per county."""
    cur = con.execute("""
        SELECT county, date, median_price, yoy_pct
        FROM zhvi_county
        WHERE state = 'MA'
        ORDER BY county, date ASC
    """)
    rows = cur.fetchall()

    # Group all months per county, keep all for chart + latest for table
    by_county = {}
    for county, date, price, yoy in rows:
        if county not in by_county:
            by_county[county] = []
        by_county[county].append({"date": date, "median_price": price, "yoy_pct": yoy})

    # Build output: latest snapshot + full history
    counties = []
    for county, history in sorted(by_county.items()):
        latest = history[-1]
        counties.append({
            "county": county,
            "latest_date": latest["date"],
            "median_price": latest["median_price"],
            "yoy_pct": latest["yoy_pct"],
            "history": history
        })

    # Sort by median price descending
    counties.sort(key=lambda x: x["median_price"] or 0, reverse=True)

    out = {
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "counties": counties
    }
    _write("ma_counties.json", out)
    return len(counties)


def export_ma_tax(con) -> int:
    """Export MA town property tax rates — all years available."""
    cur = con.execute("""
        SELECT town, year, residential_rate, yoy_change
        FROM ma_property_tax
        ORDER BY town, year ASC
    """)
    rows = cur.fetchall()

    by_town = {}
    for town, year, rate, yoy in rows:
        if town not in by_town:
            by_town[town] = []
        by_town[town].append({"year": year, "rate": rate, "yoy_change": yoy})

    # Build flat list with latest year's data for the table
    towns = []
    for town, history in sorted(by_town.items()):
        latest = history[-1]
        towns.append({
            "town": town,
            "year": latest["year"],
            "rate": latest["rate"],
            "yoy_change": latest["yoy_change"],
            "history": history
        })

    out = {
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "towns": towns
    }
    _write("ma_tax.json", out)
    return len(towns)


def _write(filename: str, data: dict):
    path = OUT_DIR / filename
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  Export: wrote {path.name} ({path.stat().st_size // 1024}KB)")


def run(verbose: bool = True):
    if verbose:
        print("\nExporting housing.db to docs/data/ JSON files...")
    try:
        con = get_db()
    except FileNotFoundError as e:
        print(f"  {e}")
        return

    counts = {}
    try:
        counts["mortgage_rates"] = export_mortgage_rates(con)
        counts["ma_state"]       = export_ma_state(con)
        counts["ma_counties"]    = export_ma_counties(con)
        counts["ma_tax"]         = export_ma_tax(con)
        con.close()
        if verbose:
            print(f"  Export complete: {counts}")
    except Exception as e:
        print(f"  Export error: {e}")
        con.close()


if __name__ == "__main__":
    run()
