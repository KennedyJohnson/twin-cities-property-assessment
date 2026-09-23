# Is your home's value in line with similar homes?

A free tool for Minneapolis homeowners: look up a house and see how the city's assessed value (the basis of your property tax) compares with what similar nearby homes actually sold for, plus an independent estimate of what the home would sell for this month, from a model that never sees the city's value.

**Live site:** https://kennedyjohnson.github.io/twin-cities-property-assessment/ (Minneapolis single-family homes, 2026 assessment)

## What it shows

- **The comparison:** the city's value next to time-adjusted prices of similar nearby sales (close in location, house size, age and lot size), in plain language: *about the same*, *on the high side*, *on the low side*, or *mixed*.
- **An independent estimate** of the expected sale price this month (and at the January valuation date), with two calibrated ranges: a likely range (about half of homes sell inside it) and a wide range (9 in 10).
- **Citywide fairness:** the city's value as a share of sale price across price tiers, measured on sales after the valuation date.
- **Next steps:** how to talk to the assessor and appeal, with official links. Plus how owner names appear in public records and how to keep yours private.

## Design principles

1. **No verdicts we can't back up.** An "over-assessed" flag was built and backtested first. About 1 in 5 flagged homes still sold at or above their assessed value, because public data can't see a home's condition. So the site shows context instead, and only says "high side" when both the comparable sales and the model agree.
2. **Informational, not advice.** Not an appraisal, and not legal or tax advice.
3. **No personal names.** Owner, taxpayer and applicant names are never downloaded. Only property characteristics, values and sale prices are published.
4. **Free to run.** Python pipeline, static site on GitHub Pages, no paid APIs or servers.

## Method

- **Model:** gradient-boosted trees (scikit-learn) on log sale price, trained on arm's-length Minneapolis sales from the five years before the January 2 valuation date.
  - **Inputs:** house size, age, rooms, lot, construction, location, the price per sq ft of the 10 and 30 nearest earlier sales, the home's own previous sale adjusted for market changes, building permits, and housing-inspection, vacant-building and rental-license history.
  - **Time:** a monthly hedonic price index (the typical price left after a model that can't see dates) is taken out before training. It's projected forward with its seasonal pattern and two-year trend, so the model gives an expected sale price for any month. Trees can't extrapolate a trend on their own; handling time this way cut a 5–7% underestimate on later sales to about 0–4%.
  - The estimate averages 5 models trained with different random seeds, to reduce variance.
  - All history features only use records dated before each sale, so nothing leaks in from the future.
  - The model never sees the assessor's values.
- **Ranges:** conformalized quantile regression. Calibrated on the most recent 20% of sales, scored with the index projected from the older 80% so forecast error is included, then refit on all of them.
- **Model selection:** every choice (features, settings, trend handling) was made on a validation split inside each training window (the last 12 months before January). The test sales below were only scored at the end. Validation and test errors matched (9.3% vs 9.3%), which suggests the model isn't overfitting.
- **Tried and left out:** census tract income, education, homeownership and vacancy (ACS 5-year estimates), and distance to lakes, the river, parks, rail stations and downtown (OpenStreetMap). None of these improved validation error; neighborhood, location and nearby-sales features already capture them. Different tree settings, rotated coordinates and dropping the neighborhood field also made no real difference.
- **Comparable sales:** within half a mile, ±20% house size, ±15 years, ±50% lot, and sold in the two years before the valuation date. If fewer than 5 are found, the search widens in steps and the page says so. Prices are adjusted with a citywide monthly index.
- **Fairness statistics:** IAAO-style ratio study (median ratio, COD, PRD) on sales after the valuation date, trimming ratio outliers outside 1.5× the IQR.

## Backtest

Trained only on data before each year's valuation date, then scored on homes that sold afterwards (January–September). The model estimates the price for the month each home sold; the city's value is for January 2 and isn't adjusted for later price changes.

| Assessment year | Sales tested | Model's typical error | Model's median bias | City's typical error | In the 90% range | In the 50% range |
|---|---|---|---|---|---|---|
| 2025 | 1,998 | 9.3% (was 11.1%) | −4.5% | 13.6% | 88% | 48% |
| 2026 | 1,729 | 9.4% (was 10.7%) | +0.4% | 12.0% | 90% | 52% |

2025 still runs low because prices rose faster that year than the trend projected; forecasting from past sales alone can't fully catch a turn in the market.

## Data sources

| Source | Used for |
|---|---|
| [Minneapolis Assessing Department Parcel Data](https://opendata.minneapolismn.gov/datasets/assessing-department-parcel-data-2026) | Building characteristics, assessed values |
| [Hennepin County GIS – County Parcels](https://gis-hennepin.opendata.arcgis.com/datasets/7975aabf6e1e42998a40a4b085ffefdf_1) | Latest sales, sale type, addresses (furnished "as is", no warranty) |
| [MetroGIS Regional Parcel Dataset](https://metrogis.org/how-do-i-get/parcel-data/) (annual snapshots, 2021–2025) | Earlier sales |
| [Minneapolis open data](https://opendata.minneapolismn.gov/): CCS Permits, CaseInspections, Active Rental Licenses | Renovation and condition signals |
| [MN Dept. of Revenue – Sales ratio studies](https://www.revenue.state.mn.us/sales-ratio-studies) | Ratio-study methods |
| [Cook County Assessor's Office open-source model](https://github.com/ccao-data/model-res-avm) | Approach for the price index, nearby-sales features and boosted trees |
| [IAAO Standard on Ratio Studies](https://www.iaao.org/wp-content/uploads/Standard_on_Ratio_Studies.pdf) | COD, PRD and outlier trimming |
| [Romano, Patterson & Candès (2019)](https://arxiv.org/abs/1905.03222) | Conformalized quantile regression |
| [UChicago Property Tax Project](https://s3.us-east-2.amazonaws.com/propertytaxdata.uchicago.edu/nationwide_reports/web/Hennepin%20County_Minnesota.html) | Cross-check of the regressivity finding |

Property records are public data under the [Minnesota Government Data Practices Act](https://mn.gov/admin/data-practices/data/rules/laws/) (Minn. Stat. ch. 13).

## Run it

```bash
pip install pandas requests scikit-learn
cd pipeline
python fetch_hennepin.py            # county parcels and latest sales
python fetch_minneapolis.py 2025 2026
python fetch_sale_history.py        # MetroGIS annual snapshots
python fetch_permits.py
python fetch_condition.py           # inspections and rental licenses
python model.py                     # backtest -> data/backtest.json
python build_site.py                # site/data/
python -m http.server -d ../site 8000
```

Raw downloads live in `data/` (gitignored). `site/` is deployed to GitHub Pages by `.github/workflows/pages.yml`.

## Related

[Twin Cities Living Quality Map](https://github.com/KennedyJohnson/Twin-Cities_Living_Quality_Map). Its district-level home value model and time-based validation informed this project.

## Disclaimer

Estimates are statistical and can be wrong. This tool does not provide appraisals, legal advice or tax advice, and is not affiliated with Hennepin County, the City of Minneapolis or the State of Minnesota. Always review your official valuation notice and contact your assessor before filing an appeal.
