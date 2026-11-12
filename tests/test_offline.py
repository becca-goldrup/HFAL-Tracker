"""Offline test: checks the safety rules and spreadsheet writing with a simulated
AI answer (no API key needed). Run after `python run.py --fetch-only`:
    python tests/test_offline.py
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import openpyxl
import config
from hfal.criteria import GRADED
from hfal.fetch import load_site
from hfal.verify import decide, max_fpl_cell, quote_found
from hfal.spreadsheet import Tracker

# ---- quote matching tolerates PDF quirks but not invented text
src = "Payments are limited to 5% of your gross\nmonthly income. Fi-\nnancial  Assistance is available."
assert quote_found("limited to 5% of your gross monthly income", src)
assert quote_found("Payments are limited ... Assistance is available", src)
assert quote_found("FinancialAssistance is available", "Financial Assistance is available")
assert not quote_found("You must apply within 30 days", src)
print("quote matching: ok")

URL = "https://www.bassett.org/patients-visitors/billing-insurance/financial-assistance"
site = load_site(URL)
assert site, "run `python run.py --fetch-only` first"
docs = {d.doc_id: d for d in site.documents}
def real(doc_id, n=90):
    """A genuine snippet from the downloaded document."""
    t = " ".join(docs[doc_id].text.split())
    mid = len(t) // 3
    return t[mid:mid + n]

app = next(d.doc_id for d in site.documents if d.kind == "docx" and not d.language_hint)
summ = next(d.doc_id for d in site.documents if d.kind == "pdf" and "Plain Language" in d.link_text and not d.language_hint)
def F(answer, conf="high", ev=(), why="test"):
    return {"answer": answer, "confidence": conf, "evidence": [{"doc_id": a, "quote": b} for a, b in ev], "reasoning": why}
findings = {
    "application_posted": F("yes", ev=[(app, real(app))]),
    "policy_summary_posted": F("yes", ev=[(summ, real(summ))]),
    "policy_statement_posted": F("no"),                                         # absence -> REVIEW
    "consistent_across_documents": F("no", ev=[("D5", "Patients must apply within 30 days of discharge")]),  # invented
    "psa_compliant_2007": F("unclear", "low", why="PSA wording ambiguous"),
    "no_time_limit": F("yes"), "no_asset_checks": F("yes"), "no_immigration_barrier": F("yes"),
    "entire_uniform_application": F("yes", ev=[(app, real(app))]),
    "contact_info_in_application": F("yes", ev=[(summ, real(summ))]),          # wrong document
    "income_tables_in_application": F("yes", "low", ev=[(app, real(app))]),     # low confidence
    "fpl_current_year": F("yes", ev=[(app, real(app))]),                        # contradicts 2026 below
    "max_fpl_400": F("yes", ev=[(app, real(app))]),
    "installments_capped_5pct": F("no"),
    "psa_in_summary": F("no"),
    "how_to_apply_in_summary": F("yes", ev=[(summ, real(summ))]),
    "income_levels_in_summary": F("yes", ev=[(summ, real(summ))]),
}
roles = [{"doc_id": "D1", "roles": ["landing_page"]}, {"doc_id": summ, "roles": ["policy_summary"]},
         {"doc_id": app, "roles": ["application"]}, {"doc_id": "D5", "roles": ["policy_statement"]}]
for r in roles:
    r.update(language="English", is_nys_uniform_application=r["doc_id"] == app, fpl_year=None)
graded = {"fingerprint": site.fingerprint(), "usage": {}, "warnings": [], "result": {
    "documents": roles, "findings": findings, "max_fpl_percent": 400, "fpl_year_used": config.FPL_YEAR - 1,
    "contact_phone": "607-547-3093", "languages_available": ["English", "Spanish"],
    "psa_definition_quote": None, "psa_counties": [], "timeframe_notes": "N/A",
    "inconsistency_notes": "N/A", "application_notes": "N/A", "summary_notes": "N/A",
    "general_notes": "Uses the term 'charity care'", "missing_material_notes": "N/A"}}

decisions, text, warnings = decide(site, graded)
got = {k: d.value for k, d in decisions.items()}
expected = {
    "application_posted": "yes", "policy_summary_posted": "yes", "policy_statement_posted": "REVIEW",
    "consistent_across_documents": "REVIEW", "psa_compliant_2007": "REVIEW", "no_time_limit": "yes",
    # immigration: Bassett's resource guide describes Medicaid citizenship rules -> red-flag scan sends it to review
    "no_asset_checks": "yes", "no_immigration_barrier": "REVIEW", "entire_uniform_application": "yes",
    "contact_info_in_application": "REVIEW", "income_tables_in_application": "REVIEW",
    # installments: "entire Uniform Application" + "no 5% cap" is a contradiction -> review
    "fpl_current_year": "REVIEW", "max_fpl_400": "yes", "installments_capped_5pct": "REVIEW",
    "psa_in_summary": "no", "how_to_apply_in_summary": "yes", "income_levels_in_summary": "yes"}
for k in expected:
    mark = "ok " if got[k] == expected[k] else "BAD"
    print(f"  {mark} {k:30} {got[k]:7} {decisions[k].reason[:85] if got[k]=='REVIEW' else ''}")
assert got == expected

# ---- spreadsheet writing (to a temp folder, original untouched)
config.OUTPUT_DIR = Path(tempfile.mkdtemp())
t = Tracker(Path(__file__).parent / "sample-tracker.xlsx")
h = next(x for x in t.hospitals() if x["hfa_url"] == URL)
t.apply(h, decisions, text, warnings, site, max_fpl_cell(decisions["max_fpl_400"], 400))
out = t.save()
wb = openpyxl.load_workbook(out); ws = wb[config.SHEET_NAME]
assert ws["T3"].value == "REVIEW" and ws["T3"].fill.fgColor.rgb == "FFF4B183" and ws["T3"].comment
assert ws["AL3"].value == "no" and ws["AL3"].fill.fgColor.rgb == "FFBDD7EE"   # changed yes -> no
assert ws["AI3"].value == 4 and ws["R3"].value == "yes"
assert {"AI Review Queue", "AI Change Log", "AI Run Log"} <= set(wb.sheetnames)
assert ws.tables["Table1"].ref.endswith("AU5"), ws.tables["Table1"].ref
print("  queue rows:", wb["AI Review Queue"].max_row - 1, "| change rows:", wb["AI Change Log"].max_row - 1,
      "| status:", ws.cell(3, 46).value)
print("  csv:", (config.OUTPUT_DIR / "hospitals.csv").read_text().splitlines()[1][:150], "...")
print("spreadsheet writing: ok\nALL OFFLINE TESTS PASSED")
