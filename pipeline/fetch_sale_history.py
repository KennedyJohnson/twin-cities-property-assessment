"""Recover earlier sales from the Metropolitan Council's annual parcel snapshots.

Hennepin's live parcel layer only keeps each parcel's latest sale. The annual
snapshots each hold the latest sale as of that year, so stacking them yields
prior sales for homes that have since sold again.

Source: Metropolitan Council / MetroGIS, "Metropolitan 7-County Parcel Points - <year>"
  https://gis.data.mn.gov/ (search "Metropolitan 7-County Parcel Points")
  https://metrogis.org/how-do-i-get/parcel-data/

Privacy: only the parcel ID, sale date and sale value are requested.

Usage: python pipeline/fetch_sale_history.py
"""
from pathlib import Path

import pandas as pd

from arcgis import fetch_layer

URL = "https://arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcel_Points_{year}/FeatureServer/3"  # layer 3 = Hennepin
OUT = Path(__file__).resolve().parent.parent / "data"
YEARS = range(2021, 2026)

if __name__ == "__main__":
    frames = []
    for year in YEARS:
        df = fetch_layer(URL.format(year=year), "CTU_NAME = 'Minneapolis' AND SALE_VALUE > 0",
                         ["OBJECTID", "COUNTY_PIN", "SALE_DATE", "SALE_VALUE"], page=2000)
        frames.append(df.assign(snapshot=year))
    hist = pd.concat(frames)
    hist["SALE_DATE"] = pd.to_datetime(hist.SALE_DATE, unit="ms", errors="coerce")
    hist = hist.drop_duplicates(["COUNTY_PIN", "SALE_DATE", "SALE_VALUE"]).drop(columns="OBJECTID")
    hist.to_csv(OUT / "sale_history.csv.gz", index=False)
    print(f"{len(hist)} distinct sales, {hist.COUNTY_PIN.nunique()} parcels -> {OUT / 'sale_history.csv.gz'}")
