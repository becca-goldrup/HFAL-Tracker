"""
Check the connection to Claude in the sprint's AWS sandbox (Amazon Bedrock).

    python tools/check_bedrock.py                 # sign-in check + list Claude models
    python tools/check_bedrock.py --test          # also make one tiny, cheap test call

Sign in first:  aws sso login --profile hackathon
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def session():
    import boto3
    if os.environ.get("AWS_ACCESS_KEY_ID"):
        return boto3.Session(region_name=config.AWS_REGION)
    return boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)


def rank(model_id: str):
    """Most capable first: Opus > Sonnet > Haiku, then newest version."""
    tier = 0 if "opus" in model_id else 1 if "sonnet" in model_id else 2
    nums = [int(n) for n in re.findall(r"\d+", model_id.split("claude")[-1].split("-v")[0])[:2]]
    nums += [0] * (2 - len(nums))          # "opus-5" -> 5.0, "opus-5-5" -> 5.5
    return (tier, tuple(-n for n in nums))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="make one tiny test call")
    args = ap.parse_args()

    # 1. Are we signed in?
    try:
        ident = session().client("sts").get_caller_identity()
        print(f"1. Signed in to AWS account {ident['Account']}  OK")
    except Exception as e:
        sys.exit(f"1. Not signed in ({type(e).__name__}: {e}).\n"
                 f"   Run: aws sso login --profile {config.AWS_PROFILE}")

    # 2. Which Claude models can this sandbox use?
    bedrock = session().client("bedrock")
    ids = []
    for page in bedrock.get_paginator("list_inference_profiles").paginate():
        ids += [p["inferenceProfileId"] for p in page["inferenceProfileSummaries"]
                if p["inferenceProfileId"].startswith("us.anthropic.")]
    if not ids:
        sys.exit("2. No Claude models (us.anthropic.*) are available. Ask an organizer.")
    ids.sort(key=rank)
    print("2. Claude models available (most capable first):")
    for i in ids:
        print("     " + i + ("   <- currently in config.py" if i == config.BEDROCK_MODEL else ""))
    if not config.BEDROCK_MODEL:
        print(f'\n   Next: in config.py set  BEDROCK_MODEL = "{ids[0]}"')
        return

    # 3. One tiny call, using the same structured-answer feature the grader uses.
    if args.test:
        from pydantic import BaseModel
        from hfal.grader import get_client

        class Ping(BaseModel):
            ok: bool
            message: str

        msg = get_client().beta.messages.parse(
            model=config.BEDROCK_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": "Reply ok=true and a five-word greeting."}],
            output_format=Ping, output_config={"effort": "low"},
        )
        text = next(b.text for b in msg.content if b.type == "text")
        print(f"3. Test call to {config.BEDROCK_MODEL}: {Ping.model_validate_json(text)}  OK")
        print("\nAll set. Try:  python run.py --limit 3")


if __name__ == "__main__":
    main()
