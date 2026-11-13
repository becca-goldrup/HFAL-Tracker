"""
HFAL compliance checker -- Part 1.

    python run.py --limit 3              # try it on the first 3 websites
    python run.py --only "Bassett"       # just hospitals whose name/system/link matches
    python run.py --fetch-only           # download documents, no AI (free)
    python run.py                        # everything (asks before spending money)

See README.md for setup.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config
from hfal import costs
from hfal.criteria import REVIEW
from hfal.fetch import Fetcher, load_site, save_site
from hfal.spreadsheet import Tracker, grade_row

logging.getLogger("pypdf").setLevel(logging.ERROR)

# Load ANTHROPIC_API_KEY (and anything else) from a local .env file, if present.
_env = config.ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))



def credentials_problem() -> str | None:
    """Explain what's missing before we try to call Claude, or None if ready."""
    if config.PROVIDER == "anthropic":
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return None
        return "No ANTHROPIC_API_KEY found. Add it to .env (see README.md)."
    if config.PROVIDER == "bedrock" and not config.BEDROCK_MODEL:
        return "BEDROCK_MODEL is empty in config.py. Run `python tools/check_bedrock.py` to pick one."
    try:
        import boto3
        session = (boto3.Session(region_name=config.AWS_REGION) if os.environ.get("AWS_ACCESS_KEY_ID")
                   else boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION))
        session.client("sts").get_caller_identity()
        return None
    except Exception as e:
        return (f"Not signed in to AWS ({type(e).__name__}). Run:\n"
                f"    aws sso login --profile {config.AWS_PROFILE}\n"
                f"(first time? see README.md, 'Connect to the AWS sandbox')")


def pick_input(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    # Prefer the most recent output, so human REVIEW decisions carry forward.
    for folder in (config.OUTPUT_DIR, config.INPUT_DIR):
        files = sorted(folder.glob("*.xlsx"), key=lambda p: (p.name, p.stat().st_mtime), reverse=True)
        files = [f for f in files if not f.name.startswith("~$")]
        if files:
            return files[0]
    sys.exit(f"No spreadsheet found. Put the CSS .xlsx file in {config.INPUT_DIR}/")


FINGERPRINTS = config.OUTPUT_DIR / "document-fingerprints.json"


def load_fingerprints() -> dict:
    """{hfa_url: {"fingerprint", "graded"}}: what each website's documents looked like when last graded."""
    import json
    try:
        return json.loads(FINGERPRINTS.read_text())
    except Exception:
        return {}


def save_fingerprints(fps: dict) -> None:
    import json
    FINGERPRINTS.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINTS.write_text(json.dumps(dict(sorted(fps.items())), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="spreadsheet to start from (default: newest in data/output, else data/input)")
    ap.add_argument("--limit", type=int, help="only check the first N websites")
    ap.add_argument("--only", help="only hospitals whose name, system or link contains this text")
    ap.add_argument("--fetch-only", action="store_true", help="download documents but don't call the AI")
    ap.add_argument("--force", action="store_true", help="re-grade even if a website hasn't changed")
    ap.add_argument("--yes", action="store_true", help="don't ask before spending money")
    ap.add_argument("--reapply", action="store_true",
                    help="re-check saved AI answers with the current safety rules and rewrite the sheet (no AI calls)")
    args = ap.parse_args()

    src = pick_input(args.input)
    print(f"Starting from: {src}")
    tracker = Tracker(src)

    # Hospitals that share a financial assistance page are checked once.
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for h in tracker.hospitals():
        if args.only and not any(o.strip().lower() in f"{h['name']} {h['system']} {h['hfa_url']}".lower() for o in args.only.split("|") if o.strip()):
            continue
        if not h["hfa_url"]:
            print(f"  ! {h['name']}: no HFA link in the sheet -- skipped")
            continue
        groups.setdefault(h["hfa_url"], []).append(h)
    if args.limit:
        groups = OrderedDict(list(groups.items())[: args.limit])
    print(f"{sum(len(v) for v in groups.values())} hospitals, {len(groups)} unique websites\n")
    if not groups:
        return

    # ------------------------------------------------------------ 1. fetch
    from hfal.grader import load_result
    sites, status, why = {}, {}, {}
    print(f"Step 1/3: downloading documents ({config.FETCH_WORKERS} websites at a time)", flush=True)
    lock, done = threading.Lock(), [0]
    urls = list(groups)
    n_workers = max(1, min(config.FETCH_WORKERS, len(urls)))

    def fetch_worker(chunk):
        # Each worker runs its own browser (Playwright browsers can't be shared across threads).
        with Fetcher() as f:
            for url in chunk:
                try:
                    site = f.fetch_site(url)
                except Exception as e:  # never let one odd site stop the run
                    from hfal.fetch import SiteFetch
                    site = SiteFetch(hfa_url=url, fetched_at="", landing_ok=False,
                                     error=f"{type(e).__name__}: {str(e)[:200]}")
                if site.landing_ok or load_site(url) is None:
                    save_site(site)  # a failed attempt doesn't overwrite the last good download
                ok_docs = [d for d in site.documents if not d.error]
                # The last fingerprint lives in the repository (data/output/document-fingerprints.json),
                # so it survives even when GitHub's temporary cache of downloaded files has expired.
                prev_fp = fingerprints.get(url, {}).get("fingerprint") or (load_result(url) or {}).get("fingerprint")
                if not site.landing_ok:
                    st, reason = f"error: {site.error}", ""
                elif prev_fp and prev_fp == site.fingerprint() and not args.force:
                    st, reason = "unchanged", "documents unchanged"
                else:
                    st = "grade"
                    reason = ("first AI check" if not prev_fp else
                              "documents changed" if prev_fp != site.fingerprint() else
                              "re-checked (same documents)")
                with lock:
                    sites[url], status[url], why[url] = site, st, reason
                    done[0] += 1
                    print(f"  [{done[0]}/{len(urls)}] {len(ok_docs):2d} docs  {st[:60]:12}  {url}", flush=True)

    fingerprints = load_fingerprints()
    chunks = [urls[i::n_workers] for i in range(n_workers)]
    with ThreadPoolExecutor(n_workers) as ex:
        for fut in [ex.submit(fetch_worker, c) for c in chunks]:
            fut.result()

    if args.fetch_only:
        print(f"\nDone (fetch only). Documents are in {config.CACHE_DIR}/")
        need = [sites[u] for u, s in status.items() if s == "grade"]
        if need:
            print(f"Estimated cost to grade these {len(need)} website(s):")
            for name, model in [("Opus 5.5", "opus-5-5"), ("Sonnet 5.5", "sonnet-5-5"), ("Haiku 5.5", "haiku-5-5")]:
                print(f"  {name:11} ${sum(costs.estimate_site(x, model) for x in need):7.2f}")
        return

    # ------------------------------------------------------------ 2. grade
    to_grade = [u for u, s in status.items() if s == "grade"]
    results = {u: load_result(u) for u in groups}
    if to_grade:
        problem = credentials_problem()
        if problem:
            sys.exit(f"\n{problem}\n(Or run with --fetch-only to just download documents.)")
        from hfal.grader import grade_site, save_result
        est = {u: costs.estimate_site(sites[u]) for u in to_grade}
        total = sum(est.values())
        where = "the AWS sandbox budget" if config.PROVIDER.startswith("bedrock") else "your API key"
        print(f"\nStep 2/3: AI grading of {len(to_grade)} website(s) with {costs.current_model()}")
        print(f"  Estimated cost: ${total:.2f}, charged to {where}. Spending cap for this run: "
              f"${config.MAX_SPEND_PER_RUN:.2f} (MAX_SPEND_PER_RUN in config.py)")
        if total > config.MAX_SPEND_PER_RUN:
            print("  The cap will stop this run partway. Run again later to continue where it stopped.")
        if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
            sys.exit("Stopped. Nothing was charged.")

        spent, committed = 0.0, 0.0   # actual spend so far; spend of calls still running
        done_est = 0.0                # what the finished calls were estimated to cost

        def calibrated(u):
            # Once real costs come in, scale estimates to match reality (never down).
            return est[u] * (max(1.0, spent / done_est) if done_est else 1.0)
        queue, running = list(to_grade), {}
        with ThreadPoolExecutor(config.PARALLEL_AI_CALLS) as ex:
            while queue or running:
                # Start more hospitals while there's room under the cap.
                while queue and len(running) < config.PARALLEL_AI_CALLS:
                    u = queue[0]
                    if spent + committed + calibrated(u) > config.MAX_SPEND_PER_RUN:
                        break
                    queue.pop(0)
                    reserve = calibrated(u)
                    committed += reserve
                    running[ex.submit(grade_site, sites[u], groups[u])] = (u, reserve)
                if not running:
                    break  # cap reached
                fut = next(as_completed(running))
                u, reserve = running.pop(fut)
                committed -= reserve
                try:
                    results[u] = fut.result()
                    save_result(u, results[u])
                    spent += costs.actual(results[u]["usage"])
                    done_est += est[u]
                    print(f"  graded   ${spent:6.2f} so far  {u}")
                except Exception as e:
                    status[u] = f"error: AI step failed: {type(e).__name__}: {str(e)[:150]}"
                    print(f"  FAILED   {u}: {status[u]}")
        for u in queue:
            status[u] = "skipped: spending cap reached, will be graded next run"
        if queue:
            print(f"  Spending cap reached: {len(queue)} website(s) left for the next run.")

    # ------------------------------------------------------------ 3. write
    from hfal.verify import decide, max_fpl_cell
    print("\nStep 3/3: checking answers and writing the spreadsheet")
    usage_total = Counter()
    for url, hospitals in groups.items():
        site, res, st = sites[url], results.get(url), status[url]
        n_docs = len([d for d in site.documents if not d.error])
        already_has_ai = all(tracker.ws.cell(h["row"], tracker.new_col["AI Last Checked"]).value for h in hospitals)
        if st == "unchanged" and already_has_ai and not args.reapply:
            # Nothing changed online: keep the sheet as-is (including staff decisions).
            for h in hospitals:
                tracker.mark_checked(h, "website unchanged")
            tracker.log_run(url, "unchanged", len(hospitals), n_docs, None, "documents unchanged")
            fingerprints[url] = {"fingerprint": site.fingerprint(), "graded": fingerprints.get(url, {}).get("graded", "")}
            continue
        if st.startswith(("error", "skipped")) or res is None:
            for h in hospitals:
                tracker.mark_checked(h, st if st.startswith(("error", "skipped")) else "error: no AI result")
            tracker.log_run(url, st, len(hospitals), n_docs, None, why.get(url, ""))
            continue
        decisions, text, warnings = decide(site, res)
        tracker.record_details(url, site, decisions, res.get("model", ""))
        fpl_val = max_fpl_cell(decisions["max_fpl_400"], res["result"].get("max_fpl_percent"))
        from hfal.spreadsheet import psa_listed
        for h in hospitals:
            tracker.apply(h, decisions, text, warnings, site, fpl_val, psa_listed(res["result"]), why.get(url, ""))
        if st == "grade":
            usage_total.update(res["usage"])
            fingerprints[url] = {"fingerprint": site.fingerprint(), "graded": tracker.run_date}
        tracker.log_run(url, "graded" if st == "grade" else "applied cached result", len(hospitals), n_docs,
                        res["usage"] if st == "grade" else None, why.get(url, ""))

    out = tracker.save()
    save_fingerprints(fingerprints)

    # ------------------------------------------------------------ summary
    checked = [h for hs in groups.values() for h in hs]
    grades = Counter(grade_row(tracker.last_values(h["row"]))["grade"] for h in checked)
    n_review = sum(1 for h in checked for v in tracker.last_values(h["row"]).values() if v == REVIEW)
    print(f"\nSaved: {out}")
    print(f"       {config.OUTPUT_DIR / 'hospitals.csv'}")
    print(f"Grades (provisional where items need review): {dict(sorted(grades.items()))}")
    print(f"Cells needing human review: {n_review}  -> see the 'AI Review Queue' tab")
    print(f"Values changed: {len(tracker.changes)}  -> see the 'AI Change Log' tab")
    if usage_total:
        cost = costs.actual(usage_total)
        print(f"AI usage this run: {usage_total['input']:,} in / {usage_total['output']:,} out tokens "
              f"(about ${cost:.2f})")


if __name__ == "__main__":
    main()
