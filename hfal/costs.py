"""
Cost estimates, so a run never surprises you (the AWS sandbox has a hard $50 budget).

Prices are Anthropic list prices in $ per million tokens; Bedrock charges about the
same but may differ slightly. Treat every number here as an estimate.
"""
from __future__ import annotations

from pathlib import Path

import config

# (substring of the model id, input $/M, output $/M). First match wins.
PRICES = [
    ("opus-5-5", 4.00, 20.00), ("opus", 5.00, 25.00),
    ("sonnet-5-5", 2.00, 10.00), ("sonnet-5", 2.00, 10.00), ("sonnet", 3.00, 15.00),
    ("haiku-5-5", 0.10, 0.50), ("haiku", 1.00, 5.00),
]
OUTPUT_TOKENS_PER_SITE = 15_000   # answer + thinking, a generous guess
TOKENS_PER_SCANNED_PAGE = 2_000   # scanned PDFs are read as page images


def current_model() -> str:
    return config.BEDROCK_MODEL if config.PROVIDER == "bedrock" else config.MODEL


def prices(model: str | None = None) -> tuple[float, float]:
    m = (model or current_model()).lower()
    for key, pin, pout in PRICES:
        if key in m:
            return pin, pout
    return 5.00, 25.00  # unknown model: assume the expensive end


def site_input_tokens(site) -> int:
    tokens = 3_000  # instructions
    for d in site.documents:
        if d.error:
            continue
        if d.scanned and d.file_path and Path(d.file_path).exists():
            tokens += d.pages * TOKENS_PER_SCANNED_PAGE
        else:
            text = d.text
            if d.language_hint and d.language_hint != "English":
                text = text[:config.TRANSLATION_PREVIEW_CHARS]
            tokens += len(text) // 4
    return tokens


def estimate_site(site, model: str | None = None) -> float:
    pin, pout = prices(model)
    return (site_input_tokens(site) * pin + OUTPUT_TOKENS_PER_SITE * pout) / 1e6


def actual(usage: dict, model: str | None = None) -> float:
    pin, pout = prices(model)
    return (usage.get("input", 0) * pin + usage.get("output", 0) * pout
            + usage.get("cache_write", 0) * pin * 1.25 + usage.get("cache_read", 0) * pin * 0.1) / 1e6
