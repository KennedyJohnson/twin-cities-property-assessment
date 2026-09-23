"""Download Minneapolis building permits for single-family homes.

Source: City of Minneapolis, "CCS Permits"
  https://opendata.minneapolismn.gov/ (dataset: CCS_Permits)
Permits are a renovation/condition signal that parcel records don't carry.

Privacy: applicant and contractor names/addresses are never requested.
The free-text work description is kept locally for keyword features only
and is never published.

Usage: python pipeline/fetch_permits.py
"""
from pathlib import Path

import pandas as pd

from arcgis import fetch_layer

URL = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/CCS_Permits/FeatureServer/0"
OUT = Path(__file__).resolve().parent.parent / "data"
FIELDS = ["OBJECTID", "APN", "permitNumber", "permitType", "occupancyType", "workType", "status",
          "value", "totalFees", "comments", "issueDate", "completeDate"]

if __name__ == "__main__":
    df = fetch_layer(URL, "occupancyType = 'SFD'", FIELDS, page=16000)
    for c in ["issueDate", "completeDate"]:
        df[c] = pd.to_datetime(df[c], unit="ms", errors="coerce")
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "permits_sfd.csv.gz", index=False)
    print(f"{len(df)} permits -> {OUT / 'permits_sfd.csv.gz'}")
