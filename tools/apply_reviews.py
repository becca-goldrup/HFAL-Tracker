"""
Apply CSS reviewers' decisions to the newest tracker spreadsheet.

Reviewers make decisions in the dashboard's "For CSS staff" tab, which downloads
a file like reviews-2026-11-12-jane.json. Uploading it to data/reviews/ on GitHub
runs this automatically; locally:

    python tools/apply_reviews.py

Each decision sets one requirement (yes / no) for every hospital that shares that
financial assistance page. Review decisions apply only where the cell is still
marked REVIEW (a newer AI check may have settled it already); corrections made
from the Data health tab ("override") apply to any answer. Applied files move to
data/reviews/applied/.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from hfal.criteria import GRADED, NO, REVIEW, YES  # noqa: E402
from hfal.fetch import site_slug  # noqa: E402
from hfal.spreadsheet import Tracker, _col  # noqa: E402
from run import pick_input  # noqa: E402

REVIEWS_DIR = config.ROOT / "data" / "reviews"
COLUMNS = {c.column for c in GRADED}


def main():
    files = sorted(f for f in REVIEWS_DIR.glob("*.json") if f.name != "publish.json")  # publish.json is a setting
    if not files:
        print("No review files in data/reviews/. Nothing to apply.")
        return
    src = pick_input(None)
    if src.parent.resolve() != config.OUTPUT_DIR.resolve():
        print("No AI-checked spreadsheet in data/output yet; decisions will be applied after the first check.")
        return
    tracker = Tracker(src)
    by_site, by_slug = {}, {}
    for h in tracker.hospitals():
        by_site.setdefault(h["hfa_url"], []).append(h)
        by_slug[site_slug(h["hfa_url"])] = h["hfa_url"]

    applied = skipped = 0
    for f in files:
        try:
            batch = json.loads(f.read_text())
            decisions = batch["decisions"]
        except Exception as e:
            print(f"  ! {f.name}: could not read ({e}); left in place")
            continue
        reviewer = str(batch.get("reviewer") or "CSS reviewer")[:80]
        when = str(batch.get("submitted") or date.today().isoformat())[:10]
        for d in decisions:
            # Compact form from the Submit to GitHub button: {"id": "<site>|<column>", "d": ..., "n": ..., "o": 1}
            if "id" in d and "|" in str(d["id"]) and not d.get("hfa_url"):
                slug, col = str(d["id"]).split("|", 1)
                d = {"hfa_url": by_slug.get(slug), "column": d.get("column") or col,
                     "decision": d.get("decision") or d.get("d"), "note": d.get("note") or d.get("n"),
                     "override": d.get("override") or d.get("o")}
            value, column = str(d.get("decision", "")).lower(), str(d.get("column", ""))
            if value not in (YES, NO) or column not in COLUMNS:
                skipped += 1
                continue
            hospitals = by_site.get(d.get("hfa_url"), [])
            override = bool(d.get("override"))  # a correction to an answer that wasn't flagged
            changed = False
            for h in hospitals:
                current = tracker.ws.cell(h["row"], _col(column)).value
                if current == REVIEW or override:
                    tracker.apply_decision(h, column, value, reviewer, when, str(d.get("note") or "")[:500])
                    changed = True
            applied += changed
            skipped += not changed
        dest = REVIEWS_DIR / "applied" / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        f.replace(dest)
        print(f"  {f.name}: {len(decisions)} decision(s) from {reviewer}")

    if not applied:
        # Nothing changed in the spreadsheet (the files are still recorded in data/reviews/applied/).
        print(f"Applied 0 decisions; {skipped} skipped because those answers were already settled "
              f"(or weren't a yes/no). No changes to the spreadsheet.")
        return
    tracker.run_date = date.fromisoformat(src.stem.replace("hfal-tracker-", "")).isoformat() \
        if src.stem.startswith("hfal-tracker-") else tracker.run_date  # keep the same dated file
    tracker.save()
    print(f"Applied {applied} decision(s)" + (f"; {skipped} skipped because those answers were already settled "
          f"(or weren't a yes/no)." if skipped else "."))


if __name__ == "__main__":
    main()
