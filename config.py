"""
Settings you might want to change. Everything else lives in the hfal/ folder.
"""
from pathlib import Path

ROOT = Path(__file__).parent

# ---- Files -------------------------------------------------------------------
INPUT_DIR = ROOT / "data" / "input"     # put the CSS spreadsheet here
OUTPUT_DIR = ROOT / "data" / "output"   # updated spreadsheets + CSV land here
CACHE_DIR = ROOT / "data" / "cache"     # downloaded documents + AI answers
MANUAL_DIR = ROOT / "data" / "manual"   # documents a person saved for sites that block the tool
# Current documents CSS pointed to that the crawler might miss (or that live on
# another site after a rebrand). They are added to that site's documents.
EXTRA_DOCUMENTS = {
    "https://www.northwell.edu/billing-and-insurance/financial-assistance-programs-policies/financial-assistance-program": [
        "https://www.northwell.edu/sites/northwell.edu/files/2026-06/doh-nys-uniform-hospital-financial-assistance-application.pdf",
    ],
    # Arnot is now Centralus Health; its 2024 application is still on the old site.
    "https://www.arnothealth.org/financial-assistance": [
        "https://centralushealth.org/wp-content/uploads/2026_uniform_financial_assistance_application.pdf",
    ],
}

# HFA links in the spreadsheet that moved. The original spreadsheet is never
# edited; the tool uses the new link and records the change in the AI Change Log.
HFA_LINK_FIXES = {
    # old link (page not found, Nov 2026) -> new link
    "https://nfmmc.org/patients-visitors/financial-assistance/": "https://www.nfmmc.org/financial-assistance",
}
SHEET_NAME = "Hospital Tracker"
FIRST_DATA_ROW = 3                      # row 1 = section titles, row 2 = headers

# ---- The law -----------------------------------------------------------------
# NY Public Health Law Section 2807-K:
#   https://newyork.public.law/laws/n.y._public_health_law_section_2807-k
# Hospitals are compared against the current NYS DOH Uniform Financial Assistance
# Application (CSS, Nov 2026: use the 2026 version, which uses 2026 FPL figures).
FPL_YEAR = 2026
REFERENCE_APPLICATION = ROOT / "data" / "reference" / "nys-uniform-application-2026.txt"

# The rubric table lists "no policy statement posted" as an automatic F, but CSS's
# spreadsheet formula (and its published "14 of 212 compliant") doesn't apply it.
# False = match the spreadsheet (17 hospitals would drop to F if True). Ask CSS.
POLICY_STATEMENT_AUTO_FAIL = False

# ---- Where Claude runs -------------------------------------------------------
# "bedrock-nova" -> Amazon Nova in the sprint's AWS sandbox. Works with the sandbox
#                   credits today (Claude there needs a Marketplace subscription the
#                   sandbox role can't create). Sign in: `aws sso login --profile hackathon`
# "bedrock"      -> Claude in the AWS sandbox, once Claude access is enabled
# "anthropic"    -> Claude with your own Anthropic API key in .env (ANTHROPIC_API_KEY=...)
PROVIDER = "bedrock-nova"
NOVA_MODEL = "us.amazon.nova-pro-v1:0"
NOVA_MAX_TOKENS = 10000
NOVA_MAX_CHARS_PER_HOSPITAL = 900_000   # Nova Pro reads up to ~300K tokens

AWS_PROFILE = "hackathon"   # the profile name from `aws configure sso`
AWS_REGION = "us-east-1"
# Bedrock model id (an inference profile starting with "us.anthropic.").
# Run `python tools/check_bedrock.py` to list the ones your sandbox allows.
BEDROCK_MODEL = "us.anthropic.claude-sonnet-5-5"   # Opus 5.5 needs a Marketplace subscription the sandbox role lacks

# ---- AI model ----------------------------------------------------------------
MODEL = "claude-opus-5-5"   # used when PROVIDER = "anthropic"
EFFORT = "high"           # low | medium | high | xhigh | max  (accuracy matters here)
MAX_OUTPUT_TOKENS = 64000
PARALLEL_AI_CALLS = 4     # how many hospitals to grade at the same time

# ---- Spending safety ---------------------------------------------------------
# The AWS sandbox has a $50 budget and FREEZES when it's used up. A run stops
# starting new hospitals once its estimated spend would pass this cap; the rest
# are picked up next run (finished ones are cached and never paid for twice).
MAX_SPEND_PER_RUN = 15.00

# ---- Website crawling --------------------------------------------------------
MAX_DOCUMENTS_PER_SITE = 30       # PDFs + sub-pages followed from each HFA page
FOLLOW_SUBPAGES = True            # also open relevant same-site pages one click away
PAGE_TIMEOUT_SECONDS = 45        # opening one web page
FILE_TIMEOUT_SECONDS = 60        # downloading one PDF / Word file
SITE_TIME_BUDGET_SECONDS = 300   # stop collecting more documents from a site after this
FETCH_WORKERS = 6                # websites downloaded at the same time
# Translated copies of the same document mostly repeat the English version, so
# we only send the first part of them to the AI (enough to confirm the language).
TRANSLATION_PREVIEW_CHARS = 3000
# Safety cap on how much text one hospital can send to the AI (~1 token / 4 chars).
MAX_CHARS_PER_HOSPITAL = 1_500_000
