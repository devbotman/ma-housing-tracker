# 🏠 MA Housing Market Tracker

Real-time housing market analytics dashboard for Massachusetts and the US. All data from free public sources — no API keys required except FRED (free registration).

**Live dashboard:** [devbotman.github.io/ma-housing-tracker](https://devbotman.github.io/ma-housing-tracker) *(coming soon)*

---

## 📊 What it tracks

### Massachusetts (town & county level)
- Median sale price by town and county — current month vs. prior year
- Price per square foot trends
- Days on market
- Property tax rates with YoY changes (MA DOR public data)
- Sales volume and inventory levels

### National
- Median home prices by state (Zillow ZHVI)
- Affordability index (price-to-income ratio)
- New vs. existing home sales

### Mortgage & Refinance Rates (last 60 days)
- 30-year fixed
- 15-year fixed
- 5/1 ARM
- Refinance rate spread vs. purchase rate
- All charted as time series from FRED

---

## 🗂️ Data Sources

| Data | Source | Update freq | Free? |
|------|--------|-------------|-------|
| Mortgage rates | [FRED (Freddie Mac PMMS)](https://fred.stlouisfed.org/series/MORTGAGE30US) | Weekly | ✅ Free API |
| Median prices by state | [Zillow Research ZHVI](https://www.zillow.com/research/data/) | Monthly | ✅ Free CSV |
| Median prices by zip/county | [Zillow Research ZHVI](https://www.zillow.com/research/data/) | Monthly | ✅ Free CSV |
| Median prices by MA town | [Redfin Data Center](https://www.redfin.com/news/data-center/) | Monthly | ✅ Free CSV |
| Property tax rates | [MA DOR Local Tax Rates](https://www.mass.gov/lists/local-tax-rates-by-town) | Annual | ✅ Free |
| New home sales | [Census Bureau](https://www.census.gov/econ/currentdata/) | Monthly | ✅ Free |

---

## 🏗️ Architecture

```
pipeline/
  fetch_fred.py          # Mortgage/refi rates via FRED API
  fetch_zillow.py        # Download + parse Zillow ZHVI CSVs
  fetch_redfin.py        # Download + parse Redfin MA town data
  fetch_ma_tax.py        # Scrape MA DOR property tax table
  load_db.py             # Load all sources into SQLite
  run_pipeline.py        # Orchestrator — runs all fetchers

server.py                # Flask API serving chart data
dashboard.html           # Single-page dashboard (Chart.js)
housing.db               # SQLite database (gitignored)
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/devbotman/ma-housing-tracker.git
cd ma-housing-tracker
pip install -r requirements.txt

# Get a free FRED API key at https://fred.stlouisfed.org/docs/api/api_key.html
export FRED_API_KEY=your_key_here

# Run the data pipeline (downloads ~50MB of CSVs, takes ~2 min first run)
python pipeline/run_pipeline.py

# Start the dashboard
python server.py
# → http://localhost:5051
```

---

## 📁 Tech Stack

- **Python 3.12** — data pipeline
- **pandas** — CSV parsing, aggregation, YoY calculations
- **requests** — FRED API + file downloads
- **SQLite** — local data store
- **Flask** — API layer
- **Chart.js** — interactive charts
- **GitHub Actions** — weekly automated data refresh

---

*Data is for informational purposes only. Not financial advice.*
