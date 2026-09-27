"""Discover which yearly datasets are published, so the pipeline never needs a hardcoded year."""
from datetime import date
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
ASMT_URL = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/Assessing_Department_Parcel_Data_{year}/FeatureServer/0"
SNAPSHOT_URL = "https://arcgis.metc.state.mn.us/data1/rest/services/parcels/Parcel_Points_{year}/FeatureServer/3"


def _exists(url):
    try:
        r = requests.get(url, params={"f": "json"}, timeout=60)
        return r.ok and "error" not in r.json()
    except (requests.RequestException, ValueError):
        return False


def published_assessment_year():
    """Newest Minneapolis assessment layer online (new one usually appears in spring)."""
    for year in range(date.today().year + 1, date.today().year - 3, -1):
        if _exists(ASMT_URL.format(year=year)):
            return year
    raise RuntimeError("no Minneapolis assessment layer found")


def snapshot_years(first=2021):
    """MetroGIS annual parcel snapshots available from `first` onward."""
    return [y for y in range(first, date.today().year + 1) if _exists(SNAPSHOT_URL.format(year=y))]


def local_assessment_year():
    """Newest assessment year already downloaded into data/."""
    return max(int(p.name.split("_")[1][:4]) for p in DATA.glob("minneapolis_*.csv.gz"))


if __name__ == "__main__":
    print(published_assessment_year())
