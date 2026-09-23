"""Download Minneapolis Assessing Department parcel data (building characteristics).

Source: City of Minneapolis, "Assessing Department Parcel Data <year>"
  https://opendata.minneapolismn.gov/datasets/assessing-department-parcel-data-2026
One dataset per assessment year (values as of January 2; taxes payable the next year).

Privacy: the owner name field is never requested.

Usage: python pipeline/fetch_minneapolis.py 2025 2026
"""
import sys
from pathlib import Path

from arcgis import fetch_layer

URL = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/Assessing_Department_Parcel_Data_{year}/FeatureServer/0"
OUT = Path(__file__).resolve().parent.parent / "data"
FIELDS = [
    "ObjectId", "ASMTYEAR", "HOUSE_NO", "ADRSTR", "UNITNO", "ZIP1", "ADDRESSFORMATTED", "NEIGHBORHOOD", "COMMUNITY",
    "ZONING", "PARCELAREA", "X", "Y", "PROPERTYTYPE", "LANDVALUE", "BUILDINGVALUE", "TOTALVALUE", "HOMESTEAD",
    "NUMBEROFBUILDINGS", "BUILDINGUSE", "YEARBUILT", "BASEMENTAREA", "ABOVEGROUNDAREA", "STORIES",
    "PRIMARYHEATING", "CONSTRUCTIONTYPE", "EXTERIORWALL", "ROOF", "GARAGESTALLS", "TOTALBEDROOMS",
    "FIREPLACES", "TOTALBATHROOMS",
]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for year in sys.argv[1:] or ["2026"]:
        df = fetch_layer(URL.format(year=year), "PROPERTYTYPE = 'RESIDENTIAL 1 UNIT'", FIELDS)
        path = OUT / f"minneapolis_{year}.csv.gz"
        df.to_csv(path, index=False)
        print(f"{year}: {len(df)} rows -> {path}")
