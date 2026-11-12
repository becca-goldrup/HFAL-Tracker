"""
Step 2: ask Claude to grade one hospital's documents against the rubric.

Claude must answer in a fixed JSON shape (structured outputs), and every YES/NO
must come with verbatim quotes and the document id they came from. We don't
trust those quotes blindly -- hfal/verify.py checks each one against the text we
downloaded before anything is written to the spreadsheet.
"""
from __future__ import annotations

import base64
import os
import json
from pathlib import Path
from typing import List, Literal, Optional

import anthropic
from pydantic import BaseModel, Field, create_model

import config
from hfal.criteria import GRADED
from hfal.fetch import SiteFetch, site_slug


# ---------------------------------------------------------------- answer shape
class Quote(BaseModel):
    doc_id: str = Field(description="Document id, e.g. D3")
    quote: str = Field(description="Exact words copied from that document (1-3 sentences). Never paraphrase.")


class Finding(BaseModel):
    answer: Literal["yes", "no", "unclear", "not_found"]
    confidence: Literal["high", "medium", "low"]
    evidence: List[Quote]
    reasoning: str = Field(description="One or two sentences explaining the answer, citing doc ids.")


DocRoleName = Literal["landing_page", "application", "policy_summary", "policy_statement",
                      "supplemental", "not_relevant"]


class DocRole(BaseModel):
    doc_id: str
    roles: List[DocRoleName]
    language: str = Field(description="Language the document is written in, e.g. English, Spanish")
    is_nys_uniform_application: bool
    fpl_year: Optional[int] = Field(description="FPL guideline year the document uses, if any")


Findings = create_model("Findings", **{c.key: (Finding, ...) for c in GRADED})


class GradingResult(BaseModel):
    documents: List[DocRole]
    findings: Findings  # type: ignore[valid-type]
    max_fpl_percent: Optional[int] = Field(description="Highest % of FPL covered, per the APPLICATION only (e.g. 400)")
    fpl_year_used: Optional[int] = Field(description="FPL year used in the APPLICATION")
    contact_phone: Optional[str] = Field(description="Primary HFA help phone number on the APPLICATION")
    languages_available: List[str] = Field(description="Languages the application / summary / policy are posted in")
    psa_definition_quote: Optional[str] = Field(description="Exact wording that defines the primary service area, if any")
    psa_counties: List[str] = Field(description="Counties/areas the hospital says its PSA covers")
    timeframe_notes: str = Field(description="Deadline wording if any; 'N/A' if none")
    inconsistency_notes: str = Field(description="Differences between the hospital's own documents; 'N/A' if none")
    application_notes: str = Field(description="Prohibited questions, omitted Uniform Application parts, FPL issues; 'N/A' if none")
    summary_notes: str = Field(description="Notes about the plain language summary; 'N/A' if none")
    general_notes: str = Field(description="Other notes, e.g. still uses the term 'charity care'; 'N/A' if none")
    missing_material_notes: str = Field(description="Anything that seems linked/mentioned but missing or unreadable; 'N/A' if none")


# ---------------------------------------------------------------- prompt
def _criteria_block() -> str:
    lines = []
    for c in GRADED:
        q = c.question.format(fpl_year=config.FPL_YEAR)
        scope = {"all": "ALL documents",
                 "application": "the APPLICATION ONLY (pretend the other documents do not exist)",
                 "summary": "the PLAIN LANGUAGE SUMMARY ONLY (pretend the other documents do not exist)"}[c.scope]
        lines.append(f"- {c.key}  [column {c.column}, {c.section}; look at {scope}]\n"
                     f"  Question: {q}\n" + (f"  Rules: {c.guidance}\n" if c.guidance else ""))
    return "\n".join(lines)


SYSTEM = f"""You are auditing a New York hospital's compliance with the reformed NY Hospital Financial Assistance Law (HFAL) for the Community Service Society of New York. Your answers feed a public compliance tracker used by advocates, regulators and lawmakers.

You will receive every document we could download from the hospital's financial assistance web page: the landing page text, linked pages, PDFs and Word files. Each has an id (D1, D2, ...).

How to work (this follows the CSS manual methodology):
1. First classify every document (application, policy_summary, policy_statement, landing_page, supplemental, not_relevant) and note its language. A document can have more than one role, e.g. a landing page that is also the plain language summary. Translations of the same document share its role.
2. Read everything carefully. Time limits, immigration status, asset checks and the primary service area can appear anywhere.
3. APPLICATION criteria: judge using ONLY the application. If the application says 400% FPL but other documents say 300%, the application criterion is YES and you record the conflict in inconsistency_notes. Same for FPL year.
4. PLAIN LANGUAGE SUMMARY criteria: judge using ONLY the summary.
5. For every criterion, YES always means COMPLIANT.

Answer values:
- "yes" / "no": you found clear support. Give 1-3 short VERBATIM quotes (exact words, copied character for character from the document text you were given) with the doc_id. For a "yes" that rests on something being absent (e.g. no time limit anywhere), evidence may be empty, but say so in reasoning.
- "not_found": the document needed to answer (e.g. the application) is not among the documents.
- "unclear": the documents are ambiguous, contradict each other in a way that matters, are unreadable, or you are unsure. Explain why.

Accuracy rules -- these matter more than finishing:
- Never invent or paraphrase quotes. Every quote is checked by a program against the source text; a quote that cannot be found sends the item to human review.
- Never guess. A wrong answer could lead a patient to think they qualify for assistance when they don't, or the reverse. When in doubt, answer "unclear" with low confidence.
- Do not use outside knowledge about this hospital. Only the documents count. You MAY use general knowledge of NY geography (counties and which counties border each other) for the primary service area question, and you should state the counties you relied on.
- Documents in other languages count. Translations that are truncated previews are only there to show which languages are posted.

The {len(GRADED)} graded criteria:
{_criteria_block()}

Also fill in the note fields. Use "N/A" for a note when there is nothing to say."""


def _documents_content(site: SiteFetch, hospitals: list[dict]) -> tuple[list[dict], list[str]]:
    """Build the user message. Returns (content blocks, warnings)."""
    warnings: list[str] = []
    names = "\n".join(f"- {h['name']} ({h['address']}, {h['city']} NY {h['zip']}); system: {h['system']}"
                      for h in hospitals)
    header = (f"Hospital(s) that use this financial assistance page:\n{names}\n\n"
              f"Financial assistance page: {site.hfa_url}\n"
              f"Downloaded: {site.fetched_at}\n\n")
    if site.skipped_links:
        header += f"Note: {len(site.skipped_links)} more relevant-looking links were not downloaded (cap reached).\n"
    blocks: list[dict] = []
    text_parts = [header]
    budget = config.MAX_CHARS_PER_HOSPITAL
    for d in site.documents:
        meta = f'id="{d.doc_id}" kind="{d.kind}" url="{d.url}" link_text="{d.link_text}"'
        if d.language_hint:
            meta += f' link_says_language="{d.language_hint}"'
        if d.error:
            text_parts.append(f"<document {meta}>\n[COULD NOT DOWNLOAD: {d.error}]\n</document>\n")
            continue
        if d.scanned and d.file_path and Path(d.file_path).stat().st_size < 15_000_000:
            # No text layer: let Claude read the PDF pages as images.
            text_parts.append(f"<document {meta}>\n[Scanned PDF -- attached below as a PDF with title {d.doc_id}]\n</document>\n")
            blocks.append({"type": "document", "title": d.doc_id,
                           "source": {"type": "base64", "media_type": "application/pdf",
                                      "data": base64.standard_b64encode(Path(d.file_path).read_bytes()).decode()}})
            continue
        text = d.text
        if d.language_hint and d.language_hint != "English" and len(text) > config.TRANSLATION_PREVIEW_CHARS:
            text = text[:config.TRANSLATION_PREVIEW_CHARS] + "\n[... translation preview truncated ...]"
        if len(text) > budget:
            warnings.append(f"{d.doc_id} was cut short because this hospital's documents exceeded the size cap")
            text = text[:max(0, budget)] + "\n[... TRUNCATED: size cap reached ...]"
        budget -= len(text)
        text_parts.append(f"<document {meta}>\n{text}\n</document>\n")
    text_parts.append("Grade this hospital against every criterion.")
    return blocks + [{"type": "text", "text": "\n".join(text_parts)}], warnings


# ---------------------------------------------------------------- API call
_client = None


def get_client():
    """Claude via the AWS sandbox (Bedrock) or via an Anthropic API key, per config.py."""
    global _client
    if _client is None:
        if config.PROVIDER == "bedrock":
            if os.environ.get("AWS_ACCESS_KEY_ID"):
                # Temporary keys pasted from the AWS access portal ("Option B")
                _client = anthropic.AnthropicBedrock(aws_region=config.AWS_REGION, max_retries=4)
            else:
                _client = anthropic.AnthropicBedrock(aws_profile=config.AWS_PROFILE,
                                                     aws_region=config.AWS_REGION, max_retries=4)
        else:
            _client = anthropic.Anthropic(max_retries=4)
    return _client


def model_id() -> str:
    if config.PROVIDER == "bedrock":
        if not config.BEDROCK_MODEL:
            raise RuntimeError("Set BEDROCK_MODEL in config.py (run `python tools/check_bedrock.py` to see options)")
        return config.BEDROCK_MODEL
    return config.MODEL


def grade_site(site: SiteFetch, hospitals: list[dict]) -> dict:
    """Call Claude. Returns a dict that is saved to data/cache/<site>/result.json."""
    content, warnings = _documents_content(site, hospitals)
    extra = {}
    if config.PROVIDER == "anthropic":
        # If a safety filter wrongly declines, the API retries on another model.
        # (Not available on Bedrock; there a decline just sends the hospital to review.)
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    with get_client().beta.messages.stream(
        model=model_id(),
        max_tokens=config.MAX_OUTPUT_TOKENS,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_format=GradingResult,
        output_config={"effort": config.EFFORT},
        **extra,
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError(f"Model declined to grade ({getattr(msg.stop_details, 'category', None)})")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Answer was cut off (max_tokens); raise MAX_OUTPUT_TOKENS in config.py")
    text = next(b.text for b in msg.content if b.type == "text")
    result = GradingResult.model_validate_json(text)
    u = msg.usage
    return {
        "fingerprint": site.fingerprint(),
        "model": msg.model,
        "graded_at": site.fetched_at,
        "fpl_year_setting": config.FPL_YEAR,
        "warnings": warnings,
        "usage": {"input": u.input_tokens, "output": u.output_tokens,
                  "cache_read": u.cache_read_input_tokens or 0,
                  "cache_write": u.cache_creation_input_tokens or 0},
        "result": json.loads(result.model_dump_json()),
    }


def result_path(hfa_url: str) -> Path:
    return config.CACHE_DIR / site_slug(hfa_url) / "result.json"


def load_result(hfa_url: str) -> Optional[dict]:
    p = result_path(hfa_url)
    return json.loads(p.read_text()) if p.exists() else None


def save_result(hfa_url: str, data: dict) -> None:
    p = result_path(hfa_url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False))
