"""
Turn a "[Review decisions]" GitHub issue (opened from the dashboard's Submit to
GitHub button) into a decisions file in data/reviews/. Run by the
apply-review-issue workflow, with ISSUE_BODY, ISSUE_NUMBER and ISSUE_AUTHOR set.
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

REVIEWS_DIR = config.ROOT / "data" / "reviews"


def main():
    body = os.environ.get("ISSUE_BODY", "")
    number = re.sub(r"\D", "", os.environ.get("ISSUE_NUMBER", "0")) or "0"
    author = os.environ.get("ISSUE_AUTHOR", "")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", body, re.S)
    if not m:
        sys.exit("No decisions block found in the issue.")
    data = json.loads(m.group(1))
    decisions = data.get("decisions")
    if not isinstance(decisions, list) or not decisions or len(decisions) > 500:
        sys.exit("The decisions block is empty or too large.")
    data["reviewer"] = (str(data.get("reviewer") or "").strip() or author)[:80]
    data["submitted"] = str(data.get("submitted") or date.today().isoformat())[:10]
    data["source"] = f"GitHub issue #{number} by {author}"
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEWS_DIR / f"reviews-{data['submitted']}-issue{number}.json"
    out.write_text(json.dumps(data, indent=1))
    print(f"Saved {len(decisions)} decision(s) to data/reviews/{out.name}")


if __name__ == "__main__":
    main()
