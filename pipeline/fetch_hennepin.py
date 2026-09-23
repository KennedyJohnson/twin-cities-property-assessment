"""Download residential parcels from Hennepin County's public parcel layer.

Source: Hennepin County GIS, "County Parcels" (compiled monthly)
  https://gis-hennepin.opendata.arcgis.com/datasets/7975aabf6e1e42998a40a4b085ffefdf_1
  Furnished "AS IS" with no warranty; not suitable for legal, engineering or surveying purposes.

Privacy: owner and taxpayer name fields are never requested, so no personal
names are downloaded or stored. Only property attributes that describe the
parcel itself are kept.

Usage: python pipeline/fetch_hennepin.py
"""
from datetime import date
from pathlib import Path

import pandas as pd

from arcgis import fetch_layer

LAYER = "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1"
OUT = Path(__file__).resolve().parent.parent / "data"

PROPERTY_TYPES = ["RESIDENTIAL"]  # single-family homes for v1
FIELDS = [
    "OBJECTID", "PID", "HOUSE_NO", "FRAC_HOUSE_NO", "STREET_NM", "ZIP_CD", "MUNIC_NM", "SCHOOL_DIST_NO",
    "PR_TYP_NM1", "HMSTD_CD1", "BUILD_YR", "PARCEL_AREA",
    "SALE_DATE", "SALE_PRICE", "SALE_CODE_NAME",
    "MKT_VAL_TOT", "LAND_MV1", "BLDG_MV1", "TAX_TOT", "PETITION_REVIEW_IND",
    "LAT", "LON",
]


if __name__ == "__main__":
    types = ",".join(f"'{t}'" for t in PROPERTY_TYPES)
    df = fetch_layer(LAYER, f"PR_TYP_NM1 IN ({types})", FIELDS, page=2000)
    # SALE_DATE is a "YYYYMM" string (month precision).
    df["SALE_DATE"] = pd.to_datetime(df["SALE_DATE"], format="%Y%m", errors="coerce")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"hennepin_{date.today():%Y%m}.csv.gz"
    df.to_csv(path, index=False)
    print(f"{len(df)} rows -> {path}")
