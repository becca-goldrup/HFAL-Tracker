"""
Step 3: decide what is safe to write, and what needs a human.

This is the anti-hallucination layer. Claude's answer only becomes a "yes" or
"no" in the spreadsheet if ALL of these hold:
  * Claude was confident (not "unclear", "not_found", or low confidence)
  * every quote it gave can actually be found in the document it cited
  * the kind of proof the rubric requires is there (see Criterion.yes_proof / no_proof)
  * application / summary criteria are backed by the application / summary
  * a number-based answer (Max FPL, FPL year) agrees with the number Claude extracted
Otherwise the cell is written as REVIEW with the reason attached.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

import config
from hfal.criteria import GRADED, NO, REVIEW, TEXT_COLUMNS, YES
from hfal.fetch import SiteFetch

ROLE_FOR_SCOPE = {"application": "application", "summary": "policy_summary"}


@dataclass
class Decision:
    value: str                       # yes / no / REVIEW
    reason: str                      # why (shown in the Review Queue and cell comment)
    evidence: list[str] = field(default_factory=list)  # 'D3: "quote" (url)'
    ai_answer: str = ""
    confidence: str = ""


# ---------------------------------------------------------------- quote matching
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\[page \d+\]", " ", s)
    s = re.sub(r"[^\w%$]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote: str, source: str) -> bool:
    """True if the quote (allowing '...' gaps and PDF spacing glitches) is in source."""
    src = _norm(source)
    src_nospace = src.replace(" ", "")
    pieces = [p for p in re.split(r"\.\.\.|…", quote) if _norm(p)]
    if not pieces:
        return False
    for piece in pieces:
        q = _norm(piece)
        if q in src or q.replace(" ", "") in src_nospace:
            continue
        # Fuzzy fallback for small extraction differences (hyphenation, ligatures).
        if len(q) >= 25:
            m = SequenceMatcher(None, src_nospace, q.replace(" ", ""), autojunk=False)
            match = m.find_longest_match(0, len(src_nospace), 0, len(q.replace(" ", "")))
            if match.size >= 0.9 * len(q.replace(" ", "")):
                continue
        return False
    return True


MIN_QUOTE_WORDS = 5

# Wording that often signals a violation. Matches only send an item to REVIEW
# (they never mark a hospital non-compliant on their own), so erring broad is fine.
_DEADLINE = re.compile(r"\b(\d{2,3}|thirty|sixty|ninety|twelve|six|three)\s*(\(\d+\)\s*)?(calendar\s+)?(days?|months?|years?)\b"
                       r"[^.]{0,80}?\b(after|from|of|following|before)\b", re.I)
_DEADLINE_CONTEXT = re.compile(r"\b(apply|applying|application|request|submit|complete)", re.I)
_DEADLINE_IGNORE = re.compile(r"collection agenc|send you|notify you|decision|respond|we will|will receive|process", re.I)
_ASSETS = re.compile(r"bank statements?|savings account|checking account|\bassets?\b|real estate|property you own|"
                     r"stocks|retirement account|401\s*\(?k\)?|\bvehicles?\b|resources you own", re.I)
_IMMIGRATION = re.compile(r"citizen(ship)?|immigra\w*|green card|\balien\b|undocumented|\bvisa\b|"
                          r"lawful(ly)? (present|resident)|legal (status|resident)|proof of residency", re.I)
_IMMIGRATION_OK = re.compile(r"shall not|not be|regardless|does not|doesn.t|not a factor|not required|not an eligibility|"
                             r"not consider|no matter|national origin|discriminat|medicare|medicaid|age\s+of\s+65", re.I)
# Common harmless contexts for asset words: "assets may not be considered", Medicare/FSA explanations, car accidents.
_ASSETS_OK = re.compile(r"not be considered|not considered|may not|will not|cannot|not consider|does not|"
                        r"spending account|health savings|motor vehicle|third party|liab", re.I)


def _snippet(text: str, m) -> str:
    return re.sub(r"\s+", " ", text[max(0, m.start() - 70):m.end() + 70]).strip()


def red_flags(site: SiteFetch) -> dict[str, list[tuple[str, str]]]:
    """Scan the downloaded documents ourselves for wording the AI may have missed."""
    out = {"no_time_limit": [], "no_asset_checks": [], "no_immigration_barrier": []}
    for d in site.documents:
        if d.error or not d.text:
            continue
        t = d.text
        for m in _DEADLINE.finditer(t):
            around = t[max(0, m.start() - 150):m.end() + 150]
            if _DEADLINE_CONTEXT.search(around) and not _DEADLINE_IGNORE.search(around):
                out["no_time_limit"].append((d.doc_id, _snippet(t, m)))
        for m in _ASSETS.finditer(t):
            if not _ASSETS_OK.search(t[max(0, m.start() - 80):m.end() + 80]):
                out["no_asset_checks"].append((d.doc_id, _snippet(t, m)))
        for m in _IMMIGRATION.finditer(t):
            if not _IMMIGRATION_OK.search(t[max(0, m.start() - 80):m.end() + 80]):
                out["no_immigration_barrier"].append((d.doc_id, _snippet(t, m)))
    return out


# ---------------------------------------------------------------- decisions
def decide(site: SiteFetch, graded: dict) -> tuple[dict[str, Decision], dict[str, str], list[str]]:
    """Returns (decisions by criterion key, text column values, hospital-level warnings)."""
    r = graded["result"]
    docs = {d.doc_id: d for d in site.documents}
    roles: dict[str, set] = {}
    for dr in r["documents"]:
        if dr["doc_id"] in docs and not docs[dr["doc_id"]].error:
            for role in dr["roles"]:
                roles.setdefault(role, set()).add(dr["doc_id"])
    warnings = list(graded.get("warnings", []))
    if not site.landing_ok:
        warnings.append(f"HFA page could not be opened: {site.error}")
    elif site.error:
        warnings.append(f"Some documents may be missing: {site.error}")
    warnings += [n for n in site.notes if "person" in n]  # graded from hand-saved files: say so

    out: dict[str, Decision] = {}
    for c in GRADED:
        f = r["findings"][c.key]
        ans, conf = f["answer"], f["confidence"]
        ev_lines, bad, unverifiable, wrong_scope, good, short = [], [], [], [], 0, 0
        for q in f["evidence"]:
            d = docs.get(q["doc_id"])
            ev_lines.append(f'{q["doc_id"]}: "{q["quote"]}"' + (f" ({d.url})" if d else ""))
            if d is None:
                bad.append(f"cited {q['doc_id']}, which doesn't exist")
            elif d.scanned:
                unverifiable.append(q["doc_id"])
            elif not quote_found(q["quote"], d.text):
                bad.append(f"quote not found in {q['doc_id']}")
            elif len(_norm(q["quote"]).split()) < MIN_QUOTE_WORDS:
                short += 1  # a heading like "How To Apply" isn't evidence
            else:
                good += 1
                need_role = ROLE_FOR_SCOPE.get(c.scope)
                if need_role and q["doc_id"] not in roles.get(need_role, set()):
                    wrong_scope.append(q["doc_id"])

        def review(why: str) -> Decision:
            return Decision(REVIEW, why, ev_lines, ans, conf)

        if ans == "unclear":
            d = review(f"AI unsure: {f['reasoning']}")
        elif ans == "not_found":
            d = review(f"AI could not find the needed document: {f['reasoning']}")
        elif conf == "low":
            d = review(f"AI said '{ans}' with low confidence: {f['reasoning']}")
        elif bad:
            d = review("Possible hallucination -- " + "; ".join(bad) + f". AI said '{ans}': {f['reasoning']}")
        elif unverifiable:
            d = review(f"AI said '{ans}' based on scanned PDF(s) {', '.join(unverifiable)} that can't be machine-checked: {f['reasoning']}")
        elif wrong_scope:
            d = review(f"Evidence came from {', '.join(wrong_scope)}, not the {c.scope} (rubric says judge from the {c.scope} only)")
        elif c.requires_doc and c.requires_doc not in roles:
            hint = (f' Tip: search "hospital financial assistance application {config.FPL_YEAR} <hospital name>", and add the '
                    f"link to EXTRA_DOCUMENTS in config.py." if c.requires_doc == "application" else "")
            d = review(f"No {c.requires_doc.replace('_', ' ')} was found among the downloaded documents, so this can't be judged automatically.{hint}")
        else:
            proof = c.yes_proof if ans == "yes" else c.no_proof
            if proof == "review":
                hint = (f' Tip: search "hospital financial assistance application {config.FPL_YEAR} <hospital name>".'
                        if c.key == "application_posted" else "")
                d = review(f"AI said '{ans}'. A missing document can't be confirmed automatically "
                           f"(it may be on another page) -- please check the website.{hint} {f['reasoning']}")
            elif proof == "quote" and good == 0:
                why = " (its quotes were too short to count as evidence, e.g. a heading)" if short else ""
                d = review(f"AI said '{ans}' but gave no verifiable quote{why}: {f['reasoning']}")
            else:
                d = Decision(YES if ans == "yes" else NO, f["reasoning"], ev_lines, ans, conf)
        out[c.key] = d

    # ---- cross-checks on numbers the AI extracted
    fpl = out["max_fpl_400"]
    pct = r.get("max_fpl_percent")
    if fpl.value != REVIEW:
        if pct is None:
            out["max_fpl_400"] = Decision(REVIEW, f"AI said '{fpl.value}' but did not report the FPL %", fpl.evidence, fpl.ai_answer, fpl.confidence)
        elif (pct >= 400) != (fpl.value == YES):
            out["max_fpl_400"] = Decision(REVIEW, f"AI answer '{fpl.value}' contradicts its own number ({pct}%)", fpl.evidence, fpl.ai_answer, fpl.confidence)
    yr = out["fpl_current_year"]
    used = r.get("fpl_year_used")
    if yr.value != REVIEW and used is not None and (used == config.FPL_YEAR) != (yr.value == YES):
        out["fpl_current_year"] = Decision(REVIEW, f"AI answer '{yr.value}' contradicts the FPL year it found ({used}; expected {config.FPL_YEAR})", yr.evidence, yr.ai_answer, yr.confidence)

    # ---- red-flag scan: the tool reads the documents itself before accepting "nothing wrong found"
    flags = red_flags(site)
    for key, label in (("no_time_limit", "a deadline to apply"), ("no_asset_checks", "an asset check"),
                       ("no_immigration_barrier", "an immigration-status condition")):
        dec = out[key]
        if dec.value == YES and flags[key]:
            hits = "; ".join(f'{doc}: "...{snip}..."' for doc, snip in flags[key][:3])
            out[key] = Decision(REVIEW, f"AI found nothing like {label}, but the documents contain wording that may be one -- "
                                        f"please check: {hits}", dec.evidence + [hits], dec.ai_answer, dec.confidence)
    dec = out["consistent_across_documents"]
    if dec.value == YES and flags["no_time_limit"]:
        out["consistent_across_documents"] = Decision(
            REVIEW, "AI called the documents consistent, but at least one mentions a deadline to apply -- check whether "
                    "the others say the same: " + "; ".join(f'{d}: "...{s}..."' for d, s in flags["no_time_limit"][:2]),
            dec.evidence, dec.ai_answer, dec.confidence)

    # ---- the full Uniform Application includes these, so "yes, entire UA" + "missing X" can't both be true
    if out["entire_uniform_application"].value == YES:
        for key in ("income_tables_in_application", "installments_capped_5pct", "contact_info_in_application"):
            dec = out[key]
            if dec.value == NO:
                out[key] = Decision(REVIEW, f"Contradiction: AI said the hospital uses the entire Uniform Application "
                                            f"(which includes this) but also that the application lacks it. {dec.reason}",
                                    dec.evidence, dec.ai_answer, dec.confidence)

    # ---- free-text columns
    text = {
        "timeframe_notes": r["timeframe_notes"],
        "inconsistency_notes": r["inconsistency_notes"],
        "languages_available": ", ".join(r["languages_available"]) or "N/A",
        "general_notes": r["general_notes"],
        "contact_phone": r.get("contact_phone") or "N/A",
        "application_notes": r["application_notes"]
            + (f" | Max FPL found: {pct}%" if pct is not None else ""),
        "summary_notes": r["summary_notes"],
    }
    if r.get("psa_definition_quote"):
        text["general_notes"] += f' | PSA as written: "{r["psa_definition_quote"]}"'
    if r.get("missing_material_notes") and r["missing_material_notes"] != "N/A":
        warnings.append("AI noted missing/unreadable material: " + r["missing_material_notes"])
    assert set(text) == set(TEXT_COLUMNS)
    return out, text, warnings


def max_fpl_cell(decision: Decision, pct: Optional[int]):
    """The sheet stores Max FPL as a multiple of 100% (4 = 400%) or 'no'."""
    if decision.value == YES and pct:
        return round(pct / 100, 2) if pct % 100 else pct // 100
    return decision.value
