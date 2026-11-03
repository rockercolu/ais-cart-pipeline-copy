"""Calls to Meta's Model API (OpenAI-compatible Chat Completions), plus a mock client for building without a key."""
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

DEFAULT_BASE = "https://api.meta.ai/v1"
# Assumed list prices, USD per 1M tokens (input, output). The dashboard's Usage page has the real charges.
PRICES = {"muse-spark-1.3": (1.25, 4.25), "muse-spark-1.1": (1.25, 4.25), "muse-wonder-1.0": (4.00, 20.00)}


class MetaError(Exception):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status, self.body = status, body


def est_cost(model, usage):
    pin, pout = PRICES.get(model, (None, None))
    if pin is None or usage.get("prompt_tokens") is None:
        return None
    return round(usage["prompt_tokens"] / 1e6 * pin + (usage.get("completion_tokens") or 0) / 1e6 * pout, 6)


def parse_json_content(content):
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    content = (content or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content, re.S)
    return json.loads(fenced.group(1) if fenced else content)


class MetaClient:
    mode = "live"

    def __init__(self, key, base=None, timeout=150):
        self.key, self.base, self.timeout = key, (base or DEFAULT_BASE).rstrip("/"), timeout

    def chat(self, model, system, text, image=None, schema_name=None, schema=None, temperature=None, reasoning=None, hint=None):
        """One call. image = (bytes, mime) or None. Returns (parsed JSON, usage dict, latency seconds)."""
        content = [{"type": "text", "text": text}]
        if image:
            raw, mime = image
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}})
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema}}
        if temperature is not None:
            body["temperature"] = temperature
        if reasoning:
            body["reasoning_effort"] = reasoning
        req = urllib.request.Request(f"{self.base}/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, raw = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:
            raise MetaError(f"Could not reach Meta's API: {getattr(e, 'reason', e)}")
        latency = round(time.perf_counter() - t0, 3)
        if status != 200:
            raise MetaError(f"Meta's API returned HTTP {status}", status, raw[:1500])
        try:
            data = json.loads(raw)
            parsed = parse_json_content(data["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise MetaError(f"The model's answer was not valid JSON ({type(e).__name__})", status, raw[:1500])
        return parsed, data.get("usage") or {}, latency


# ---------- mock: canned answers so the app can be built and demoed before a key works ----------

MOCK_DATA = Path(__file__).resolve().parent / "mock_data.json"


@lru_cache(maxsize=1)
def _mock_labels():
    try:
        return json.loads(MOCK_DATA.read_text())
    except (OSError, ValueError):
        return {}


def _from_label(label):
    def f(v):
        if v["status"] == "ambiguous":
            return {"status": "unknown", "value": None, "evidence": "not clear on screen"}
        return {"status": v["status"], "value": v["value"], "evidence": v.get("evidence") or ""}
    out = {k: f(v) for k, v in label.items() if isinstance(v, dict)}
    out["line_items"] = [{k: f(v) for k, v in it.items()} for it in label["line_items"]]
    out["uncertainty_flags"] = list(label.get("uncertainty_flags") or [])
    return out


def mock_verdict(facts, math):
    from .checks import money
    failed = [c for c in math if not c["ok"]]
    total = (facts.get("total_due_now") or {}).get("value")
    if (facts.get("total_due_now") or {}).get("status") == "unknown":
        # Not one of the three samples: mock mode read nothing, so it must not approve anything
        return {"decision": "WAIT", "headline": "Sample mode only knows the three sample checkouts, so it can't check this one",
                "reasons": [{"text": "Sample mode doesn't read new screenshots; the live version does.", "fields": ["total_due_now"]}],
                "check_before_buying": ["Try one of the three sample checkouts, or see the demo video for a live run"], "confidence": "low"}
    if any("total" in c["check"] or "subtotal" in c["check"] for c in failed):
        return {"decision": "WAIT", "headline": f"The totals on this checkout don't add up, so don't pay {total or 'yet'} until they do",
                "reasons": [{"text": "A math check on the order summary failed.", "fields": ["subtotal", "discounts", "tax", "total_due_now"]}],
                "check_before_buying": ["Ask the seller to correct the total"], "confidence": "medium"}
    if failed and money(facts.get("renewal_terms")) is None:
        return {"decision": "WAIT", "headline": f"You'd pay {total} now, but the renewal price isn't shown",
                "reasons": [{"text": f"{total} is due today.", "fields": ["total_due_now"]},
                            {"text": "The renewal price is not stated.", "fields": ["renewal_terms"]}],
                "check_before_buying": ["Find the renewal price before paying"], "confidence": "medium"}
    if (facts.get("trial_terms") or {}).get("status") in ("observed", "inferred"):
        return {"decision": "TRIAL", "headline": f"Start the trial, and decide before it converts: {facts['trial_terms']['value']}",
                "reasons": [{"text": "A trial is offered before any charge.", "fields": ["trial_terms", "total_due_now"]},
                            {"text": "Cancellation terms apply before the trial ends.", "fields": ["cancellation_terms"]}],
                "check_before_buying": ["Set a reminder before the cancellation deadline"], "confidence": "medium"}
    return {"decision": "BUY", "headline": f"The checkout is complete and adds up to {total}",
            "reasons": [{"text": "Line items, discount and tax add up to the total.", "fields": ["subtotal", "total_due_now"]}],
            "check_before_buying": [], "confidence": "medium"}


class MockClient:
    """Answers like the real models would on the three sample checkouts; anything else gets an all-unknown answer."""
    mode = "mock"

    def chat(self, model, system, text, image=None, schema_name=None, schema=None, temperature=None, reasoning=None, hint=None):
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        if schema_name == "cart_extraction":
            sha = hashlib.sha256(image[0]).hexdigest() if image else ""
            label = _mock_labels().get(sha)
            if label:
                return _from_label(label), usage, 0.0
            from .schema import TOP_FIELDS
            unk = {"status": "unknown", "value": None, "evidence": "mock mode: only the three sample screenshots are recognized"}
            return {**{k: dict(unk) for k in TOP_FIELDS}, "line_items": [], "uncertainty_flags": ["other"]}, usage, 0.0
        if schema_name == "cart_review":
            return {"corrections": []}, usage, 0.0
        if schema_name == "cart_verdict":
            return mock_verdict(hint["facts"], hint["math"]), usage, 0.0
        raise MetaError(f"mock has no answer for {schema_name}")


def client_from_env():
    """MOCK=1 gives the mock. Otherwise a live client if MODEL_API_KEY is set, else None."""
    if os.environ.get("MOCK", "").strip() in ("1", "true", "yes"):
        return MockClient()
    key = os.environ.get("MODEL_API_KEY", "").strip()
    return MetaClient(key, os.environ.get("MODEL_API_BASE")) if key else None
