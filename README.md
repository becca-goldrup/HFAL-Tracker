# HFAL Compliance Tracker: Part 1 (the checker)

This is a tool for the AI for Health Equity Design Sprint (CSSNY challenge). It visits each New York
hospital's financial assistance page, reads the posted documents, grades them against the
CSS rubric (17 yes/no criteria), and writes the results into a copy of the CSS spreadsheet.
Anything the AI can't find or isn't sure about is marked **REVIEW** for a person to check.

Part 2 (the dashboard and map) will read `data/output/hospitals.csv`, which this tool produces.

## How it works

```
 Spreadsheet ──► 1. FETCH ──────► 2. GRADE ───────► 3. VERIFY ──────────► 4. WRITE
 (HFA links)     open each page   Claude reads all   every quote checked   new dated .xlsx
                 in a real        docs, answers      against the source;   + Review Queue
                 browser, save    each criterion     unsure/unproven ->    + Change Log
                 PDFs/Word/pages  with exact quotes  REVIEW                + hospitals.csv
```

* **Shared pages are checked once.** 212 hospitals share 98 unique financial assistance pages.
* **It follows the CSS methodology.** Application criteria are judged from the application only,
  summary criteria from the summary only, and conflicts between documents go in "Inconsistency notes".
* **It guards against hallucination.** A cell only gets `yes` or `no` if Claude was confident, every quote it gave
  is actually found in the downloaded document, and the evidence came from the right
  document. "This document isn't posted" is always sent to a human, because the document might
  be on a page the crawler didn't reach. The rules are in [hfal/verify.py](hfal/verify.py).
* **Monthly re-runs are cheap.** If a website's documents haven't changed, that hospital is skipped
  and any fixes a reviewer made are kept.
* **Your original spreadsheet is never modified.**

## Files

| File | What it does |
|---|---|
| [run.py](run.py) | The command you run |
| [config.py](config.py) | Settings (AI model, FPL year, crawl limits) |
| [hfal/criteria.py](hfal/criteria.py) | **The rubric**: the 17 criteria, the rules, and plain-language law text |
| [hfal/fetch.py](hfal/fetch.py) | Step 1: browse sites and download documents |
| [hfal/grader.py](hfal/grader.py) | Step 2: the prompt and the Claude API call |
| [hfal/verify.py](hfal/verify.py) | Step 3: safety checks and the REVIEW decisions |
| [hfal/spreadsheet.py](hfal/spreadsheet.py) | Step 4: Excel output and CSV export |

## Setup (one time)

You need Python 3.9 or newer. In a terminal, from this folder:

```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -r requirements.txt
```
```bash
python -m playwright install chromium
```

(Run `source .venv/bin/activate` again each time you open a new terminal.)

### Connect to the AWS sandbox (how this tool reaches Claude)
For the sprint, Claude runs in the CUIMC AWS sandbox through **Amazon Bedrock**, billed to the sandbox
budget. These steps follow the sprint's participant guide.

1. Accept the AWS IAM Identity Center invitation email, set a password and MFA, and sign in to the
   access portal. Open **CUIMC Innovation Sandbox** and make sure you have an active lease. Your account
   should then appear under the **Accounts** tab.
2. Install the **AWS CLI v2** using the macOS installer from
   <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>.
3. Connect the CLI to the sandbox (answers from the guide; the start URL is the one in your invitation email):
   ```bash
   aws configure sso
   ```
   SSO session name `hackathon`, start URL `https://cuimc-dev.awsapps.com/start/`, SSO region `us-east-1`,
   default client region `us-east-1`, output format `json`, profile name `hackathon`.
4. Sign in. This opens your browser, and you'll need to repeat it when the sign-in expires:
   ```bash
   aws sso login --profile hackathon
   ```
5. See which Claude models the sandbox allows:
   ```bash
   python tools/check_bedrock.py
   ```
   Put the suggested ID in `BEDROCK_MODEL` in `config.py`, then run a tiny test call:
   ```bash
   python tools/check_bedrock.py --test
   ```

**Mind the budget.** The sandbox has a $50 budget and freezes when it's used up. Three safeguards help:
- `python run.py --fetch-only` is free and prints what grading would cost on Opus, Sonnet, and Haiku.
- Every run shows its estimate and asks before spending anything.
- `MAX_SPEND_PER_RUN` in `config.py` (default $15) stops a run from starting new hospitals once its spend would
  pass the cap. It adjusts its estimates using real costs as it goes, and whatever is left gets picked up next run.
  Finished hospitals are saved, so you never pay for them twice.

Start with `--limit 3`. For cheaper runs, set `BEDROCK_MODEL` to a Sonnet model.

*Using your own Anthropic API key instead:* set `PROVIDER = "anthropic"` in `config.py`, copy `.env.example`
to `.env`, and paste your key after `ANTHROPIC_API_KEY=`.

### Add the spreadsheet
Put the CSS `.xlsx` file in `data/input/`. The spreadsheets in `data/input/` and `data/output/`
are committed to GitHub, so the Part 2 dashboard can use `data/output/hospitals.csv`. Downloaded
documents in `data/cache/` stay local because they're large and get re-created on every run.

## Running it

```bash
python run.py --fetch-only            # free: just download documents, to see what it finds
```
```bash
python run.py --limit 3               # grade the first 3 websites (a cheap test)
```
```bash
python run.py --only "Northwell"      # one system or hospital
```
```bash
python run.py                         # everything; it shows a cost estimate and asks first
```

Each run starts from the newest file in `data/output/` (or `data/input/` the first time), so
reviewer edits carry forward. Use `--input path/to/file.xlsx` to choose a different file and
`--force` to re-grade sites that haven't changed.

**Cost and time:** a full run (98 sites) on Claude Opus should cost roughly $30–60 (Bedrock prices may differ) and
take about 1–2 hours. Later runs only re-grade sites whose documents changed.

## Reading the output

Open `data/output/hfal-tracker-YYYY-MM-DD.xlsx`:

* **Orange cell = REVIEW.** Hover over it to see why. All of them are also listed in the **AI Review Queue** tab,
  with the AI's answer, its quotes, and the link. To resolve one, type `yes` or `no` in the cell. Next month's run
  keeps your answer unless the hospital's documents change.
* **Blue cell:** the AI changed the value since the previous spreadsheet (hover to see the old value).
  The **AI Change Log** tab keeps the full history, which feeds the challenge's "recent updates" requirement.
* **New columns at the end:** last checked date, number of REVIEW items, grade status, and the documents reviewed.
  While items are unresolved, the grade is a range from best case to worst case, for example
  `B to D (provisional: 2 item(s) need review)`. It becomes a single grade once a person resolves them.
* Downloaded documents are kept in `data/cache/<site>/files/` so reviewers can see exactly what the AI read.

## Testing without AI access

```bash
python tests/make_sample_sheet.py     # makes tests/sample-tracker.xlsx (3 sample hospitals)
```
```bash
python run.py --fetch-only --input tests/sample-tracker.xlsx
```
```bash
python tests/test_offline.py          # checks the safety rules with a simulated AI answer
```
```bash
python tests/test_spend_cap.py        # checks the spending cap with a fake AI
```

## Websites that block the tool

* **Sites that refuse the automated browser** but answer a simple request: the tool switches to simple requests that
  say plainly what the tool is (`HFAL-Tracker/1.0 ...`). The spreadsheet notes this for those hospitals.
* **Sites that refuse all automated access** (for example a "verify you are human" check): the tool does **not** try
  to get around this. Run `python tools/blocked_sites.py`. It creates a folder for each blocked hospital under
  `data/manual/`, with instructions inside. A person saves that hospital's documents there from a normal browser,
  and the tool grades from those files and marks the hospital as "graded from saved documents."
* **Broken links:** add the new address to `HFA_LINK_FIXES` in `config.py`. The original spreadsheet stays
  untouched; the tool uses the new link and records the change in the AI Change Log.

## Part 2: the dashboard

The `docs/` folder is a website with three tabs, a shared set of filters (region or county, system, grade,
requirement), and a detail panel for each hospital:
* **Overview:** headline numbers, the grade breakdown, compliance with each requirement, and recent changes.
* **Hospitals:** a sortable table. Select a hospital to see where it falls short, with the rule in plain language.
* **Map:** every hospital as a dot colored by grade. Hover for name, address, and system; select a dot for the link.

It's plain HTML and JavaScript, with no build step, and GitHub Pages hosts it for free.

**Update the dashboard data** after a Part 1 run (or to rebuild from the spreadsheet in `data/input/`):
```bash
python tools/build_dashboard.py
```
This writes `docs/data/hospitals.json`. Commit and push it, and the website updates within a minute or two.
The first build looks up each hospital's map location and county (US Census geocoder, with OpenStreetMap
as a fallback) and saves them in `data/geocode.json`, so later builds skip that step.

**Preview it locally:**
```bash
python3 -m http.server 8765 --directory docs
```
Then open <http://localhost:8765>.

**Turn on GitHub Pages (one time):** in the repository on github.com, go to **Settings → Pages**. Under
"Build and deployment", choose **Deploy from a branch**, select branch **main** and folder **/docs**, then select **Save**.
The site appears at `https://becca-goldrup.github.io/HFAL-Tracker/`.

## Questions for CSS (judgment calls built into the tool)

1. **FPL year.** The column says "2025 FPL Guidelines", but it's now late 2026. Should hospitals be on the
   2026 guidelines? Change `FPL_YEAR` in `config.py`.
2. **Automatic F.** The rubric lists "no policy statement posted" as an automatic F, but the spreadsheet formula
   (and the published "14 of 212 compliant") doesn't use it. The tool matches the spreadsheet by default; set
   `POLICY_STATEMENT_AUTO_FAIL = True` in `config.py` to follow the rubric table instead (17 hospitals would drop to F).
3. **Missing documents.** When the application or summary isn't found, the tool marks the related criteria
   REVIEW rather than `no`, so a person confirms the document really is missing.
4. **Plain-language law text** in `hfal/criteria.py` was drafted from the methodology document and should be
   checked by CSS before it appears on a public dashboard.
