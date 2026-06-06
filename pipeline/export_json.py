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
    """Export MA + comparison states ZHVI trend."""
    cur = con.execute("""
        SELECT state, date, median_price, yoy_pct
        FROM zhvi_state
        WHERE state IN ('Massachusetts', 'Connecticut', 'New Hampshire', 'Rhode Island',
                        'New York', 'California', 'Texas', 'Florida')
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


def export_ma_market(con) -> int:
    """Export MA market activity (inventory, new listings, % above list, median list price, rent)."""
    # County-level datasets: latest value + 24-month history per county
    county_datasets = {
        "inventory":        "market_invt_county",
        "new_listings":     "market_newlist_county",
        "pct_above_list":   "market_pct_above_county",
        "median_list_price":"market_mlp_county",
        "rent_index":       "market_zori_county",
    }
    # State-level time series
    state_datasets = {
        "inventory":        "market_invt_state",
        "new_listings":     "market_newlist_state",
        "pct_above_list":   "market_pct_above_state",
        "median_list_price":"market_mlp_state",
    }

    # Build county snapshots
    counties = {}
    for metric, table in county_datasets.items():
        try:
            cur = con.execute(f"""
                SELECT county, date, {metric}
                FROM {table}
                WHERE state = 'MA'
                ORDER BY county, date ASC
            """)
            for county, date, val in cur.fetchall():
                if county not in counties:
                    counties[county] = {"county": county, "history": {}}
                if metric not in counties[county]["history"]:
                    counties[county]["history"][metric] = []
                counties[county]["history"][metric].append({"date": date, "value": val})
        except Exception:
            pass  # table may not exist yet

    # Compute latest values per county per metric
    county_list = []
    for county, data in sorted(counties.items()):
        entry = {"county": county, "latest": {}, "history": data["history"]}
        for metric, series in data["history"].items():
            if series:
                entry["latest"][metric] = series[-1]
        county_list.append(entry)

    # Build state time series (all metrics on same date axis)
    state_series = {}
    for metric, table in state_datasets.items():
        try:
            cur = con.execute(f"""
                SELECT date, {metric} FROM {table}
                WHERE state = 'Massachusetts'
                ORDER BY date ASC
            """)
            for date, val in cur.fetchall():
                if date not in state_series:
                    state_series[date] = {"date": date}
                state_series[date][metric] = val
        except Exception:
            pass

    state_list = sorted(state_series.values(), key=lambda x: x["date"])

    out = {
        "updated":  datetime.now().strftime("%Y-%m-%d"),
        "counties": county_list,
        "state":    state_list,
    }
    _write("ma_market.json", out)
    return len(county_list)


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
    exporters = [
        ("mortgage_rates", export_mortgage_rates),
        ("ma_state",       export_ma_state),
        ("ma_counties",    export_ma_counties),
        ("ma_tax",         export_ma_tax),
        ("ma_market",      export_ma_market),
    ]
    for name, fn in exporters:
        try:
            counts[name] = fn(con)
        except Exception as e:
            print(f"  Export skipped {name}: {e}")
            counts[name] = 0
    con.close()
    if verbose:
        print(f"  Export complete: {counts}")


if __name__ == "__main__":
    run()
