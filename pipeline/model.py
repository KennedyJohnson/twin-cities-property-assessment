"""Valuation model, comparable sales, conservative flags, and the backtest.

Joins Minneapolis building characteristics to Hennepin County sales, trains a
model of sale price from physical features + location + sale month (never the
assessor's own values), and calibrates a 90% prediction interval with split
conformal prediction.

A parcel is flagged "possibly over-assessed" only when BOTH:
  1. assessed value > upper end of the calibrated 90% interval, and
  2. >= MIN_COMPS time-adjusted comparable sales have a median below
     assessed value by at least COMP_MARGIN.

Backtest: train only on sales before the valuation date of an earlier
assessment year, flag with that year's assessments, and check the flags
against sales that happened afterwards.

Usage: python pipeline/model.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neighbors import BallTree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

ALPHA = 0.10          # 90% prediction interval
MIN_COMPS = 5
COMP_MARGIN = 0.10    # comps' median must be >=10% below assessed value
COMP_RADIUS_FT = 2640  # half a mile (Minneapolis X/Y are in feet)
COMP_MONTHS = 24
MIN_SALE = 50_000
TRAIN_YEARS = 5       # older sales drift too far from today's market
PERMIT_YEARS = 5      # permit look-back window

NUMERIC = ["ABOVEGROUNDAREA", "BASEMENTAREA", "PARCELAREA", "YEARBUILT", "STORIES", "GARAGESTALLS",
           "TOTALBEDROOMS", "TOTALBATHROOMS", "FIREPLACES", "X", "Y", "months",
           "permits_n", "permits_major", "permit_fees_log", "years_since_major",
           "prior_sale_adj_log", "years_since_prior",
           "housing_cases", "nuisance_cases", "vacant_building", "rental", "rental_tier"]
CATEGORICAL = ["NEIGHBORHOOD", "CONSTRUCTIONTYPE", "EXTERIORWALL", "PRIMARYHEATING", "ROOF", "ZONING"]
SUFFIXES = {"ST", "AVE", "RD", "DR", "PL", "LN", "CT", "BLVD", "TER", "PKWY", "CIR", "WAY", "TRL", "HWY", "PKY",
            "N", "S", "E", "W", "NE", "SE", "NW", "SW"}


def street_core(s):
    t = str(s).upper().split()
    while t and t[-1] in SUFFIXES:
        t.pop()
    return " ".join(t)


def address_key(house_no, street, zip_code):
    num = pd.to_numeric(house_no, errors="coerce").astype("Int64").astype(str)
    zc = pd.to_numeric(zip_code, errors="coerce").astype("Int64").astype(str)
    return num + "|" + street.map(street_core) + "|" + zc


def load(asmt_year, county_file):
    """One row per Minneapolis single-family parcel, with its latest county sale."""
    m = pd.read_csv(DATA / f"minneapolis_{asmt_year}.csv.gz", low_memory=False)
    m = m[(m.BUILDINGUSE == "Single Family House") & (m.NUMBEROFBUILDINGS.fillna(1) == 1)]
    m["key"] = address_key(m.HOUSE_NO, m.ADRSTR, m.ZIP1)
    m = m[~m.key.duplicated(keep=False)]

    h = pd.read_csv(DATA / county_file, parse_dates=["SALE_DATE"], low_memory=False)
    h = h[h.MUNIC_NM == "MINNEAPOLIS"].copy()
    h["key"] = address_key(h.HOUSE_NO, h.STREET_NM, h.ZIP_CD)
    h = h[~h.key.duplicated(keep=False)]
    # The county's street names keep the direction (e.g. "LINCOLN ST NE"), which the city's sometimes drops.
    h["county_addr"] = (pd.to_numeric(h.HOUSE_NO, errors="coerce").astype("Int64").astype(str) + " "
                        + h.FRAC_HOUSE_NO.fillna("").astype(str).str.strip() + " " + h.STREET_NM.astype(str))
    h["county_addr"] = h.county_addr.str.split().str.join(" ").str.replace(r" ([NS]) ([EW])$", r" \1\2", regex=True)
    cols = ["key", "PID", "county_addr", "SALE_DATE", "SALE_PRICE", "SALE_CODE_NAME", "PETITION_REVIEW_IND"]
    df = m.merge(h[cols], on="key", how="left", indicator=True)
    df["matched"] = df._merge == "both"
    return df.drop(columns="_merge")


def qualified_sales(df):
    q = df[df.matched & (df.SALE_CODE_NAME == "WARRANTY DEED") & (df.SALE_PRICE >= MIN_SALE)
           & df.ABOVEGROUNDAREA.gt(300) & df.SALE_DATE.notna()]
    # Drop extreme price-per-sqft outliers (likely data errors or non-market sales).
    ppsf = q.SALE_PRICE / q.ABOVEGROUNDAREA
    lo, hi = ppsf.quantile([0.01, 0.99])
    return q[ppsf.between(lo, hi)]


def _digits(s):
    return s.astype(str).str.replace(r"\.0$", "", regex=True).str.replace(r"\D", "", regex=True)


def permit_features(df, ref_dates):
    """Permit history in the PERMIT_YEARS before each row's reference date (no look-ahead)."""
    p = pd.read_csv(DATA / "permits_sfd.csv.gz", parse_dates=["issueDate"], low_memory=False)
    p = p[p.status.ne("Cancelled") & p.issueDate.notna()].assign(pid=lambda d: _digits(d.APN))
    p["major"] = p.workType.isin(["Remodel", "Addition", "NewRes", "New"]) | p.comments.str.contains(
        r"remodel|addition|kitchen|renovat|finish(?:ed|ing)? basement", case=False, na=False)
    rows = pd.DataFrame({"row": range(len(df)), "pid": _digits(df.PID).to_numpy(), "ref": ref_dates.to_numpy()})
    j = rows.merge(p[["pid", "issueDate", "major", "totalFees"]], on="pid")
    j = j[(j.issueDate < j.ref) & (j.issueDate >= j.ref - pd.DateOffset(years=PERMIT_YEARS))]
    g = j.groupby("row")
    last_major = j[j.major].groupby("row").apply(lambda d: (d.ref.iloc[0] - d.issueDate.max()).days / 365.25)
    out = pd.DataFrame(index=range(len(df)))
    out["permits_n"] = g.size()
    out["permits_major"] = j[j.major].groupby("row").size()
    out["permit_fees_log"] = np.log1p(g.totalFees.sum())
    out["years_since_major"] = last_major
    out[["permits_n", "permits_major", "permit_fees_log"]] = out[["permits_n", "permits_major", "permit_fees_log"]].fillna(0)
    out["years_since_major"] = out.years_since_major.fillna(PERMIT_YEARS + 1)
    return out.set_index(df.index)


def _pid(s):
    return pd.to_numeric(_digits(s), errors="coerce")


def all_sales():
    """Every recorded sale: MetroGIS annual snapshots plus the current county file."""
    hist = pd.read_csv(DATA / "sale_history.csv.gz", parse_dates=["SALE_DATE"])
    hist = pd.DataFrame({"pid": _pid(hist.COUNTY_PIN), "date": hist.SALE_DATE, "price": hist.SALE_VALUE})
    cur = pd.read_csv(sorted(DATA.glob("hennepin_*.csv.gz"))[-1], usecols=["PID", "MUNIC_NM", "SALE_DATE", "SALE_PRICE"],
                      parse_dates=["SALE_DATE"], low_memory=False)
    cur = cur[cur.MUNIC_NM == "MINNEAPOLIS"]
    cur = pd.DataFrame({"pid": _pid(cur.PID), "date": cur.SALE_DATE, "price": cur.SALE_PRICE})
    s = pd.concat([hist, cur]).dropna()
    s = s[s.price >= MIN_SALE]
    s["month"] = s.date.dt.to_period("M")
    return s.drop_duplicates(["pid", "month"])


_SALES = None


def prior_sale_features(df, ref_dates):
    """The home's most recent earlier sale, adjusted to the reference month with a trailing market index."""
    global _SALES
    if _SALES is None:
        _SALES = all_sales()
    s = _SALES
    # Trailing index, shifted a month so the reference month never uses its own (possibly later) sales.
    idx = np.exp(s.groupby("month").price.apply(lambda p: np.log(p).median()).rolling(3, min_periods=1).mean().shift(1))
    idx = idx.bfill()
    rows = pd.DataFrame({"row": range(len(df)), "pid": _pid(df.PID).to_numpy(),
                         "ref": ref_dates.dt.to_period("M").to_numpy()})
    j = rows.merge(s[["pid", "month", "price"]], on="pid")
    j = j[j.month < j.ref].sort_values("month").groupby("row").last()
    ref_idx = j.ref.map(idx).astype(float).fillna(idx.iloc[-1])
    out = pd.DataFrame(index=range(len(df)))
    out["prior_sale_adj_log"] = np.log(j.price * ref_idx / j.month.map(idx).astype(float))
    out["years_since_prior"] = (j.ref - j.month).apply(lambda d: d.n / 12)
    return out.set_index(df.index)  # NaN when there is no earlier sale; the model handles missing values


_CONDITION = None


def condition_features(df, ref_dates):
    """Inspection and rental-license history before each row's reference date (no look-ahead).

    Housing/nuisance inspection cases in the PERMIT_YEARS window, whether the home was ever
    in the Vacant Building Registration program, and rental license status and tier.
    """
    global _CONDITION
    if _CONDITION is None:
        insp = pd.read_csv(DATA / "inspections.csv.gz", parse_dates=["Completed_Date"], low_memory=False)
        insp = insp.dropna(subset=["Completed_Date"]).assign(pid=lambda d: _pid(d.APN))
        insp = insp.groupby(["pid", "Violation_Case_Number", "Case_Type"], as_index=False).Completed_Date.min()
        rent = pd.read_csv(DATA / "rental_licenses.csv.gz", parse_dates=["issueDate"]).assign(pid=lambda d: _pid(d.apn))
        rent["tier_n"] = pd.to_numeric(rent.tier.str.extract(r"(\d)")[0], errors="coerce")
        _CONDITION = insp, rent
    insp, rent = _CONDITION
    rows = pd.DataFrame({"row": range(len(df)), "pid": _pid(df.PID).to_numpy(), "ref": ref_dates.to_numpy()})

    j = rows.merge(insp, on="pid")
    j = j[j.Completed_Date < j.ref]
    recent = j[j.Completed_Date >= j.ref - pd.DateOffset(years=PERMIT_YEARS)]
    out = pd.DataFrame(index=range(len(df)))
    out["housing_cases"] = recent[recent.Case_Type.isin(["HIS", "FIS"])].groupby("row").size()
    out["nuisance_cases"] = recent[recent.Case_Type == "Nuisance"].groupby("row").size()
    out["vacant_building"] = j[j.Case_Type == "VBR"].groupby("row").size().clip(upper=1)

    r = rows.merge(rent[["pid", "issueDate", "tier_n"]], on="pid")
    r = r[r.issueDate < r.ref]
    out["rental"] = r.groupby("row").size().clip(upper=1)
    out["rental_tier"] = r.groupby("row").tier_n.max()
    cols = ["housing_cases", "nuisance_cases", "vacant_building", "rental"]
    out[cols] = out[cols].fillna(0)
    return out.set_index(df.index)


def features(df, value_date):
    X = df.copy()
    ref = pd.Timestamp(value_date)
    sale = X.SALE_DATE.fillna(ref)
    X["months"] = (sale.dt.year - ref.year) * 12 + (sale.dt.month - ref.month)
    X = X.join(permit_features(X, sale)).join(prior_sale_features(X, sale)).join(condition_features(X, sale))
    for c in CATEGORICAL:
        X[c] = X[c].astype("category")
    return X[NUMERIC + CATEGORICAL]


def fit_interval_model(train, value_date, seed=0):
    """Median + quantile models on log price, then split-conformal calibration (CQR).

    The calibration set is the most recent 20% of sales, which are closest to the
    valuation date, so the interval accounts for drift between training and prediction.
    """
    train = train.sort_values("SALE_DATE")
    cut = int(len(train) * 0.8)
    fit, cal = train.iloc[:cut], train.iloc[cut:]
    y_fit, y_cal = np.log(fit.SALE_PRICE), np.log(cal.SALE_PRICE)

    def hgb(**kw):
        return HistGradientBoostingRegressor(max_iter=600, learning_rate=0.05, max_leaf_nodes=31,
                                             min_samples_leaf=30, l2_regularization=1.0,
                                             categorical_features="from_dtype", random_state=seed, **kw)

    Xf, Xc = features(fit, value_date), features(cal, value_date)
    mid = hgb().fit(Xf, y_fit)
    lo = hgb(loss="quantile", quantile=ALPHA / 2).fit(Xf, y_fit)
    hi = hgb(loss="quantile", quantile=1 - ALPHA / 2).fit(Xf, y_fit)
    # Conformity score: how far outside the raw quantile band each calibration sale falls.
    scores = np.maximum(lo.predict(Xc) - y_cal, y_cal - hi.predict(Xc))
    n = len(scores)
    q = np.quantile(scores, min(1, np.ceil((n + 1) * (1 - ALPHA)) / n))
    # Refit on all sales so the most recent market is in the model; keep the calibrated margin.
    Xa, ya = features(train, value_date), np.log(train.SALE_PRICE)
    mid, lo, hi = hgb().fit(Xa, ya), hgb(loss="quantile", quantile=ALPHA / 2).fit(Xa, ya),         hgb(loss="quantile", quantile=1 - ALPHA / 2).fit(Xa, ya)
    return mid, lo, hi, q


def predict(models, df, value_date):
    mid, lo, hi, q = models
    X = features(df.assign(SALE_DATE=pd.NaT), value_date)  # value as of the valuation date
    return np.exp(mid.predict(X)), np.exp(lo.predict(X) - q), np.exp(hi.predict(X) + q)


def market_index(sales):
    """Monthly citywide median price-per-sqft index, used to time-adjust comps."""
    s = sales.assign(m=sales.SALE_DATE.dt.to_period("M"), ppsf=sales.SALE_PRICE / sales.ABOVEGROUNDAREA)
    idx = s.groupby("m").ppsf.median().rolling(3, center=True, min_periods=1).median()
    return idx


def comps(parcels, sales, value_date):
    """Time-adjusted median price of nearby similar sales, for every parcel."""
    ref = pd.Timestamp(value_date).to_period("M")
    window = sales[(sales.SALE_DATE.dt.to_period("M") <= ref)
                   & (sales.SALE_DATE >= pd.Timestamp(value_date) - pd.DateOffset(months=COMP_MONTHS))].copy()
    idx = market_index(sales)
    base = idx.get(ref, idx[idx.index <= ref].iloc[-1])
    window["adj_price"] = window.SALE_PRICE * base / window.SALE_DATE.dt.to_period("M").map(idx).astype(float)

    tree = BallTree(window[["X", "Y"]].to_numpy())
    near = tree.query_radius(parcels[["X", "Y"]].to_numpy(), r=COMP_RADIUS_FT)
    area_w, year_w, price_w, pid_w = (window[c].to_numpy() for c in ["ABOVEGROUNDAREA", "YEARBUILT", "adj_price", "PID"])
    med, count = np.full(len(parcels), np.nan), np.zeros(len(parcels), dtype=int)
    area_p, year_p, pid_p = (parcels[c].to_numpy() for c in ["ABOVEGROUNDAREA", "YEARBUILT", "PID"])
    for i, cand in enumerate(near):
        if not area_p[i] > 0:
            continue
        ok = cand[(np.abs(area_w[cand] / area_p[i] - 1) <= 0.20)
                  & (np.abs(year_w[cand] - year_p[i]) <= 15)
                  & (pid_w[cand] != pid_p[i])]  # a home is never its own comparable
        count[i] = len(ok)
        if len(ok):
            med[i] = np.median(price_w[ok])
    return med, count


def assess(parcels, sales_before, value_date):
    sales_before = sales_before[sales_before.SALE_DATE >= pd.Timestamp(value_date) - pd.DateOffset(years=TRAIN_YEARS)]
    models = fit_interval_model(sales_before, value_date)
    est, low, high = predict(models, parcels, value_date)
    comp_med, comp_n = comps(parcels, sales_before, value_date)
    out = parcels.assign(est=est, low=low, high=high, comp_median=comp_med, comp_n=comp_n)
    out.attrs["train_sales"] = len(sales_before)
    return out


def apply_flags(out, model_margin=0.0, comp_margin=COMP_MARGIN, min_comps=MIN_COMPS):
    """Status for each parcel. Margins are extra room beyond the interval / comps before flagging."""
    complete = out.ABOVEGROUNDAREA.gt(300) & out.YEARBUILT.gt(1800) & out.matched & (out.PETITION_REVIEW_IND != "T")
    over_model = out.TOTALVALUE > out.high * (1 + model_margin)
    over_comps = out.comp_median <= out.TOTALVALUE * (1 - comp_margin)
    return pd.Series(np.select([~complete | (out.comp_n < min_comps), over_model & over_comps],
                               ["not_enough_data", "possibly_over"], "in_line"), index=out.index)


def backtest_frame(asmt_year, county_file):
    """Assess with data available before the valuation date; attach the sale that happened afterwards."""
    value_date = f"{asmt_year}-01-01"
    df = load(asmt_year, county_file)
    sales = qualified_sales(df)
    before = sales[sales.SALE_DATE < value_date]
    after = sales[(sales.SALE_DATE >= value_date) & (sales.SALE_DATE < f"{asmt_year}-10-01")]
    res = assess(df, before, value_date).set_index("key")
    test = res.loc[after.key].assign(later_price=after.SALE_PRICE.to_numpy())
    return res, test


def score(res, test, **flag_kw):
    status_all, status = apply_flags(res, **flag_kw), apply_flags(test, **flag_kw)
    flagged = test[status == "possibly_over"]
    in_line = test[status == "in_line"]
    return {
        "flagged_share_all_parcels": float((status_all == "possibly_over").mean()),
        "not_enough_data_share": float((status_all == "not_enough_data").mean()),
        "flagged_test_sales": int(len(flagged)),
        "flagged_sold_at_or_above_assessed": float((flagged.later_price >= flagged.TOTALVALUE).mean()) if len(flagged) else None,
        "flagged_median_sale_to_assessed": float((flagged.later_price / flagged.TOTALVALUE).median()) if len(flagged) else None,
        "in_line_sold_below_90pct_of_assessed": float((in_line.later_price < 0.9 * in_line.TOTALVALUE).mean()),
    }


def accuracy(res, test):
    return {
        "train_sales": res.attrs["train_sales"], "test_sales": int(len(test)),
        "model_median_abs_pct_error": float(np.median(np.abs(test.est / test.later_price - 1))),
        "assessor_median_abs_pct_error": float(np.median(np.abs(test.TOTALVALUE / test.later_price - 1))),
        "interval_coverage": float(((test.later_price >= test.low) & (test.later_price <= test.high)).mean()),
    }


if __name__ == "__main__":
    grid = [dict(model_margin=mm, comp_margin=cm, min_comps=mc)
            for mm in (0.0, 0.05, 0.10) for cm in (0.10, 0.15, 0.20) for mc in (5, 8)]
    report = {}
    for year in (2025, 2026):
        res, test = backtest_frame(year, "hennepin_202609.csv.gz")
        report[year] = {"accuracy": accuracy(res, test), "grid": [{**g, **score(res, test, **g)} for g in grid]}
    print(json.dumps(report, indent=1))
    (DATA / "backtest.json").write_text(json.dumps(report, indent=1))
