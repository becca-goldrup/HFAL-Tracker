"""Checks the spending cap with a fake AI (no money spent). Needs `python run.py --fetch-only` first.
    python tests/test_spend_cap.py
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config, run
import hfal.grader as grader
from hfal import costs
from hfal.criteria import GRADED

config.PROVIDER, config.BEDROCK_MODEL = "bedrock", "us.anthropic.claude-sonnet-5-5-v1:0"
config.OUTPUT_DIR = Path(tempfile.mkdtemp())
run.credentials_problem = lambda: None
grader.load_result = lambda url: None          # pretend nothing was graded before
grader.save_result = lambda url, data: None    # don't pollute the real cache
calls = []

def fake_grade(site, hospitals):
    calls.append(site.hfa_url)
    f = {"answer": "unclear", "confidence": "low", "evidence": [], "reasoning": "fake"}
    return {"fingerprint": site.fingerprint(), "usage": {"input": 500_000, "output": 0}, "warnings": [],
            "result": {"documents": [], "findings": {c.key: dict(f) for c in GRADED}, "max_fpl_percent": None,
                       "fpl_year_used": None, "contact_phone": None, "languages_available": [],
                       "psa_definition_quote": None, "psa_counties": [], "timeframe_notes": "N/A",
                       "inconsistency_notes": "N/A", "application_notes": "N/A", "summary_notes": "N/A",
                       "general_notes": "N/A", "missing_material_notes": "N/A"}}
grader.grade_site = fake_grade
config.PARALLEL_AI_CALLS = 1
config.MAX_SPEND_PER_RUN = 2.20   # each fake call "costs" $1.00 -> room for 2 sites, not 3
sys.argv = ["run.py", "--input", str(Path(__file__).parent / "sample-tracker.xlsx"), "--yes", "--force"]
run.main()
assert len(calls) == 2, calls
print(f"\nSPEND CAP TEST PASSED: graded {len(calls)} of 3 sites, stopped under the ${config.MAX_SPEND_PER_RUN} cap")
