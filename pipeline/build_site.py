"""Build the static site data: per-address context, citywide fairness, and backtest results.

Outputs (site/data/):
  addresses.json   address -> ZIP, for the search box
  zip/<zip>.json   per-parcel context for one ZIP code
  summary.json     backtest accuracy + citywide assessment-fairness statistics

Published per parcel: address, the city's assessed value and building
characteristics (all already public on the city/county sites), our estimated
range, and nearby comparable sales (public sale records). No owner names.

Usage: python pipeline/build_site.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import build_neighborhoods
import model as M

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
ASMT_YEAR = 2026
VALUE_DATE = f"{ASMT_YEAR}-01-01"
MAX_COMPS = 8
MIN_GROUP = 30  # minimum sales to report a group's fairness statistics


# Search tiers for comparable sales, tried in order until at least MIN_COMPS are found:
# (radius in feet, max house-size difference, max age difference in years, months of sales,
#  max lot-size difference). Lot size matters: a big lot in a prime spot carries a lot of value.
COMP_TIERS = [
    (2640, 0.20, 15, 24, 0.50),  # within half a mile, close in size, age and lot, last two years
    (5280, 0.25, 25, 24, 0.60),  # within a mile, a bit looser
    (5280, 0.30, 30, 36, 0.75),  # within a mile, looser still, last three years
]


def comp_lists(parcels, sales, value_date):
    """Most similar nearby sales per parcel (time-adjusted), widening the search only when needed.

    Returns the sales table, a list of comp indices per parcel (most similar first), and the
    tier used (0 = closest search; -1 = not enough even at the widest search).
    """
    ref = pd.Timestamp(value_date).to_period("M")
    oldest = max(t[3] for t in COMP_TIERS)
    w = sales[(sales.SALE_DATE.dt.to_period("M") < ref)
              & (sales.SALE_DATE >= pd.Timestamp(value_date) - pd.DateOffset(months=oldest))].copy()
    idx = M.market_index(sales)
    base = idx[idx.index < ref].iloc[-1]
    w["adj"] = w.SALE_PRICE * base / w.SALE_DATE.dt.to_period("M").map(idx).astype(float)
    w = w.reset_index(drop=True)
    age_months = ((ref - w.SALE_DATE.dt.to_period("M")).apply(lambda d: d.n)).to_numpy()
    tree = BallTree(w[["X", "Y"]].to_numpy())
    max_r = max(t[0] for t in COMP_TIERS)
    near, dist = tree.query_radius(parcels[["X", "Y"]].to_numpy(), r=max_r, return_distance=True)
    area, yb, pid, lot = (w[c].to_numpy() for c in ["ABOVEGROUNDAREA", "YEARBUILT", "PID", "PARCELAREA"])
    out, tiers = [], []
    for (a, y, p, lt), cand, d in zip(parcels[["ABOVEGROUNDAREA", "YEARBUILT", "PID", "PARCELAREA"]].to_numpy(), near, dist):
        if not (a > 0 and y > 1800):
            out.append(np.array([], dtype=int))
            tiers.append(-1)
            continue
        size_gap = np.abs(area[cand] / a - 1)
        age_gap = np.abs(yb[cand] - y)
        lot_gap = np.abs(lot[cand] / lt - 1) if lt > 0 else np.zeros(len(cand))
        not_self = pid[cand] != p if pd.notna(p) else np.ones(len(cand), bool)
        chosen, tier = np.array([], dtype=int), -1
        for t, (radius, size_tol, age_tol, months, lot_tol) in enumerate(COMP_TIERS):
            ok = ((d <= radius) & (size_gap <= size_tol) & (age_gap <= age_tol) & (age_months[cand] <= months)
                  & (lot_gap <= lot_tol) & not_self)
            if ok.sum() >= M.MIN_COMPS:
                # Rank by similarity: distance (per quarter mile) + house-size, age and lot-size gaps.
                score = d[ok] / 1320 + size_gap[ok] * 5 + age_gap[ok] / 15 + lot_gap[ok] * 2
                chosen, tier = cand[ok][np.argsort(score)], t
                break
        out.append(chosen)
        tiers.append(tier)
    return w, out, tiers


def fairness(res, sales_after):
    """IAAO-style ratio statistics using sales that happened after the valuation date."""
    t = res.set_index("key").loc[sales_after.key].assign(price=sales_after.SALE_PRICE.to_numpy())
    t["ratio"] = t.TOTALVALUE / t.price
    # Standard ratio-study outlier trim (IAAO): drop ratios outside 1.5x the interquartile range.
    # These are mostly as-is, distressed or investor sales that don't reflect market value.
    q1, q3 = t.ratio.quantile([0.25, 0.75])
    n_all = len(t)
    t = t[t.ratio.between(q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1))]

    def stats(g):
        r = g.ratio
        med = r.median()
        return {"n": int(len(g)), "median_ratio": round(float(med), 3),
                "cod": round(float((r - med).abs().mean() / med * 100), 1),
                "prd": round(float(r.mean() / (g.TOTALVALUE.sum() / g.price.sum())), 3),
                "share_over_110": round(float((r > 1.10).mean()), 3)}

    t["decile"] = pd.qcut(t.price, 10, labels=False)
    by_comm = {c: stats(g) for c, g in t.groupby("COMMUNITY") if len(g) >= MIN_GROUP}
    return {"overall": stats(t), "trimmed": int(n_all - len(t)), "by_price_decile": [stats(g) | {"price_min": int(g.price.min()), "price_max": int(g.price.max())}
                                                     for _, g in t.groupby("decile")],
            "by_community": by_comm}


def main():
    df = M.load(ASMT_YEAR, sorted(M.DATA.glob("hennepin_*.csv.gz"))[-1].name)
    sales = M.qualified_sales(df)
    before = sales[sales.SALE_DATE < VALUE_DATE]
    after = sales[sales.SALE_DATE >= VALUE_DATE]

    # The model learns from every sale to date; comparisons with the city's value use its estimate at the
    # valuation date, and the page also shows its expected sale price for the current month.
    res = M.assess(df, before, VALUE_DATE, model_sales=sales)
    now = pd.Timestamp.today().normalize().replace(day=1)
    est_now, ranges_now = M.predict(res.attrs["models"], res, now)
    res = res.assign(est_now=est_now, low_now=ranges_now[0.10][0], high_now=ranges_now[0.10][1],
                     low50_now=ranges_now[0.50][0], high50_now=ranges_now[0.50][1])
    # Homes without a county match still have the city's building data, so they get context too.
    complete = res.ABOVEGROUNDAREA.gt(300) & res.YEARBUILT.gt(1800) & (res.PETITION_REVIEW_IND != "T")
    w, comps, tiers = comp_lists(res, before, VALUE_DATE)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "zip").mkdir(exist_ok=True)
    by_zip, index = {}, {}
    for i, r in enumerate(res.itertuples()):
        addr = r.county_addr if isinstance(r.county_addr, str) else " ".join(str(r.ADDRESSFORMATTED).split())
        zc = str(int(r.ZIP1)) if pd.notna(r.ZIP1) else "unknown"
        c = w.iloc[comps[i]] if len(comps[i]) else w.iloc[[]]
        enough = bool(complete.iloc[i] and tiers[i] >= 0)
        entry = {
            "a": addr, "nb": r.NEIGHBORHOOD, "v": int(r.TOTALVALUE),
            "sqft": int(r.ABOVEGROUNDAREA) if pd.notna(r.ABOVEGROUNDAREA) else None,
            "yb": int(r.YEARBUILT) if pd.notna(r.YEARBUILT) else None,
            "bd": int(r.TOTALBEDROOMS) if pd.notna(r.TOTALBEDROOMS) else None,
            "ba": float(r.TOTALBATHROOMS) if pd.notna(r.TOTALBATHROOMS) else None,
            "ok": enough, "nc": int(len(c)), "tier": tiers[i],
        }
        if enough:
            adj = c.adj.to_numpy()
            entry |= {"e": int(round(r.est, -3)), "lo": int(round(r.low, -3)), "hi": int(round(r.high, -3)),
                      "lo50": int(round(r.low50, -3)), "hi50": int(round(r.high50, -3)),
                      "n": int(round(r.est_now, -3)), "nlo": int(round(r.low_now, -3)), "nhi": int(round(r.high_now, -3)),
                      "nlo50": int(round(r.low50_now, -3)), "nhi50": int(round(r.high50_now, -3)),
                      "pct": round(float((adj < r.TOTALVALUE).mean()), 2),
                      "cm": int(round(float(np.median(adj)), -3)),
                      "c": [[x.county_addr, x.SALE_DATE.strftime("%Y-%m"), int(x.SALE_PRICE),
                             int(round(x.adj, -3)), int(x.ABOVEGROUNDAREA), int(x.YEARBUILT),
                             None if pd.isna(x.TOTALBEDROOMS) else int(x.TOTALBEDROOMS),
                             None if pd.isna(x.TOTALBATHROOMS) else float(x.TOTALBATHROOMS)]
                            for x in c.head(MAX_COMPS).itertuples()]}
        by_zip.setdefault(zc, {})[addr] = entry
        index[addr] = zc
    for zc, entries in by_zip.items():
        (OUT / "zip" / f"{zc}.json").write_text(json.dumps(entries, separators=(",", ":")), encoding="utf-8")
    (OUT / "addresses.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")

    backtest = json.loads((M.DATA / "backtest.json").read_text())
    summary = {
        "assessment_year": ASMT_YEAR, "value_date": VALUE_DATE, "built": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "parcels": int(len(res)), "with_context": int(sum(e["ok"] for z in by_zip.values() for e in z.values())),
        "training_sales": int(res.attrs["train_sales"]), "estimate_month": now.strftime("%Y-%m"),
        "backtest": {y: v["accuracy"] for y, v in backtest.items()},
        "flag_backtest": {y: next(g for g in v["grid"] if g["model_margin"] == 0 and g["comp_margin"] == 0.1 and g["min_comps"] == 5)
                          for y, v in backtest.items()},
        "fairness": fairness(res, after),
        "fairness_window": f"sales {after.SALE_DATE.min():%b %Y}–{after.SALE_DATE.max():%b %Y}",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    build_neighborhoods.main()
    print(json.dumps({k: summary[k] for k in ["parcels", "with_context", "training_sales", "fairness_window"]}))
    print(json.dumps(summary["fairness"]["overall"]), [d["median_ratio"] for d in summary["fairness"]["by_price_decile"]])


if __name__ == "__main__":
    main()
