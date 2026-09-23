# Twin Cities Property Assessment Check

A free tool that helps Twin Cities homeowners see whether their property's assessed value (the "estimated market value" on their tax statement) looks out of line with what comparable homes actually sold for, and, only when the evidence is strong, how to raise it with the assessor.

**Status:** early development. Data ingestion works for Hennepin County; the valuation model and site are in progress.

## Principles

1. **Only flag when we're really sure.** Most homes will show "in line with comparable sales" or "not enough data." A home is only flagged as *possibly over-assessed* when several independent checks agree, and the flag threshold is calibrated so that it is rarely wrong on held-out sales (see [Flagging policy](#flagging-policy)). We would rather miss a case than send someone to an appeal they will lose.
2. **Informational, not advice.** This is not an appraisal, and not legal or tax advice. It points people to the official appeal process and the evidence the assessor asks for.
3. **Public data only, no personal names.** Owner and taxpayer names are never downloaded. The site shows only property characteristics and values that the county already publishes per parcel.
4. **Free to run.** Data refresh and model training run on GitHub Actions; the site is static files on Vercel/GitHub Pages. No paid APIs or servers.

## How it works (planned)

```
county open data ──► fetch (monthly, GitHub Actions) ──► clean + qualify sales
                                                           │
                            valuation model (trained on qualified sales, time-based validation)
                                                           │
             per-parcel: assessed value vs. model range vs. nearby comparable sales
                                                           │
                        static JSON per ZIP code ──► static site (address search)
```

## Flagging policy

A parcel is shown as **possibly over-assessed** only if *all* of these hold:

- The assessed value is above the **upper end of the model's 90% prediction interval** (the interval is calibrated on held-out sales, so it contains the true sale price about 90% of the time).
- At least **five qualified comparable sales** (same area, similar size and age, sold in the assessment window) have a **median price below** the assessed value by a meaningful margin.
- The parcel has complete data (no missing building characteristics, not recently split or combined, not under an existing petition).

Before launch, the policy is backtested on sales the model never saw: among homes it would have flagged, the share that actually sold **at or above** their assessed value must be very small (target: under 5%). Those results will be published on the site.

## First look at the data (Hennepin County, single-family homes)

Using arm's-length sales ("warranty deed") compared with the county's current estimated market value:

| Sale year | Sales | Median assessed ÷ sale price | COD* |
|---|---|---|---|
| 2023 | 7,384 | 0.98 | 8.9 |
| 2024 | 7,840 | 0.96 | 10.0 |
| 2025 | 8,561 | 0.92 | 11.0 |
| 2026 (to Aug) | 5,969 | 0.90 | 12.8 |

\*Coefficient of dispersion: how spread out the ratios are. The IAAO standard for single-family homes is 5–15.

- **Most homes are assessed below recent sale prices**, typically by 8–10%. Over-assessment is the exception.
- **Mild regressivity:** among 2025–26 sales, the cheapest tenth of homes had a median ratio of 0.98 versus 0.87 for the most expensive tenth. This is consistent with the [UChicago Property Tax Project's Hennepin report](https://s3.us-east-2.amazonaws.com/propertytaxdata.uchicago.edu/nationwide_reports/web/Hennepin%20County_Minnesota.html).
- These are preliminary numbers that don't yet apply the state's full [sales ratio study criteria](https://www.revenue.state.mn.us/sales-ratio-studies) or time adjustments.

## Data sources

| Source | Used for | Terms |
|---|---|---|
| [Hennepin County GIS – County Parcels](https://gis-hennepin.opendata.arcgis.com/datasets/7975aabf6e1e42998a40a4b085ffefdf_1) (monthly) | Assessed values, last sale, build year, lot size, location | Free, no license required. Furnished "AS IS" with no warranty; not suitable for legal, engineering or surveying purposes. |
| [Minneapolis Assessing Department Parcel Data](https://opendata.minneapolismn.gov/datasets/assessing-department-parcel-data-2025) (planned) | Square footage, bedrooms, bathrooms | City open data |
| [MN Dept. of Revenue – Sales ratio studies](https://www.revenue.state.mn.us/sales-ratio-studies) and [criteria](https://www.revenue.state.mn.us/sites/default/files/2025-10/2026-sales-ratio-criteria-10-21-25.pdf) | Which sales count as arm's-length; study window | Public |
| [UChicago Property Tax Project](https://s3.us-east-2.amazonaws.com/propertytaxdata.uchicago.edu/nationwide_reports/web/Hennepin%20County_Minnesota.html) | Cross-checking regressivity results | Cited only |

Property records are public data under the [Minnesota Government Data Practices Act](https://mn.gov/admin/data-practices/data/rules/laws/) (Minn. Stat. ch. 13).

## Appeal process (official sources)

- Minneapolis: [Appeal your market value](https://www.minneapolismn.gov/resident-services/property-housing/property-values-taxes/market-value/appeal/). The City Assessor handles Minneapolis.
- Other Hennepin cities: [Hennepin County property assessment](https://www.hennepin.us/residents/property/property-assessment)
- Statewide: [MN Dept. of Revenue – Appealing property value and classification](https://www.revenue.state.mn.us/appealing-property-value-and-classification)

## Related

[Twin Cities Living Quality Map](https://github.com/KennedyJohnson/Twin-Cities_Living_Quality_Map). Its district-level home value model and time-based validation approach inform this project.

## Run it

```bash
pip install pandas requests
python pipeline/fetch_hennepin.py   # ~287k single-family parcels -> data/ (gitignored)
```

## Disclaimer

Estimates are statistical and can be wrong. This tool does not provide appraisals, legal advice, or tax advice, and is not affiliated with Hennepin County, the City of Minneapolis, or the State of Minnesota. Always review your official valuation notice and contact your assessor before filing an appeal.
