"""Paged downloads from public ArcGIS REST feature/map layers."""
import time

import pandas as pd
import requests


def fetch_layer(layer_url, where, fields, page=1000):
    rows, offset = [], 0
    session = requests.Session()
    while True:
        params = {"where": where, "outFields": ",".join(fields), "returnGeometry": "false",
                  "orderByFields": "OBJECTID" if "OBJECTID" in fields else "", "resultOffset": offset,
                  "resultRecordCount": page, "f": "json"}
        for attempt in range(5):
            try:
                resp = session.get(f"{layer_url}/query", params=params, timeout=60)
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
        print(f"\r{offset} rows", end="", flush=True)
        if not batch or not data.get("exceededTransferLimit", len(batch) == page):
            break
        time.sleep(0.2)  # be polite to public servers
    print()
    df = pd.DataFrame(rows, columns=fields)
    text = df.select_dtypes("object").columns
    df[text] = df[text].apply(lambda c: c.str.strip())
    return df
