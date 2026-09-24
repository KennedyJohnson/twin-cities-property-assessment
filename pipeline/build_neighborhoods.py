"""Per-neighborhood assessment summary for the Twin Cities Living Quality Map.

Reads the per-ZIP home files build_site.py writes and emits site/data/neighborhoods.json:
  {"built": ..., "neighborhoods": {"COOPER": {"homes": n, "compared": n, "median_ratio": r,
                                              "share_high": s, "share_low": s}, ...}}
median_ratio is the city's value over our January estimate (1.0 = in line). A home counts as
high/low only when both checks agree, same rule as the per-home verdict in site/app.js.
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site" / "data"
# Assessor abbreviations -> the city's official neighborhood names the map uses.
ALIASES = {
    "CEDAR RSIDE/WEST BANK": "CEDAR RIVERSIDE",
    "COLUMBIA": "COLUMBIA PARK",
    "NICOLLET IS/EAST BANK": "NICOLLET ISLAND - EAST BANK",
    "PROSPECT PK/E RIVER RD": "PROSPECT PARK - EAST RIVER ROAD",
    "STEVENS SQ/LORING HGTS": "STEVEN'S SQUARE - LORING HEIGHTS",
}


def main():
    groups = defaultdict(list)
    for f in sorted((OUT / "zip").glob("*.json")):
        for h in json.loads(f.read_text(encoding="utf-8")).values():
            if h.get("nb"):
                groups[ALIASES.get(h["nb"], h["nb"])].append(h)
    out = {}
    for nb, homes in sorted(groups.items()):
        ok = [h for h in homes if h.get("ok")]
        if len(ok) < 10:
            continue
        high = sum(h["pct"] >= 0.8 and h["v"] > h["hi50"] for h in ok)
        low = sum(h["pct"] <= 0.2 and h["v"] < h["lo50"] for h in ok)
        out[nb] = {
            "homes": len(homes),
            "compared": len(ok),
            "median_ratio": round(statistics.median(h["v"] / h["e"] for h in ok), 3),
            "share_high": round(high / len(ok), 3),
            "share_low": round(low / len(ok), 3),
        }
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    doc = {"built": summary["built"], "assessment_year": summary["assessment_year"], "neighborhoods": out}
    (OUT / "neighborhoods.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"{len(out)} neighborhoods")


if __name__ == "__main__":
    main()
