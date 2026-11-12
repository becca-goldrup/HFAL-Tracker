"""
After `python run.py --fetch-only`: which websites look like they're missing an
application, summary or policy? Those are worth a look (or a crawler fix) before
paying for AI grading. Free; reads only the local cache.

    python tools/crawl_report.py
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from hfal import costs  # noqa: E402
from hfal.fetch import load_site  # noqa: E402
from run import pick_input  # noqa: E402
from hfal.spreadsheet import Tracker  # noqa: E402

LOOKS_LIKE = {
    "application": ["application", "form", "solicitud", "apply"],
    "summary": ["summary", "plain language", "plain-language", "resumen", "pls"],
    "policy": ["policy", "política", "politica", "fap"],
}


def kinds_found(site) -> set:
    found = set()
    for d in site.documents:
        if d.error or d.doc_id == "D1":
            continue
        label = (d.link_text + " " + d.url).lower()
        for kind, words in LOOKS_LIKE.items():
            if any(w in label for w in words):
                found.add(kind)
    # The landing page itself often is the summary.
    landing = next((d for d in site.documents if d.doc_id == "D1" and not d.error), None)
    if landing and "summary" in landing.text.lower():
        found.add("summary")
    return found


def main():
    tracker = Tracker(pick_input(None))
    groups = {}
    for h in tracker.hospitals():
        if h["hfa_url"]:
            groups.setdefault(h["hfa_url"], []).append(h["name"])

    rows, missing_count, scanned, cost = [], Counter(), 0, {"opus-5-5": 0, "sonnet-5-5": 0}
    for url, names in groups.items():
        site = load_site(url)
        if site is None:
            rows.append(("NOT FETCHED", url, names, 0))
            continue
        if not site.landing_ok:
            rows.append((f"PAGE FAILED: {site.error[:60]}", url, names, 0))
            continue
        ok = [d for d in site.documents if not d.error]
        scanned += sum(d.scanned for d in ok)
        for m in cost:
            cost[m] += costs.estimate_site(site, m)
        missing = [k for k in LOOKS_LIKE if k not in kinds_found(site)]
        missing_count.update(missing)
        if missing:
            rows.append(("missing? " + ", ".join(missing), url, names, len(ok)))

    print(f"{len(groups)} websites, {sum(len(n) for n in groups.values())} hospitals\n")
    print("Websites that may be missing documents (check these by hand, or improve the crawler):")
    for status, url, names, n in sorted(rows):
        print(f"  {status:42} {n:2d} docs  {url}\n  {'':42}          ({len(names)} hospital(s): {names[0][:50]})")
    print(f"\nLooks missing -> application: {missing_count['application']}, summary: {missing_count['summary']}, "
          f"policy: {missing_count['policy']}  |  scanned PDFs: {scanned}")
    print(f"Estimated cost to grade everything: Opus 5.5 ${cost['opus-5-5']:.2f}, Sonnet 5.5 ${cost['sonnet-5-5']:.2f}")


if __name__ == "__main__":
    main()
