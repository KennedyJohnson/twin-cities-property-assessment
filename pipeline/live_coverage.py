"""Live check of the published estimates against sales that closed after they were published.

Each monthly build saves the estimate and ranges it published for that month (`tracking/estimates_YYYY-MM.csv.gz`,
parcel ID + numbers only). Later builds join those snapshots to qualified sales that closed in the estimate month
after the snapshot was built, which the model could not have seen, and report how often the 90% and 50% ranges
actually contained the sale price. The backtest answers the same question for past years; this one keeps
answering it for the estimates people actually saw.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from model import _pid

TRACKING = Path(__file__).resolve().parent.parent / "tracking"
MIN_SALES = 30  # months with fewer matched sales aren't reported


def snapshot(res: pd.DataFrame, ok, month: pd.Timestamp, built: pd.Timestamp):
    TRACKING.mkdir(exist_ok=True)
    s = res.loc[np.asarray(ok), ["PID", "est_now", "low_now", "high_now", "low50_now", "high50_now"]].round(0)
    s = s.assign(PID=_pid(s.PID).astype("Int64"), built=built.strftime("%Y-%m-%d")).dropna(subset=["PID"])
    s.to_csv(TRACKING / f"estimates_{month:%Y-%m}.csv.gz", index=False)


def report(sales: pd.DataFrame) -> list[dict]:
    out = []
    for path in sorted(TRACKING.glob("estimates_*.csv.gz")):
        month = pd.Period(path.name.removeprefix("estimates_").removesuffix(".csv.gz"), "M")
        snap = pd.read_csv(path, dtype={"PID": "Int64"})
        built = pd.Timestamp(snap.built.iloc[0])
        later = sales[(sales.SALE_DATE.dt.to_period("M") == month) & (sales.SALE_DATE > built)]
        j = later.assign(PID=_pid(later.PID).astype("Int64"))[["PID", "SALE_PRICE"]].merge(snap, on="PID")
        if len(j) < MIN_SALES:
            continue
        p = j.SALE_PRICE
        out.append({
            "month": str(month), "sales": int(len(j)),
            "range90_coverage": round(float(((p >= j.low_now) & (p <= j.high_now)).mean()), 3),
            "range50_coverage": round(float(((p >= j.low50_now) & (p <= j.high50_now)).mean()), 3),
            "median_abs_pct_error": round(float((j.est_now / p - 1).abs().median()), 4),
            "median_ratio": round(float((j.est_now / p).median()), 4),
        })
    return out
