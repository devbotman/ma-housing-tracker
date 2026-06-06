"""
run_pipeline.py — Housing data pipeline orchestrator
=====================================================
Runs all fetchers in sequence. Safe to run on a schedule (weekly).

Usage:
    python pipeline/run_pipeline.py
    python pipeline/run_pipeline.py --fred-only
    python pipeline/run_pipeline.py --zillow-only
    FRED_API_KEY=abc123 python pipeline/run_pipeline.py
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fred-only",   action="store_true")
    parser.add_argument("--zillow-only", action="store_true")
    parser.add_argument("--tax-only",    action="store_true")
    parser.add_argument("--all-states",  action="store_true", help="Load all states in Zillow (slow)")
    args = parser.parse_args()

    t0 = time.time()
    print(f"\n{'='*50}")
    print(f"  MA Housing Tracker — Data Pipeline")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'='*50}\n")

    run_all = not any([args.fred_only, args.zillow_only, args.tax_only])

    if run_all or args.fred_only:
        print("Step 1: Mortgage rates (FRED)...")
        try:
            from fetch_fred import run as run_fred
            run_fred()
        except Exception as e:
            print(f"  FRED error: {e}")

    if run_all or args.zillow_only:
        print("\nStep 2: Home prices (Zillow ZHVI)...")
        try:
            from fetch_zillow import run as run_zillow
            run_zillow(ma_only=not args.all_states)
        except Exception as e:
            print(f"  Zillow error: {e}")

    if run_all or args.tax_only:
        print("\nStep 3: Property tax rates (MA DOR)...")
        try:
            from fetch_ma_tax import run as run_tax
            run_tax()
        except Exception as e:
            print(f"  Tax error: {e}")

    if run_all or args.zillow_only:
        print("\nStep 3b: Market activity (Zillow extended)...")
        try:
            from fetch_zillow_market import run as run_market
            run_market()
        except Exception as e:
            print(f"  Market error: {e}")

    print("\nStep 4: Exporting to JSON (dashboard)...")
    try:
        from export_json import run as run_export
        run_export()
    except Exception as e:
        print(f"  Export error: {e}")

    elapsed = time.time() - t0
    print(f"\n{'='*50}")
    print(f"  Pipeline complete — {elapsed:.1f}s")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
