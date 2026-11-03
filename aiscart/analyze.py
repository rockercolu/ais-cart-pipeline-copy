"""The full screenshot-to-verdict run.

1. Extract   Muse Spark reads every field from the screenshot (observed / inferred / unknown, with evidence)
2. Check     plain code runs math and schema checks and picks fields worth a second look
3. Review    Muse Wonder re-reads only those fields; skipped when nothing is flagged
4. Verdict   BUY / TRIAL / WAIT / REJECT from the checked facts only, then code checks the verdict
"""
import copy
import hashlib
import os

from .checks import check_schema, math_checks
from .meta import MetaError, est_cost
from .review import REVIEW_SYSTEM, merge, review_schema, review_text, select_fields
from .schema import DEFAULT_QUESTION, SCHEMA, SYSTEM_PROMPT
from .verdict import VERDICT_SYSTEM, finalize, normalize_citations, validate_verdict, verdict_schema, verdict_text

ALWAYS_REVIEW = ["subtotal", "discounts", "tax", "total_due_now", "renewal_terms", "trial_terms", "cancellation_terms"]


def _v(text):
    return hashlib.sha256(text.encode()).hexdigest()[:8]


VERSIONS = {"extract_prompt": _v(SYSTEM_PROMPT), "review_prompt": _v(REVIEW_SYSTEM), "verdict_prompt": _v(VERDICT_SYSTEM)}


def settings_from_env():
    t = os.environ.get("TEMPERATURE", "0").strip()
    return {
        "extract_model": os.environ.get("EXTRACT_MODEL", "muse-spark-1.3"),
        "review_model": os.environ.get("REVIEW_MODEL", "muse-wonder-1.0"),
        "verdict_model": os.environ.get("VERDICT_MODEL", "muse-spark-1.3"),
        "temperature": float(t) if t else None,
        "reasoning": os.environ.get("REASONING", "medium").strip() or None,
    }


class StepError(Exception):
    def __init__(self, step, err, calls):
        super().__init__(str(err))
        self.step, self.err, self.calls = step, err, calls


def analyze(image, mime, question, client, settings, review="auto"):
    """image: raw bytes. review: auto | always | never. Returns the result dict; raises StepError if a call fails."""
    question = (question or "").strip() or "Should I complete this purchase?"
    calls = []

    def call(step, model, system, text, img, name, schema, hint=None):
        try:
            parsed, usage, latency = client.chat(model, system, text, img, name, schema,
                                                 settings.get("temperature"), settings.get("reasoning"), hint)
        except MetaError as e:
            raise StepError(step, e, calls)
        calls.append({"step": step, "model": model, "latency_s": latency,
                      "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                      "est_cost_usd": est_cost(model, usage)})
        return parsed

    # 1. Extract
    first = call("extract", settings["extract_model"], SYSTEM_PROMPT, DEFAULT_QUESTION, (image, mime), "cart_extraction", SCHEMA)

    # 2. Check
    picks, math_first = select_fields(first)
    if review == "always":
        for p in ALWAYS_REVIEW:
            picks.setdefault(p, ["review requested for every money and terms field"])
    if review == "never":
        picks_used = {}
    else:
        picks_used = picks

    # 3. Review
    facts, changes = copy.deepcopy(first), []
    if picks_used:
        corrections = call("review", settings["review_model"], REVIEW_SYSTEM, review_text(first, picks_used),
                           (image, mime), "cart_review", review_schema(list(picks_used)))
        facts, changes = merge(first, corrections, picks_used)
    math = math_checks(facts)

    # 4. Verdict (text only: the verdict model never sees the screenshot)
    model_verdict = call("verdict", settings["verdict_model"], VERDICT_SYSTEM, verdict_text(facts, math, question),
                         None, "cart_verdict", verdict_schema(facts), hint={"facts": facts, "math": math})
    model_verdict, citation_fixes = normalize_citations(model_verdict, facts)
    verdict_checks = validate_verdict(model_verdict, facts, math)
    verdict = finalize(model_verdict, verdict_checks)  # a failed check is held back as WAIT, never shown as BUY/TRIAL

    lat = [c["latency_s"] for c in calls if c["latency_s"] is not None]
    cost = [c["est_cost_usd"] for c in calls if c["est_cost_usd"] is not None]
    return {
        "mode": client.mode,
        "question": question,
        "verdict": verdict,
        "verdict_checks": verdict_checks,
        "verdict_checks_passed": all(c["ok"] for c in verdict_checks),
        "citations_normalized": citation_fixes,
        "facts": facts,
        "checks": {"math": math, "math_before_review": math_first, "schema_problems": check_schema(facts),
                   "fields_flagged": picks},
        "review": {"ran": bool(picks_used), "model": settings["review_model"] if picks_used else None,
                   "changes": [c for c in changes if c.get("applied")],
                   "skipped_because": None if picks_used else ("review turned off" if review == "never" and picks else "nothing flagged")},
        "facts_before_review": first if picks_used else None,
        "calls": calls,
        "total_latency_s": round(sum(lat), 3) if lat else None,
        "total_est_cost_usd": round(sum(cost), 6) if cost else None,
        "settings": settings,
        "versions": VERSIONS,
        "image_sha256": hashlib.sha256(image).hexdigest(),
    }
