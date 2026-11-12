"""
Grading with Amazon Nova (Bedrock's own models), for when Claude isn't available
in the AWS account. Uses the same instructions, the same answer format, and the
same safety checks (hfal/verify.py) as the Claude path; only the API call differs.

Nova is reached through Bedrock's Converse API. To get an answer in the exact
format we need, we give it one "tool" whose input is the GradingResult schema and
require it to call that tool.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re

import config

TOOL_NAME = "submit_grades"
_client = None


def _client_rt():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        session = (boto3.Session(region_name=config.AWS_REGION) if os.environ.get("AWS_ACCESS_KEY_ID")
                   else boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION))
        _client = session.client("bedrock-runtime",
                                 config=Config(read_timeout=600, retries={"max_attempts": 6, "mode": "adaptive"}))
    return _client


# ---------------------------------------------------------------- schema
def _inline_schema(model_cls) -> tuple[dict, set]:
    """Pydantic JSON schema -> plain JSON schema (no $ref, no anyOf-null) that Converse tools accept.
    Returns (schema, names of top-level optional fields)."""
    raw = model_cls.model_json_schema()
    defs = raw.pop("$defs", {})
    optional_top: set = set()

    def walk(node, top=False):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            if "anyOf" in node:  # Optional[X] -> X (null allowed by leaving it out)
                options = [o for o in node["anyOf"] if o.get("type") != "null"]
                merged = walk(options[0]) if options else {}
                if "description" in node:
                    merged["description"] = node["description"] + " (leave out if unknown)"
                return merged
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if "properties" in node:  # optional fields (Optional[...]) aren't required, at any level
                opt = {name for name, prop in node["properties"].items()
                       if "anyOf" in prop and any(o.get("type") == "null" for o in prop["anyOf"])}
                if top:
                    optional_top.update(opt)
                out["required"] = [r for r in node.get("required", []) if r not in opt]
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw, top=True), optional_top


# ---------------------------------------------------------------- request
def _converse_content(blocks: list[dict]) -> list[dict]:
    """Anthropic-style content blocks -> Converse content blocks."""
    out, n_docs = [], 0
    for b in blocks:
        if b["type"] == "text":
            out.append({"text": b["text"]})
        elif b["type"] == "document" and n_docs < 5:  # Converse allows up to 5 documents
            data = base64.b64decode(b["source"]["data"])
            if len(data) <= 4_500_000:
                n_docs += 1
                name = re.sub(r"[^A-Za-z0-9 ]", " ", f"scanned {b.get('title', n_docs)}")
                out.insert(0, {"document": {"format": "pdf", "name": name, "source": {"bytes": data}}})
    return out


def _call(messages, system, tool_config):
    """One Converse call, retrying Bedrock's occasional 'unexpected error' (ModelErrorException)."""
    import time
    for attempt in range(3):
        try:
            return _client_rt().converse(
                modelId=config.NOVA_MODEL,
                system=[{"text": system}],
                messages=messages,
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": config.NOVA_MAX_TOKENS, "temperature": 0},
            )
        except Exception as e:
            if type(e).__name__ != "ModelErrorException" or attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))


def grade(system: str, blocks: list[dict], result_cls) -> tuple[object, dict, str]:
    """Returns (validated result, usage dict, model id)."""
    schema, optional_top = _inline_schema(result_cls)
    tool_config = {
        "tools": [{"toolSpec": {"name": TOOL_NAME,
                                "description": "Submit the grades for this hospital. Call this exactly once with every field.",
                                "inputSchema": {"json": schema}}}],
        "toolChoice": {"tool": {"name": TOOL_NAME}},
    }
    messages = [{"role": "user", "content": _converse_content(blocks)}]
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    last_error = None
    for attempt in (1, 2):  # one retry, telling the model what was wrong with its first answer
        r = _call(messages, system, tool_config)
        usage["input"] += r["usage"]["inputTokens"]
        usage["output"] += r["usage"]["outputTokens"]
        if r.get("stopReason") == "max_tokens":
            raise RuntimeError("Nova's answer was cut off (max_tokens); raise NOVA_MAX_TOKENS in config.py")
        content = r["output"]["message"]["content"]
        use = next((c["toolUse"] for c in content if "toolUse" in c), None)
        if use is None:
            last_error = "the model answered without calling submit_grades"
            messages += [r["output"]["message"],
                         {"role": "user", "content": [{"text": "Please call submit_grades with the complete grading."}]}]
            continue
        data = dict(use["input"])
        for name in optional_top:
            data.setdefault(name, None)
        for doc in data.get("documents") or []:  # nested optional field
            if isinstance(doc, dict):
                doc.setdefault("fpl_year", None)
        try:
            return result_cls.model_validate(data), usage, config.NOVA_MODEL
        except Exception as e:  # pydantic ValidationError
            last_error = str(e)[:1500]
            messages += [r["output"]["message"], {"role": "user", "content": [{"toolResult": {
                "toolUseId": use["toolUseId"], "status": "error",
                "content": [{"text": f"That input was invalid: {last_error}\nCall submit_grades again with every field filled in."}]}}]}]
    raise RuntimeError(f"Nova did not return a valid grading: {last_error}")
