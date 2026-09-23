"""Download residential parcels from Hennepin County's public parcel layer.

Source: Hennepin County GIS, "County Parcels" (compiled monthly)
  https://gis-hennepin.opendata.arcgis.com/datasets/7975aabf6e1e42998a40a4b085ffefdf_1
  Furnished "AS IS" with no warranty; not suitable for legal, engineering or surveying purposes.

Privacy: owner and taxpayer name fields are never requested, so no personal
names are downloaded or stored. Only property attributes that describe the
parcel itself are kept.

Usage: python pipeline/fetch_hennepin.py
"""
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

LAYER = "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1/query"
OUT = Path(__file__).resolve().parent.parent / "data"
PAGE = 2000  # server maxRecordCount

PROPERTY_TYPES = ["RESIDENTIAL"]  # single-family homes for v1
FIELDS = [
    "PID", "HOUSE_NO", "FRAC_HOUSE_NO", "STREET_NM", "ZIP_CD", "MUNIC_NM", "SCHOOL_DIST_NO",
    "PR_TYP_NM1", "HMSTD_CD1", "BUILD_YR", "PARCEL_AREA",
    "SALE_DATE", "SALE_PRICE", "SALE_CODE_NAME",
    "MKT_VAL_TOT", "LAND_MV1", "BLDG_MV1", "TAX_TOT", "PETITION_REVIEW_IND",
    "LAT", "LON",
]


def fetch(where):
    rows, offset = [], 0
    session = requests.Session()
    while True:
        params = {"where": where, "outFields": ",".join(FIELDS), "returnGeometry": "false",
                  "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": PAGE, "f": "json"}
        for attempt in range(5):
            try:
                resp = session.get(LAYER, params=params, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise RuntimeError(data["error"])
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        batch = [f["attributes"] for f in data["features"]]
        rows.extend(batch)
        offset += len(batch)
        print(f"\r{offset} parcels", end="", flush=True)
        if len(batch) < PAGE:
            break
        time.sleep(0.2)  # be polite to the county server
    print()
    return pd.DataFrame(rows, columns=FIELDS)


if __name__ == "__main__":
    types = ",".join(f"'{t}'" for t in PROPERTY_TYPES)
    df = fetch(f"PR_TYP_NM1 IN ({types})")
    # SALE_DATE is a "YYYYMM" string (month precision); text fields are space-padded.
    df["SALE_DATE"] = pd.to_datetime(df["SALE_DATE"], format="%Y%m", errors="coerce")
    text = df.select_dtypes("object").columns
    df[text] = df[text].apply(lambda c: c.str.strip())
    OUT.mkdir(exist_ok=True)
    path = OUT / f"hennepin_{date.today():%Y%m}.csv.gz"
    df.to_csv(path, index=False)
    print(f"{len(df)} rows -> {path}")
