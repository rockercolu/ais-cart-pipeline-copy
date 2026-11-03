"""Step 4: the BUY / TRIAL / WAIT / REJECT verdict, and the code checks that guard it.

The verdict model sees only the verified facts and check results, never the screenshot, so it can't read
anything new off the page. Code then checks its answer: every cited field must exist, and every dollar
amount it mentions must come from the facts or simple arithmetic on them.
"""
import itertools
import json
import re

from .checks import WITH_SYMBOL
from .schema import ITEM_FIELDS, TOP_FIELDS

DECISIONS = ["BUY", "TRIAL", "WAIT", "REJECT"]

VERDICT_SYSTEM = """You advise a founder who is about to complete a purchase. You get the facts extracted from their
checkout screenshot (each one observed, inferred or unknown, with evidence), the results of math checks on those
facts, and the founder's question. Decide one of:

- BUY: the facts are complete enough and the purchase fits the question.
- TRIAL: a free or low-cost trial lets them test first. Say what to check before it converts to paid.
- WAIT: something that matters is unknown or unclear, such as a renewal price, cut-off terms or totals that don't
  add up. Say exactly what to check.
- REJECT: the facts show the purchase is a poor deal or a trap for this goal.

Rules:
- Use only the facts given. Unknown fields are risks, not zeros.
- Every reason lists the field paths it relies on, exactly as they appear in the facts (for example total_due_now,
  renewal_terms, line_items[0].line_total).
- Never state a price, saving or date that isn't in the facts. If you compute an amount, show the arithmetic.
- If a math check failed, say so in a reason.
Return only JSON that matches the schema."""

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": DECISIONS},
        "headline": {"type": "string"},
        "reasons": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "fields"], "additionalProperties": False}},
        "check_before_buying": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["decision", "headline", "reasons", "check_before_buying", "confidence"],
    "additionalProperties": False,
}


def verdict_text(facts, math, question):
    return "\n".join([
        f"Founder's question: {question}",
        "",
        "Facts from the checkout screenshot:",
        json.dumps(facts, indent=2),
        "",
        "Math checks on those facts:",
        json.dumps(math, indent=2),
        "",
        "Field paths you can cite (use these exact strings, nothing else):",
        ", ".join(sorted(field_paths(facts))),
    ])


def verdict_schema(facts):
    """VERDICT_SCHEMA with the cited fields limited to this checkout's real field paths."""
    s = json.loads(json.dumps(VERDICT_SCHEMA))
    s["properties"]["reasons"]["items"]["properties"]["fields"]["items"] = {"type": "string", "enum": sorted(field_paths(facts))}
    return s


_SUFFIX = re.compile(r"\.(value|status|evidence)$")


def normalize_citations(v, facts):
    """Map obvious variants of a valid path onto it (facts.total_due_now.value -> total_due_now). Anything that
    doesn't map stays as written, so the citation check still catches it. Returns (verdict copy, list of changes)."""
    known = field_paths(facts)
    n_items = len(facts.get("line_items") or [])
    out, changes = json.loads(json.dumps(v)), []
    for r in out.get("reasons") or []:
        fixed = []
        for f in r.get("fields") or []:
            g = _SUFFIX.sub("", str(f).strip().replace(" ", ""))
            g = g[len("facts."):] if g.startswith("facts.") else g
            m = re.match(r"^line_items\[(\d+)\]$", g)
            if m and int(m.group(1)) < n_items:
                g = f"line_items[{m.group(1)}].name"  # citing a whole row points at the row's name
            if g in known and g != f:
                changes.append({"cited": f, "read_as": g})
            fixed.append(g if g in known else f)
        r["fields"] = fixed
    return out, changes


def field_paths(facts):
    paths = set(TOP_FIELDS)
    for i, _ in enumerate(facts.get("line_items") or []):
        paths |= {f"line_items[{i}].{k}" for k in ITEM_FIELDS}
    return paths


def fact_amounts(facts):
    """Every dollar amount that appears in a fact's value."""
    vals = [facts.get(k) for k in TOP_FIELDS]
    for it in facts.get("line_items") or []:
        vals += [(it or {}).get(k) for k in ITEM_FIELDS]
    out = set()
    for f in vals:
        if isinstance(f, dict) and f.get("status") != "unknown" and f.get("value"):
            for m in WITH_SYMBOL.finditer(str(f["value"])):
                out.add(round(float(m.group(3).replace(",", "")), 2))
    return out


def supported(amount, base):
    """True if an amount is a fact, a sum or difference of two facts, or a fact times 2 to 12 (months, years)."""
    if any(abs(amount - b) <= 0.01 for b in base):
        return True
    for a, b in itertools.combinations(sorted(base), 2):
        if abs(amount - (a + b)) <= 0.01 or abs(amount - abs(a - b)) <= 0.01:
            return True
    return any(abs(amount - b * k) <= 0.01 for b in base for k in range(2, 13))


def validate_verdict(v, facts, math):
    """Code checks on the model's verdict. Returns a list of {check, ok, detail}; the verdict itself is not changed."""
    out = []
    if v.get("decision") not in DECISIONS:
        out.append({"check": "decision is one of BUY, TRIAL, WAIT, REJECT", "ok": False, "detail": repr(v.get("decision"))})
        return out
    known = field_paths(facts)
    cited = [f for r in v.get("reasons") or [] for f in (r.get("fields") or [])]
    bad = sorted({f for f in cited if f not in known})
    out.append({"check": "every cited field exists", "ok": not bad,
                "detail": "all cited fields found" if not bad else "not in the facts: " + ", ".join(bad)})
    out.append({"check": "every reason cites at least one field",
                "ok": all(r.get("fields") for r in v.get("reasons") or []) and bool(v.get("reasons")),
                "detail": f"{len(v.get('reasons') or [])} reason(s)"})

    base = fact_amounts(facts)
    texts = [v.get("headline") or ""] + [r.get("text") or "" for r in v.get("reasons") or []] + list(v.get("check_before_buying") or [])
    unsupported = []
    for t in texts:
        for m in WITH_SYMBOL.finditer(t):
            amt = round(float(m.group(3).replace(",", "")), 2)
            if not supported(amt, base):
                unsupported.append(m.group(0).strip())
    out.append({"check": "every dollar amount comes from the facts", "ok": not unsupported,
                "detail": "all amounts traced to the facts" if not unsupported else "not traceable: " + ", ".join(sorted(set(unsupported)))})

    failed = [c["check"] for c in math if not c["ok"]]
    if v["decision"] in APPROVALS:
        out.append({"check": "no BUY or TRIAL while a code check fails", "ok": not failed,
                    "detail": "all code checks passed" if not failed else "failed: " + "; ".join(failed)})
    return out


APPROVALS = ("BUY", "TRIAL")


def finalize(v, checks):
    """What users see. If any verdict check failed, the answer is held back as WAIT: a failed check can never
    reach the user as BUY or TRIAL. The model's own answer is kept in model_* fields for the record."""
    failed = [c for c in checks if not c["ok"]]
    out = dict(v, model_decision=v.get("decision"), held_back=bool(failed))
    if failed:
        # Plain explanations only. The model's own words can carry the very error that was caught (an invented
        # amount, say), so they stay in model_* fields and in verdict_checks, not in what users read.
        out.update(
            decision="WAIT",
            headline="Not approved yet: this recommendation didn't pass our checks, so look at these points before buying",
            reasons=[{"text": PLAIN.get(c["check"], "The recommendation didn't pass a check.") +
                      (f" ({c['detail'][len('failed: '):]})" if c["check"] == APPROVAL_CHECK else ""),
                      "fields": FIELDS_FOR.get(c["check"], [])} for c in failed],
            check_before_buying=["Compare the facts table with the checkout before paying"],
            confidence="low",
            model_headline=v.get("headline"),
            model_reasons=v.get("reasons"),
            model_check_before_buying=v.get("check_before_buying"),
        )
    return out


APPROVAL_CHECK = "no BUY or TRIAL while a code check fails"
PLAIN = {
    "decision is one of BUY, TRIAL, WAIT, REJECT": "The recommendation wasn't a valid decision.",
    "every cited field exists": "The recommendation relied on information that isn't in the checkout.",
    "every reason cites at least one field": "Part of the recommendation wasn't tied to anything in the checkout.",
    "every dollar amount comes from the facts": "The recommendation mentioned an amount that isn't in the checkout.",
    APPROVAL_CHECK: "The checkout's numbers don't add up, or a key price is missing.",
}
FIELDS_FOR = {APPROVAL_CHECK: ["subtotal", "discounts", "tax", "total_due_now", "renewal_terms"]}
