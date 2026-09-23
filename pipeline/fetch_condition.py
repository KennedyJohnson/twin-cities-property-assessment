"""Download condition signals: housing inspection cases and rental licenses (Minneapolis).

Sources (City of Minneapolis open data, https://opendata.minneapolismn.gov/):
  CaseInspections        housing/code-violation inspections, keyed by parcel (APN)
  Active_Rental_Licenses rental license and tier per property

Privacy: only parcel IDs, dates, case/inspection types and license tier are
requested. Owner and applicant names, addresses, phones and emails are never
downloaded.

Usage: python pipeline/fetch_condition.py
"""
from pathlib import Path

import pandas as pd

from arcgis import fetch_layer

BASE = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/{name}/FeatureServer/0"
OUT = Path(__file__).resolve().parent.parent / "data"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    insp = fetch_layer(BASE.format(name="CaseInspections"), "1=1",
                       ["OBJECTID", "APN", "Violation_Case_Number", "Case_Type", "Case_Group", "Inspection_Result",
                        "Inspection_Type", "Completed_Date"], page=2000)
    insp["Completed_Date"] = pd.to_datetime(insp.Completed_Date, unit="ms", errors="coerce")
    insp.to_csv(OUT / "inspections.csv.gz", index=False)
    print(f"{len(insp)} inspections")

    rent = fetch_layer(BASE.format(name="Active_Rental_Licenses"), "1=1",
                       ["OBJECTID", "apn", "category", "tier", "status", "issueDate", "licensedUnits"], page=2000)
    rent["issueDate"] = pd.to_datetime(rent.issueDate, unit="ms", errors="coerce")
    rent.to_csv(OUT / "rental_licenses.csv.gz", index=False)
    print(f"{len(rent)} rental licenses")
