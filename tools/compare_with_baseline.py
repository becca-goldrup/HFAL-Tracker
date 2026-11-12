"""
How do the AI's answers compare with CSS's hand-checked spreadsheet?

    python tools/compare_with_baseline.py

Compares every hospital the AI has graded (newest file in data/output) with the
original CSS spreadsheet (data/input). Disagreements are not automatically AI
mistakes: hospitals have changed their documents since CSS's September 2025 review.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from hfal.criteria import GRADED, LABELS, REVIEW  # noqa: E402
from hfal.spreadsheet import Tracker, _col, _normalize  # noqa: E402


def newest(folder: Path) -> Path:
    return max((p for p in folder.glob("*.xlsx") if not p.name.startswith("~$")), key=lambda p: p.name)


def main():
    base, ai = Tracker(newest(config.INPUT_DIR)), Tracker(newest(config.OUTPUT_DIR))
    base_rows = {h["name"]: h["row"] for h in base.hospitals()}
    seen_sites, totals, per_criterion = set(), Counter(), {c.key: Counter() for c in GRADED}
    disagreements = []
    for h in ai.hospitals():
        checked = ai.ws.cell(h["row"], ai.new_col["AI Last Checked"]).value
        if not checked or "error" in str(checked) or h["hfa_url"] in seen_sites:
            continue
        seen_sites.add(h["hfa_url"])  # hospitals sharing a page get identical answers; count each page once
        for c in GRADED:
            a = _normalize(ai.ws.cell(h["row"], _col(c.column)).value)
            b = _normalize(base.ws.cell(base_rows[h["name"]], _col(c.column)).value)
            kind = "needs review" if a == REVIEW else ("agree" if a == b else "disagree")
            totals[kind] += 1
            per_criterion[c.key][kind] += 1
            if kind == "disagree":
                cm = ai.ws.cell(h["row"], _col(c.column)).comment
                disagreements.append((h["name"], LABELS[c.key], b, a, cm.text if cm else ""))

    n = sum(totals.values())
    if not n:
        sys.exit("No AI-graded hospitals found in data/output yet.")
    print(f"Compared {len(seen_sites)} website(s), {n} answers, against CSS's 2025 spreadsheet:\n")
    for k in ("agree", "disagree", "needs review"):
        print(f"  {k:13} {totals[k]:4}  ({100 * totals[k] / n:.0f}%)")
    decided = totals["agree"] + totals["disagree"]
    if decided:
        print(f"\n  When the AI gave a yes/no answer, it matched CSS {100 * totals['agree'] / decided:.0f}% of the time.")
    print("\nBy requirement (agree / disagree / review):")
    for c in GRADED:
        k = per_criterion[c.key]
        print(f"  {LABELS[c.key][:52]:52} {k['agree']:2} / {k['disagree']:2} / {k['needs review']:2}")
    if disagreements:
        print("\nDisagreements (CSS 2025 -> AI now):")
        for name, label, b, a, why in disagreements:
            print(f"  - {name}: {label}: {b} -> {a}")
            if why:
                print(f"      {why.splitlines()[0][:220]}")


if __name__ == "__main__":
    main()
