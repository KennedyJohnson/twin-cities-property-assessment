"""Valuation model, comparable sales, conservative flags, and the backtest.

Joins Minneapolis building characteristics to Hennepin County sales and trains a
model of sale price from physical features, location, nearby sales and history
(never the assessor's own values). Time is handled outside the trees: a monthly
hedonic price index is estimated, the trees learn prices with the index removed,
and the index (trend + seasons) is projected to the month being estimated, so the
model gives an expected sale price for a given month. Likely (50%) and wide (90%)
ranges are calibrated with conformalized quantile regression.

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

ALPHA = 0.10          # wide range: 90% prediction interval (used for flags)
ALPHAS = (0.10, 0.50)  # wide (90%) and likely (50%) ranges
MIN_COMPS = 5
COMP_MARGIN = 0.10    # comps' median must be >=10% below assessed value
COMP_RADIUS_FT = 2640  # half a mile (Minneapolis X/Y are in feet)
COMP_MONTHS = 24
MIN_SALE = 50_000
TRAIN_YEARS = 5       # older sales drift too far from today's market
LAG_K = (10, 30)      # nearby-sales features: the 10 and 30 closest earlier sales
LAG_MONTHS = 24
SEEDS = 5             # the estimate averages this many models (lower variance)
PERMIT_YEARS = 5      # permit look-back window

NUMERIC = ["ABOVEGROUNDAREA", "BASEMENTAREA", "PARCELAREA", "YEARBUILT", "STORIES", "GARAGESTALLS",
           "TOTALBEDROOMS", "TOTALBATHROOMS", "FIREPLACES", "X", "Y",
           "permits_n", "permits_major", "permit_fees_log", "years_since_major",
           "prior_sale_adj_log", "years_since_prior",
           "housing_cases", "nuisance_cases", "vacant_building", "rental", "rental_tier",
           *[f"lag_{s}{k}" for k in LAG_K for s in ("med", "sd")], "lag_dist"]
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


def spatial_lag(pool, df, ref_dates):
    """Price per sq ft (index-adjusted, logged) of the nearest pool sales dated before each row's reference month.

    Median and spread of the LAG_K closest sales in the LAG_MONTHS before, plus the typical distance
    to the 10 closest. A home is never its own neighbor.
    """
    p = pool.assign(m=pool.SALE_DATE.dt.to_period("M"))
    lp = np.log(p.SALE_PRICE / p.ABOVEGROUNDAREA)
    idx = lp.groupby(p.m).median().rolling(3, center=True, min_periods=1).mean()
    v_all, xy_all, pid_all = (lp - p.m.map(idx).astype(float)).to_numpy(), p[["X", "Y"]].to_numpy(), p.PID.to_numpy()
    m_all = p.m.to_numpy()
    refm = ref_dates.dt.to_period("M").to_numpy()
    xy, pids = df[["X", "Y"]].to_numpy(dtype=float), df.PID.to_numpy()
    k = max(LAG_K) + 1
    out = np.full((len(df), 2 * len(LAG_K) + 1), np.nan)
    for r in pd.unique(refm):
        keep = (m_all < r) & (m_all >= r - LAG_MONTHS)
        ii = np.where((refm == r) & ~np.isnan(xy).any(axis=1))[0]
        if keep.sum() < k or not len(ii):
            continue
        dist, nb = BallTree(xy_all[keep]).query(xy[ii], k=k)
        own = pid_all[keep][nb] == pids[ii][:, None]
        v, dist = np.where(own, np.nan, v_all[keep][nb]), np.where(own, np.nan, dist)
        for j, kk in enumerate(LAG_K):
            out[ii, 2 * j] = np.nanmedian(v[:, :kk + 1], 1)
            out[ii, 2 * j + 1] = np.nanstd(v[:, :kk + 1], 1)
        out[ii, -1] = np.nanmedian(dist[:, :11], 1)
    names = [f"lag_{s}{kk}" for kk in LAG_K for s in ("med", "sd")] + ["lag_dist"]
    return pd.DataFrame(out, columns=names, index=df.index)


def features(df, value_date, pool):
    """Model inputs. History uses records before each sale (or before value_date when there is no sale)."""
    X = df.copy()
    ref = X.SALE_DATE.fillna(pd.Timestamp(value_date))
    X = (X.join(permit_features(X, ref)).join(prior_sale_features(X, ref)).join(condition_features(X, ref))
         .join(spatial_lag(pool, X, ref)))
    for c in CATEGORICAL:
        X[c] = X[c].astype("category")
    return X[NUMERIC + CATEGORICAL]


def _hgb(seed=0, **kw):
    params = dict(max_iter=600, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=30, l2_regularization=1.0,
                  categorical_features="from_dtype", random_state=seed)
    return HistGradientBoostingRegressor(**(params | kw))


def _months(d):
    return pd.PeriodIndex(d.SALE_DATE, freq="M")


def hedonic_index(X, y, months):
    """Monthly log price index: the typical price left over, month by month, after a model that can't see time."""
    idx = pd.Series(0.0, index=months.unique())
    for _ in range(2):
        resid = y - _hgb(max_iter=300).fit(X, y - idx.reindex(months).to_numpy()).predict(X)
        idx = pd.Series(resid, index=months).groupby(level=0).median().sort_index()
    return idx.rolling(3, center=True, min_periods=1).mean()


def index_at(idx, months):
    """Index for the given months. Months inside the data use it directly; later months are projected
    with the average seasonal pattern plus the straight-line trend of the last two years."""
    months = pd.PeriodIndex(months, freq="M")
    last = idx.index[-1]
    t = np.array([(m - last).n for m in idx.index])
    cal = idx.index.month.to_numpy()
    seas = (idx - idx.rolling(12, center=True, min_periods=6).mean()).groupby(cal).mean()
    seas -= seas.mean()
    level = idx.to_numpy() - seas.reindex(cal).to_numpy()
    recent = t > -24
    slope = np.polyfit(t[recent], level[recent], 1)[0]
    ahead = np.array([(m - last).n for m in months])
    # The last 12 months' average level is centred 5.5 months before the last month.
    fc = level[-12:].mean() + slope * (ahead + 5.5) + seas.reindex(months.month).to_numpy()
    known = idx.reindex(months).to_numpy()
    return np.where((ahead <= 0) & ~np.isnan(known), known, fc)


def fit_interval_model(train, value_date):
    """Bagged median model + quantile models on index-adjusted log price, with split-conformal calibration (CQR).

    Two ranges are calibrated: a likely range (50%) and a wide range (90%). The calibration set is
    the most recent 20% of sales, scored with the index *projected* from the older 80%, so the
    ranges include the error of projecting prices forward.
    """
    train = train.sort_values("SALE_DATE")
    cut = int(len(train) * 0.8)
    fit, cal = train.iloc[:cut], train.iloc[cut:]

    def quantile_pair(alpha, X, y):
        return (_hgb(loss="quantile", quantile=alpha / 2).fit(X, y),
                _hgb(loss="quantile", quantile=1 - alpha / 2).fit(X, y))

    Xf, Xa = features(fit, value_date, fit), features(train, value_date, train)
    # Calibration homes are estimated as if from the end of `fit`, like real estimates.
    Xc = features(cal.assign(SALE_DATE=pd.NaT), fit.SALE_DATE.max() + pd.Timedelta(days=1), fit)
    yf, ya, yc = (np.log(d.SALE_PRICE.to_numpy()) for d in (fit, train, cal))
    idx_f, idx_a = hedonic_index(Xf, yf, _months(fit)), hedonic_index(Xa, ya, _months(train))
    yf_adj = yf - idx_f.reindex(_months(fit)).to_numpy()
    ya_adj = ya - idx_a.reindex(_months(train)).to_numpy()
    yc_adj = yc - index_at(idx_f, _months(cal))
    ranges = {}
    for alpha in ALPHAS:
        lo, hi = quantile_pair(alpha, Xf, yf_adj)
        # Conformity score: how far outside the raw quantile band each calibration sale falls.
        scores = np.maximum(lo.predict(Xc) - yc_adj, yc_adj - hi.predict(Xc))
        n = len(scores)
        q = np.quantile(scores, min(1, np.ceil((n + 1) * (1 - alpha)) / n))
        # Refit on all sales so the most recent market is in the model; keep the calibrated margin.
        ranges[alpha] = (*quantile_pair(alpha, Xa, ya_adj), q)
    mids = [_hgb(seed).fit(Xa, ya_adj) for seed in range(SEEDS)]
    return dict(mids=mids, ranges=ranges, idx=idx_a, pool=train, value_date=value_date)


def predict(models, df, when=None):
    """Expected sale price in month `when` (one date, or one per row; default the valuation date's month),
    plus {alpha: (low, high)}. Uses only information from before the model's valuation date."""
    X = features(df.assign(SALE_DATE=pd.NaT), models["value_date"], models["pool"])
    when = pd.Timestamp(models["value_date"]) if when is None else when
    when = pd.DatetimeIndex(np.broadcast_to(np.datetime64(pd.Timestamp(when)), len(df))
                            if isinstance(when, (str, pd.Timestamp)) else pd.to_datetime(when))
    level = index_at(models["idx"], when.to_period("M"))
    mid = np.mean([mdl.predict(X) for mdl in models["mids"]], axis=0)
    return np.exp(mid + level), {a: (np.exp(lo.predict(X) + level - q), np.exp(hi.predict(X) + level + q))
                                 for a, (lo, hi, q) in models["ranges"].items()}


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


def assess(parcels, sales_before, value_date, model_sales=None):
    """Estimates for every parcel at the valuation date, plus comparable sales.

    The model trains on `model_sales` (default: the sales before the valuation date); comps always
    use the sales before the valuation date. The fitted model is kept in out.attrs["models"] so
    callers can estimate other months with predict().
    """
    sales_before = sales_before[sales_before.SALE_DATE >= pd.Timestamp(value_date) - pd.DateOffset(years=TRAIN_YEARS)]
    if model_sales is None:
        model_sales, info_date = sales_before, pd.Timestamp(value_date)
    else:
        info_date = model_sales.SALE_DATE.max() + pd.Timedelta(days=1)
        model_sales = model_sales[model_sales.SALE_DATE >= info_date - pd.DateOffset(years=TRAIN_YEARS)]
    models = fit_interval_model(model_sales, info_date)
    est, ranges = predict(models, parcels, pd.Timestamp(value_date))
    (low, high), (low50, high50) = ranges[0.10], ranges[0.50]
    comp_med, comp_n = comps(parcels, sales_before, value_date)
    out = parcels.assign(est=est, low=low, high=high, low50=low50, high50=high50,
                         comp_median=comp_med, comp_n=comp_n)
    out.attrs["train_sales"] = len(model_sales)
    out.attrs["models"] = models
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
    res = assess(df, before, value_date)
    models = res.attrs["models"]
    res = res.set_index("key")
    test = res.loc[after.key].assign(later_price=after.SALE_PRICE.to_numpy())
    # The model is scored on its expected price for the month each home actually sold.
    est, ranges = predict(models, test.reset_index(), after.SALE_DATE.to_numpy())
    test = test.assign(est=est, low=ranges[0.10][0], high=ranges[0.10][1], low50=ranges[0.50][0], high50=ranges[0.50][1])
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
        "model_median_ratio": float(np.median(test.est / test.later_price)),
        "assessor_median_ratio": float(np.median(test.TOTALVALUE / test.later_price)),
        "assessor_median_abs_pct_error": float(np.median(np.abs(test.TOTALVALUE / test.later_price - 1))),
        "interval_coverage": float(((test.later_price >= test.low) & (test.later_price <= test.high)).mean()),
        "likely_range_coverage": float(((test.later_price >= test.low50) & (test.later_price <= test.high50)).mean()),
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
