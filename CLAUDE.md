# Twin Cities Property Assessment

Static site (`site/`, GitHub Pages via `pages.yml`) comparing a Minneapolis home's city assessed value to comparable sales plus an independent sale-price estimate. Python pipeline, no backend, no paid APIs. Never download/publish owner or taxpayer names.

## Pipeline (`pipeline/`, run from that dir; raw downloads go to gitignored `data/`)
1. `fetch_hennepin.py` → `data/hennepin_YYYYMM.csv.gz` (county parcels + latest sales; newest file is used)
2. `fetch_minneapolis.py [years]` → `data/minneapolis_<year>.csv.gz` (default: newest published year and prior)
3. `fetch_sale_history.py` → `sale_history.csv.gz` (MetroGIS annual snapshots, auto-discovered years)
4. `fetch_permits.py`, `fetch_condition.py` (inspections, rental licenses)
5. `model.py` → `data/backtest.json` (backtests latest-1 and latest assessment years)
6. `build_site.py` → `site/data/` (`summary.json` has `assessment_year`, `built`)
- `years.py` - discovers published assessment year / snapshot years from ArcGIS (no hardcoded years). `arcgis.py` - paged FeatureServer fetch. `build_neighborhoods.py` - neighborhood outputs.
- Model: sklearn HistGradientBoosting on log price, hedonic time index, 5-seed ensemble, conformalized quantile ranges. See README "Method" before changing modeling.

## Site
`site/index.html`, `site/app.js` (vanilla JS). Stale banner if `summary.built` > 60 days old.

## Automation
- `refresh.yml` - monthly (3rd, 09:00 UTC): full pipeline, commits `site/data` + `last_updated.json`, then `gh workflow run pages.yml` (GITHUB_TOKEN pushes don't trigger deploys). Fails (→ `stale-data` issue) if by June the current year's assessment layer isn't published.
- `pages.yml` - deploys `site/` on push to main or dispatch.
