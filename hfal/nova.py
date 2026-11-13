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


def _fill_gaps(data: dict, result_cls) -> None:
    """A question the model skipped counts as 'unclear' (-> human review), never as an answer."""
    findings = data.get("findings")
    if not isinstance(findings, dict):
        findings = data["findings"] = {}
    for key in result_cls.model_fields["findings"].annotation.model_fields:
        f = findings.get(key)
        if not isinstance(f, dict):
            f = findings[key] = {}
        if f.get("answer") not in ("yes", "no", "unclear", "not_found"):
            f["answer"], f["confidence"] = "unclear", "low"   # no usable answer -> review
        if f.get("confidence") not in ("high", "medium", "low"):
            f["confidence"] = "low"
        if not isinstance(f.get("evidence"), list):
            f["evidence"] = []
        f["evidence"] = [e if isinstance(e, dict) else {"sentence_id": str(e)} for e in f["evidence"]]
        f["evidence"] = [e for e in f["evidence"] if e.get("sentence_id")]
        f.setdefault("reasoning", "The model gave no explanation.")
    # Document list: fill fields the model left out (they only describe documents; they don't grade anything).
    docs = data.get("documents")
    data["documents"] = [d for d in docs if isinstance(d, dict) and d.get("doc_id")] if isinstance(docs, list) else []
    for d in data["documents"]:
        d.setdefault("roles", [])
        d["roles"] = [r for r in d["roles"] if r in ("landing_page", "application", "policy_summary",
                                                     "policy_statement", "supplemental", "not_relevant")]
        d.setdefault("language", "unknown")
        d.setdefault("is_nys_uniform_application", False)
        d.setdefault("fpl_year", None)
    for name, field in result_cls.model_fields.items():
        if name in data or name == "findings":
            continue
        ann = str(field.annotation)
        data[name] = [] if ann.startswith(("typing.List", "list")) else (None if "Optional" in ann else "N/A")


def _call_plain(messages, system, model):
    import time
    for attempt in range(2):
        try:
            return _client_rt().converse(modelId=model, system=[{"text": system}], messages=messages,
                                         inferenceConfig={"maxTokens": config.NOVA_MAX_TOKENS, "temperature": 0})
        except Exception as e:
            if type(e).__name__ != "ModelErrorException" or attempt == 1:
                raise
            time.sleep(10)


def _call(messages, system, tool_config, model):
    """One Converse call, retrying Bedrock's occasional 'unexpected error' (ModelErrorException)."""
    import time
    for attempt in range(3):
        try:
            return _client_rt().converse(
                modelId=model,
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
    """Returns (validated result, usage dict, model id). If the main model keeps failing on a
    site (e.g. 'invalid sequence as part of ToolUse'), tries the fallback model once."""
    # Plain JSON first: in testing, Nova Pro's tool-call format broke on ~40% of hospitals.
    attempts = [(_grade_text, config.NOVA_MODEL), (_grade, config.NOVA_MODEL)]
    fallback = getattr(config, "NOVA_FALLBACK_MODEL", "")
    if fallback and fallback != config.NOVA_MODEL:
        attempts += [(_grade_text, fallback), (_grade, fallback)]
    errors = []
    for fn, model in attempts:
        try:
            return fn(system, blocks, result_cls, model)
        except Exception as e:
            errors.append(f"{model} ({'json' if fn is _grade_text else 'tool'}): {str(e)[:160]}")
    raise RuntimeError(" | ".join(errors))


def _grade_text(system: str, blocks: list[dict], result_cls, model: str) -> tuple[object, dict, str]:
    """Same request, but the answer comes back as plain JSON text instead of a tool call
    (avoids Nova's occasional 'invalid sequence as part of ToolUse')."""
    schema, optional_top = _inline_schema(result_cls)
    instruction = ("\n\nRespond with ONLY one JSON object, no other text, that follows this JSON schema "
                   "(include every field of 'findings'):\n" + json.dumps(schema))
    r = _call_plain([{"role": "user", "content": _converse_content(blocks)}], system + instruction, model)
    usage = {"input": r["usage"]["inputTokens"], "output": r["usage"]["outputTokens"], "cache_read": 0, "cache_write": 0}
    if r.get("stopReason") == "max_tokens":
        raise RuntimeError("answer was cut off (max_tokens)")
    text = "".join(c.get("text", "") for c in r["output"]["message"].get("content", []))
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("no JSON in the answer")
    data = json.loads(text[start:end + 1], strict=False)  # tolerate raw line breaks inside strings
    for name in optional_top:
        data.setdefault(name, None)
    for doc in data.get("documents") or []:
        if isinstance(doc, dict):
            doc.setdefault("fpl_year", None)
    _fill_gaps(data, result_cls)
    return result_cls.model_validate(data), usage, model + " (json)"


def _grade(system: str, blocks: list[dict], result_cls, model: str) -> tuple[object, dict, str]:
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
        r = _call(messages, system, tool_config, model)
        usage["input"] += r["usage"]["inputTokens"]
        usage["output"] += r["usage"]["outputTokens"]
        if r.get("stopReason") == "max_tokens":
            raise RuntimeError("Nova's answer was cut off (max_tokens); raise NOVA_MAX_TOKENS in config.py")
        if not r["output"]["message"].get("content"):  # empty answer: keep the conversation valid for the retry
            r["output"]["message"] = {"role": "assistant", "content": [{"text": "(no answer)"}]}
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
        _fill_gaps(data, result_cls)
        try:
            return result_cls.model_validate(data), usage, model
        except Exception as e:  # pydantic ValidationError
            last_error = str(e)[:1500]
            messages += [r["output"]["message"], {"role": "user", "content": [{"toolResult": {
                "toolUseId": use["toolUseId"], "status": "error",
                "content": [{"text": f"That input was invalid: {last_error}\nCall submit_grades again with every field filled in."}]}}]}]
    raise RuntimeError(f"Nova did not return a valid grading: {last_error}")
