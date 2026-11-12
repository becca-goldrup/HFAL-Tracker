"""
The HFAL grading rubric, written down as data.

Every column the tool fills in is described here once. The grader prompt, the
safety checks, the spreadsheet writer, and (later) the Part 2 dashboard all read
from this file, so if CSS changes a rule, this is the only place to edit.

Column letters match the CSS "Hospital Tracker" sheet (Sept 2025 version).
"""

from dataclasses import dataclass
from typing import Literal, Optional

# Which document(s) the grader may look at for a criterion. This follows the
# CSS methodology: the Application section is judged ONLY from the application,
# the Plain Language Summary section ONLY from the summary.
Scope = Literal["all", "application", "summary"]

# What kind of proof a YES or a NO needs before the tool will write it without
# a human looking:
#   "quote"   -> a verbatim quote that we can find in the downloaded document
#   "absence" -> it's fine that nothing was found (e.g. "no time limit" is YES
#                when no time limit appears anywhere)
#   "review"  -> never auto-write this answer; always send to a human
Proof = Literal["quote", "absence", "review"]


@dataclass(frozen=True)
class Criterion:
    key: str               # short machine name
    column: str            # Excel column letter
    header: str            # Excel header text (row 2)
    section: str           # MATERIALS ON WEBSITE / APPLICATION / PLAIN LANGUAGE SUMMARY
    scope: Scope
    question: str          # what the AI is asked (YES always = compliant)
    guidance: str          # extra rules from the CSS methodology
    yes_proof: Proof
    no_proof: Proof
    plain_language: str    # what the law requires, for patients/advocates (dashboard)
    requires_doc: Optional[str] = None  # doc type that must exist to answer


GRADED: list[Criterion] = [
    # ---------------------------------------------------------------- MATERIALS ON WEBSITE
    Criterion(
        key="application_posted", column="R", header="Application Posted",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is a financial assistance application posted (any application, not necessarily the NYS Uniform Application)?",
        guidance="YES if any downloadable or online financial assistance application is available from the hospital's HFA page.",
        yes_proof="quote", no_proof="review",
        plain_language="Hospitals must post their financial assistance application on their website so patients can apply.",
    ),
    Criterion(
        key="policy_summary_posted", column="S", header="Policy Summary Posted (as PDF, or on landing page)",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is a plain language summary of the financial assistance policy posted (as a PDF or on the landing page)?",
        guidance="'Plain language summary' and 'policy summary' are used interchangeably. A landing page can count if it functions as the summary.",
        yes_proof="quote", no_proof="review",
        plain_language="Hospitals must post a plain-language summary of their financial assistance policy.",
    ),
    Criterion(
        key="policy_statement_posted", column="T", header="Policy Statement Posted",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is the full financial assistance policy statement posted and accessible?",
        guidance="This is the full policy document, not the summary.",
        yes_proof="quote", no_proof="review",
        plain_language="Hospitals must post their full financial assistance policy.",
    ),
    Criterion(
        key="consistent_across_documents", column="U", header="Consistent across posted documents (Y/N)",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is the information consistent across all posted materials (application, summary, policy, landing page, supplemental documents)?",
        guidance=("NO if documents disagree, e.g. different FPL years, different income cutoffs, different discount tables, "
                  "different time limits. A non-compliant online application or inconsistent supplemental documents also make this NO. "
                  "Describe every inconsistency in inconsistency_notes."),
        yes_proof="absence", no_proof="quote",
        plain_language="All of a hospital's financial assistance documents should give patients the same, correct information.",
    ),
    Criterion(
        key="psa_compliant_2007", column="V", header="Primary Service Area boundaries compliant with 2007 guidelines?",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is the hospital's primary service area (PSA), wherever it is defined, compliant with the 2007 DOH guidelines?",
        guidance=("A compliant PSA covers at least the county the hospital is in AND all contiguous counties (a broader area, "
                  "such as all of New York State, is also compliant). NO if the PSA is narrower or lists the wrong areas. "
                  "If no PSA is described in ANY posted document, answer NO. Quote the PSA definition."),
        yes_proof="quote", no_proof="quote",
        plain_language=("A hospital's financial assistance must cover patients who live in at least the hospital's county and all "
                        "neighboring counties (its 'primary service area')."),
    ),
    Criterion(
        key="no_time_limit", column="W", header="No time limit to submit?",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is the hospital compliant with the rule that there is NO time limit to submit a financial assistance application?",
        guidance="YES if no submission deadline appears anywhere. NO if any document sets a deadline (e.g. '240 days after services'). Put the deadline wording in timeframe_notes.",
        yes_proof="absence", no_proof="quote",
        plain_language="There is no deadline to apply for hospital financial assistance. Patients can apply at any time.",
    ),
    Criterion(
        key="no_asset_checks", column="Y", header="No evidence of asset checks",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is there NO evidence of asset checks?",
        guidance="NO if any document asks about assets, savings, property, or requests bank account statements. Asset checks are illegal.",
        yes_proof="absence", no_proof="quote",
        plain_language="Hospitals cannot consider a patient's assets (savings, property, bank accounts) when deciding financial assistance.",
    ),
    Criterion(
        key="no_immigration_barrier", column="Z", header="No mention of immigration status as a barrier",
        section="MATERIALS ON WEBSITE", scope="all",
        question="Is there NO mention of immigration status as a barrier to financial assistance?",
        guidance="YES if immigration status is not mentioned, or if a document explicitly says it does not matter. NO if any document excludes or limits patients based on immigration status or requires proof of citizenship/residency status.",
        yes_proof="absence", no_proof="quote",
        plain_language="Patients cannot be denied financial assistance because of their immigration status.",
    ),
    # ---------------------------------------------------------------- APPLICATION (application only)
    Criterion(
        key="entire_uniform_application", column="AD", header="ENTIRE Uniform Application",
        section="APPLICATION", scope="application", requires_doc="application",
        question="Is the hospital using the ENTIRE NYS Uniform Financial Assistance Application?",
        guidance="NO if the hospital uses its own application, or only part of the Uniform Application (e.g. omits the installments clause). Note any omissions in application_notes.",
        yes_proof="quote", no_proof="quote",
        plain_language="Hospitals must use the full New York State Uniform Financial Assistance Application, not their own version.",
    ),
    Criterion(
        key="contact_info_in_application", column="AE", header="Contact information included in application",
        section="APPLICATION", scope="application", requires_doc="application",
        question="Does the application itself clearly list contact information for financial assistance help?",
        guidance="Put the primary HFA help phone number in contact_phone.",
        yes_proof="quote", no_proof="absence",
        plain_language="The application must tell patients who to contact for help with financial assistance.",
    ),
    Criterion(
        key="income_tables_in_application", column="AG", header="Income & Discount Tables Incuded in Application",
        section="APPLICATION", scope="application", requires_doc="application",
        question="Does the application directly include tables showing income levels and the corresponding discounts on care?",
        guidance="",
        yes_proof="quote", no_proof="absence",
        plain_language="The application must show the income levels and the discount a patient gets at each level.",
    ),
    Criterion(
        key="fpl_current_year", column="AH", header="2025 FPL Guidelines",
        section="APPLICATION", scope="application", requires_doc="application",
        question="Does the application use the {fpl_year} Federal Poverty Level guidelines?",
        guidance="Report the FPL year the application states (or implies from dollar amounts) in fpl_year_used. NO if it uses another year or no FPL year can be identified.",
        yes_proof="quote", no_proof="quote",
        plain_language="Income limits must be based on the current year's Federal Poverty Level guidelines.",
    ),
    Criterion(
        key="max_fpl_400", column="AI", header="Max FPL (compliant is =/>400%)",
        section="APPLICATION", scope="application", requires_doc="application",
        question="Does the application make financial assistance available to patients at or below at least 400% of the FPL?",
        guidance="Report the highest FPL percentage the application covers in max_fpl_percent (e.g. 400). YES if >= 400.",
        yes_proof="quote", no_proof="quote",
        plain_language="Patients with incomes up to 400% of the Federal Poverty Level qualify for financial assistance.",
    ),
    Criterion(
        key="installments_capped_5pct", column="AJ", header="Installments capped at 5% of monthly income",
        section="APPLICATION", scope="application", requires_doc="application",
        question="Does the application explicitly state that installment/payment plan payments are capped at 5% of gross monthly income?",
        guidance="",
        yes_proof="quote", no_proof="absence",
        plain_language="Monthly payment plans cannot be more than 5% of a patient's gross monthly income.",
    ),
    # ---------------------------------------------------------------- PLAIN LANGUAGE SUMMARY (summary only)
    Criterion(
        key="psa_in_summary", column="AL", header="Primary Service Area described in summary? ",
        section="PLAIN LANGUAGE SUMMARY", scope="summary", requires_doc="policy_summary",
        question="Does the plain language summary itself describe the primary service area?",
        guidance="Look ONLY at the summary. If the PSA is described only in the policy or elsewhere, answer NO.",
        yes_proof="quote", no_proof="absence",
        plain_language="The plain-language summary must say which geographic area the hospital's financial assistance covers.",
    ),
    Criterion(
        key="how_to_apply_in_summary", column="AM", header="Means of applying for assistance explained",
        section="PLAIN LANGUAGE SUMMARY", scope="summary", requires_doc="policy_summary",
        question="Does the plain language summary explain how to apply for financial assistance?",
        guidance="",
        yes_proof="quote", no_proof="absence",
        plain_language="The plain-language summary must explain how to apply for financial assistance.",
    ),
    Criterion(
        key="income_levels_in_summary", column="AN", header="Income levels used to determine assistance",
        section="PLAIN LANGUAGE SUMMARY", scope="summary", requires_doc="policy_summary",
        question="Does the plain language summary include the income levels used to determine assistance ($ amounts, % of FPL, etc.)?",
        guidance="",
        yes_proof="quote", no_proof="absence",
        plain_language="The plain-language summary must list the income levels used to decide who qualifies.",
    ),
]

assert len(GRADED) == 17, "The CSS rubric has 17 graded yes/no categories"

# Free-text columns the tool fills (not part of the grade).
TEXT_COLUMNS = {
    "timeframe_notes": "X",
    "inconsistency_notes": "AA",
    "languages_available": "AB",
    "general_notes": "AC",
    "contact_phone": "AF",
    "application_notes": "AK",
    "summary_notes": "AO",
}

# Values the tool writes into a graded cell.
YES, NO, REVIEW = "yes", "no", "REVIEW"

BY_KEY = {c.key: c for c in GRADED}


def grade(answers: dict[str, str], auto_fail: bool) -> str:
    """CSS grading rubric. `answers` maps criterion key -> yes/no/REVIEW."""
    if auto_fail:
        return "F"
    errors = sum(1 for v in answers.values() if v == NO)
    if errors == 0:
        return "A"
    if errors <= 3:
        return "B"
    if errors <= 6:
        return "C"
    if errors <= 9:
        return "D"
    return "F"


def is_auto_fail(answers: dict[str, str]) -> bool:
    """Automatic F: no application posted, or not the (entire) Uniform Application.

    The rubric also lists 'no policy statement posted' as an automatic F, but the
    CSS spreadsheet formula only checks the two application conditions. We follow
    the rubric table here; flag this to CSS if the numbers differ from the sheet.
    """
    return (
        answers.get("application_posted") == NO
        or answers.get("entire_uniform_application") == NO
        or answers.get("policy_statement_posted") == NO
    )
