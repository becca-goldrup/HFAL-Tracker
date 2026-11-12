"""
Part 2: turn the tracker spreadsheet into data for the dashboard website (docs/).

    python tools/build_dashboard.py            # newest spreadsheet (data/output, else data/input)
    python tools/build_dashboard.py --input path/to/file.xlsx

Writes docs/data/hospitals.json, which docs/index.html reads. Map coordinates and
counties are looked up once (US Census geocoder, OpenStreetMap as a fallback) and
remembered in data/geocode.json, so later builds don't look them up again.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from hfal.criteria import GRADED, LABELS, NO, REVIEW, TEXT_COLUMNS, YES  # noqa: E402
from hfal.spreadsheet import Tracker, grade_row  # noqa: E402
from openpyxl.utils import column_index_from_string as col  # noqa: E402

DOCS = config.ROOT / "docs"
GEOCACHE = config.ROOT / "data" / "geocode.json"
UA = {"User-Agent": "HFAL-Tracker/1.0 (hospital financial assistance compliance dashboard)"}


# ---------------------------------------------------------------- geocoding
def _addr(h: dict) -> str:
    return f"{h['address']}, {h['city']}, NY {h['zip']}".strip(", ")


def _county_name(lat: float, lon: float) -> str:
    """County name for a point, from the Census geocoder (no API key needed)."""
    try:
        r = requests.get("https://geocoding.geo.census.gov/geocoder/geographies/coordinates", headers=UA,
                         timeout=60, params={"x": lon, "y": lat, "benchmark": "Public_AR_Current",
                                             "vintage": "Current_Current", "layers": "Counties", "format": "json"})
        return r.json()["result"]["geographies"]["Counties"][0]["NAME"]
    except Exception:
        return ""


def geocode(hospitals: list[dict]) -> dict:
    cache = json.loads(GEOCACHE.read_text()) if GEOCACHE.exists() else {}
    todo = [h for h in hospitals if _addr(h) not in cache]
    if todo:
        print(f"Looking up {len(todo)} address(es) with the US Census geocoder...")
        buf = io.StringIO()
        w = csv.writer(buf)
        for i, h in enumerate(todo):
            w.writerow([i, h["address"], h["city"], "NY", h["zip"]])
        r = requests.post("https://geocoding.geo.census.gov/geocoder/geographies/addressbatch",
                          files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
                          data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
                          headers=UA, timeout=600)
        r.raise_for_status()
        for row in csv.reader(io.StringIO(r.text)):
            if len(row) < 3:
                continue
            h = todo[int(row[0])]
            if row[2] == "Match" and len(row) >= 10:
                lon, lat = (float(x) for x in row[5].split(","))
                cache[_addr(h)] = {"lat": lat, "lon": lon, "county_fips": row[9], "source": "census"}
        # One name lookup per county, shared by every hospital in it.
        names: dict[str, str] = {}
        for v in cache.values():
            f = v.get("county_fips")
            if f and f not in names:
                names[f] = _county_name(v["lat"], v["lon"])
        for v in cache.values():
            if v.get("county_fips"):
                v["county"] = names.get(v["county_fips"], "")
        # Fallback: OpenStreetMap (1 request per second, per its usage policy).
        for h in todo:
            if _addr(h) in cache:
                continue
            time.sleep(1.1)
            r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=60,
                             params={"q": f"{h['name']}, {h['city']}, NY", "format": "json", "limit": 1,
                                     "countrycodes": "us", "addressdetails": 1})
            hits = r.json() if r.ok else []
            if not hits:
                r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=60,
                                 params={"q": _addr(h), "format": "json", "limit": 1, "countrycodes": "us",
                                         "addressdetails": 1})
                hits = r.json() if r.ok else []
            if hits:
                a = hits[0].get("address", {})
                cache[_addr(h)] = {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]),
                                   "county": a.get("county", "").replace(" County", "") + (" County" if a.get("county") else ""),
                                   "source": "openstreetmap"}
            else:
                print(f"  ! no map location found for {h['name']} ({_addr(h)})")
        GEOCACHE.parent.mkdir(parents=True, exist_ok=True)
        GEOCACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return cache


# ---------------------------------------------------------------- data
def _status(v) -> str:
    """Cell value -> yes / no / review / unknown, for display."""
    if v is None or str(v).strip() == "":
        return "unknown"
    if isinstance(v, (int, float)):
        return "yes" if v >= 4 else "no"
    s = str(v).strip()
    if s.lower() in ("yes", "no"):
        return s.lower()
    if s.upper() == REVIEW:
        return "review"
    if s[:1].isdigit():
        n = float(s.split("%")[0].split()[0])
        return "yes" if (n >= 400 or 4 <= n < 100) else "no"
    return "unknown"


def _text(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.upper() in ("N/A", "NA", "NONE") else s


def build(src: Path) -> dict:
    t = Tracker(src)
    ws = t.ws
    hospitals = t.hospitals()
    geo = geocode(hospitals)
    other_notes_col = next((c for c in range(1, ws.max_column + 1) if ws.cell(2, c).value == "Other Notes"), None)
    out = []
    for h in hospitals:
        r = h["row"]
        g = grade_row(t.last_values(r))
        loc = geo.get(_addr(h), {})
        max_fpl = ws.cell(r, col("AI")).value
        rec = {
            "id": r, "name": h["name"], "address": h["address"], "city": h["city"], "zip": str(h["zip"] or ""),
            "system": h["system"] or "Independent", "nyc": bool(ws.cell(r, col("E")).value),
            "county": loc.get("county", ""), "lat": loc.get("lat"), "lon": loc.get("lon"),
            "hfa_url": h["hfa_url"],
            "grade": g["grade"], "grade_best": g["grade_best"], "grade_worst": g["grade_worst"],
            "auto_fail": g["auto_fail"], "issues": g["n_no"], "needs_review": g["n_review"],
            "criteria": {c.key: _status(ws.cell(r, col(c.column)).value) for c in GRADED},
            "max_fpl": (f"{int(max_fpl * 100)}%" if isinstance(max_fpl, (int, float)) else _text(max_fpl)),
            "notes": {k: _text(ws.cell(r, col(letter)).value) for k, letter in TEXT_COLUMNS.items()},
            "last_checked": _text(ws.cell(r, t.new_col["AI Last Checked"]).value),
        }
        if other_notes_col:
            rec["notes"]["other_notes"] = _text(ws.cell(r, other_notes_col).value)
        out.append(rec)

    changes = []
    if "AI Change Log" in t.wb.sheetnames:
        log = t.wb["AI Change Log"]
        for row in list(log.iter_rows(min_row=2, values_only=True))[-300:]:
            if row[0]:
                changes.append({"date": str(row[0]), "hospital": row[1], "field": row[3],
                                "old": "" if row[4] is None else str(row[4]),
                                "new": "" if row[5] is None else str(row[5])})
    is_ai = src.parent.resolve() == config.OUTPUT_DIR.resolve()
    return {
        "generated": date.today().isoformat(),
        "source": (f"AI-assisted check ({src.stem.replace('hfal-tracker-', '')})" if is_ai
                   else "CSS manual review, September 2025"),
        "fpl_year": config.FPL_YEAR,
        "policy_statement_auto_fail": config.POLICY_STATEMENT_AUTO_FAIL,
        "criteria": [{"key": c.key, "label": LABELS[c.key], "section": c.section,
                      "law": c.plain_language} for c in GRADED],
        "hospitals": out,
        "changes": list(reversed(changes)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="spreadsheet to use (default: newest in data/output, else data/input)")
    args = ap.parse_args()
    from run import pick_input
    src = pick_input(args.input)
    data = build(src)
    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    (DOCS / "data" / "hospitals.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    located = sum(1 for h in data["hospitals"] if h["lat"] is not None)
    print(f"From: {src}\nWrote docs/data/hospitals.json: {len(data['hospitals'])} hospitals, "
          f"{located} on the map, {len(data['changes'])} recent changes")


if __name__ == "__main__":
    main()
