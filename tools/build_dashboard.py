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
import re  # noqa: E402
from hfal import costs  # noqa: E402
from hfal.fetch import site_slug  # noqa: E402

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
    review, last_run = (review_queue(t), last_run_info(t)) if is_ai else ([], None)
    return {
        "repo": config.GITHUB_REPO,
        "review": review,
        "last_run": last_run,
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


# ---------------------------------------------------------------- CSS staff tab
_EVIDENCE = re.compile(r'^(D\d+): "(.*)"(?: \((https?://[^)]*)\))?$', re.S)


def review_queue(t: Tracker) -> list[dict]:
    """REVIEW items, one per (website, requirement), for the 'For CSS staff' tab."""
    if "AI Review Queue" not in t.wb.sheetnames:
        return []
    by_column = {c.column: c for c in GRADED}
    docs_by_site, systems = {}, {}
    for h in t.hospitals():
        cell = t.ws.cell(h["row"], t.new_col["AI Documents Reviewed"]).value or ""
        docs_by_site.setdefault(h["hfa_url"], dict(re.findall(r"^(D\d+): (\S+)$", cell, re.M)))
        systems.setdefault(h["hfa_url"], h["system"] or "Independent")
    still_review = {(h["name"], c.column) for h in t.hospitals() for c in GRADED
                    if t.ws.cell(h["row"], col(c.column)).value == REVIEW}
    items, notes = {}, {}
    for row in t.wb["AI Review Queue"].iter_rows(min_row=2, values_only=True):
        if not row or not row[1]:
            continue
        _, hospital, system, column, _, answer, conf, reason, evidence, link, _ = (list(row) + [None] * 11)[:11]
        link = link or ""
        if column == "-":
            notes.setdefault(link, [])
            if reason and reason not in notes[link]:
                notes[link].append(str(reason))
            continue
        if column not in by_column or (hospital, column) not in still_review:
            continue
        c = by_column[column]
        key = f"{site_slug(link)}|{column}"
        item = items.setdefault(key, {
            "id": key, "hfa_url": link, "system": systems.get(link, system or ""), "column": column,
            "key": c.key, "requirement": LABELS[c.key], "section": c.section, "law": c.plain_language,
            "ai_answer": answer or "", "confidence": conf or "", "reason": str(reason or ""),
            "evidence": [], "hospitals": [],
        })
        if hospital not in item["hospitals"]:
            item["hospitals"].append(hospital)
        if evidence and not item["evidence"]:
            site_docs = docs_by_site.get(link, {})
            for line in str(evidence).split("\n"):
                m = _EVIDENCE.match(line.strip())
                if m:
                    item["evidence"].append({"doc": m[1], "quote": m[2][:600], "url": m[3] or site_docs.get(m[1], "")})
                elif line.strip():
                    item["evidence"].append({"doc": "", "quote": line.strip()[:600], "url": ""})
    out = list(items.values())
    for it in out:
        it["site_notes"] = notes.get(it["hfa_url"], [])
        it["documents"] = docs_by_site.get(it["hfa_url"], {})
    out.sort(key=lambda it: (it["system"].lower(), it["hfa_url"], it["column"]))
    return out


def last_run_info(t: Tracker) -> dict | None:
    if "AI Run Log" not in t.wb.sheetnames:
        return None
    rows = [r for r in t.wb["AI Run Log"].iter_rows(min_row=2, values_only=True) if r and r[0]]
    if not rows:
        return None
    last = max(str(r[0]) for r in rows)
    latest = {}  # one entry per website: its most recent result that day
    for r in rows:
        if str(r[0]) == last:
            latest[r[1]] = r
    rows = list(latest.values())
    status = [str(r[2] or "") for r in rows]
    usage = {"input": sum(int(r[5] or 0) for r in rows), "output": sum(int(r[6] or 0) for r in rows)}
    return {"date": last, "model": costs.current_model(), "websites": len(rows),
            "graded": sum(s == "graded" for s in status), "unchanged": sum(s == "unchanged" for s in status),
            "problems": sum(s.startswith(("error", "skipped")) for s in status),
            "cost": round(costs.actual(usage), 2)}


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
