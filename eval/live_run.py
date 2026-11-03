#!/usr/bin/env python3
"""Run the three sample checkouts against a deployed AI's Cart service and write a report.

  export AISCART_TOKEN=...            # the service token, if the server requires one (read from the environment only)
  python3 eval/live_run.py --url https://your-app.vercel.app --runs 2

Before and after the run, note the usage shown on Meta's dashboard (Usage page): the report's costs are estimates
from token counts at list prices, and the dashboard has the real charges.

Writes eval/runs/live_<time>/ with every raw response, REPORT.md and summary.json. Python 3.9+, standard library only.
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "tools"))
from aiscart.checks import score  # noqa: E402
from score_drift import consistency  # noqa: E402

SAMPLES = {"checkout_01_domain": "Domainly", "checkout_02_trial": "Sparkforge", "checkout_03_cart": "Cartwheel Office"}
QUESTION = "Should I complete this purchase?"


def post(url, payload, token):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{url}/api/analyze", data=json.dumps(payload).encode(), headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=320) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except urllib.error.URLError as e:
        return None, {"error": {"message": f"could not reach {url}: {e.reason}"}}, round(time.perf_counter() - t0, 2)
    try:
        data = json.loads(body)
    except ValueError:
        data = {"error": {"message": body[:300].decode("utf-8", "replace")}}
    return status, data, round(time.perf_counter() - t0, 2)


def summarize(sample, run, status, r, wall):
    row = {"checkout": SAMPLES[sample], "run": run, "http_status": status, "wall_s": wall}
    if status != 200:
        e = r.get("error", {})
        row.update(error=e.get("message"), step=e.get("step"), meta_status=e.get("http_status"))
        return row
    label = json.loads((HERE / "samples" / "labels" / f"{sample}.json").read_text())
    s = score(label, r["facts"])
    v = r["verdict"]
    math_failed = [c["check"] for c in r["checks"]["math"] if not c["ok"]]
    row.update(
        facts_correct=f"{sum(x['value_ok'] for x in s['rows'])} of {s['fields_scored']}",
        statuses_correct=f"{sum(x['status_ok'] for x in s['rows'])} of {s['fields_scored']}",
        invented=s["invented_details"], extra_items=s["extra_line_items"],
        flags_found=s["flags_found"], flags_missed=s["flags_missed"],
        wrong=[f"{w['field']}: expected {w['gold']} {w['gold_value']!r}, got {w['pred']} {w['pred_value']!r}" for w in s["wrong_fields"]],
        schema_problems=len(r["checks"]["schema_problems"]),
        fields_flagged=list(r["checks"]["fields_flagged"]),
        review_ran=r["review"]["ran"],
        review_changes=[f"{c['field']}: {(c.get('before') or {}).get('value')!r} -> {c['after']['value']!r}" for c in r["review"]["changes"]],
        model_decision=v.get("model_decision"), shown_decision=v["decision"], held_back=v.get("held_back"),
        verdict_checks_passed=r["verdict_checks_passed"],
        failed_verdict_checks=[f"{c['check']} ({c['detail']})" for c in r["verdict_checks"] if not c["ok"]],
        citations_normalized=[f"{c['cited']} -> {c['read_as']}" for c in r.get("citations_normalized") or []],
        math_failed=math_failed,
        # The safety property: nothing that failed a check may be shown as an approval
        approval_violation=v["decision"] in ("BUY", "TRIAL") and (not r["verdict_checks_passed"] or bool(math_failed)),
        calls=[{k: c[k] for k in ("step", "model", "latency_s", "input_tokens", "output_tokens", "est_cost_usd")} for c in r["calls"]],
        total_latency_s=r["total_latency_s"], est_cost_usd=r["total_est_cost_usd"], mode=r["mode"], versions=r["versions"],
    )
    return row


def report(rows, cons, url, runs, started):
    ok = [x for x in rows if x["http_status"] == 200]
    L = [f"# Live run, {started}", "", f"Service: {url}. {runs} run(s) per checkout. Question: \"{QUESTION}\".", ""]
    if ok:
        L.append(f"Mode: {ok[0]['mode']}. Prompt versions: " + ", ".join(f"{k} {v}" for k, v in ok[0]["versions"].items()) + ".")
        L.append("")
    viol = [x for x in ok if x["approval_violation"]]
    L += [f"**Failed checks shown as approvals: {len(viol)}** (must be 0)", "",
          "| Checkout | Run | Facts correct | Statuses correct | Invented | Fields flagged | Review changes | Model said | Shown | Verdict checks | Time (s) | Est. cost (USD) |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for x in rows:
        if x["http_status"] != 200:
            L.append(f"| {x['checkout']} | {x['run']} | Error: {x.get('error')} (step {x.get('step')}, Meta HTTP {x.get('meta_status')}) | | | | | | | | {x['wall_s']} | |")
            continue
        L.append(f"| {x['checkout']} | {x['run']} | {x['facts_correct']} | {x['statuses_correct']} | {len(x['invented'])} | "
                 f"{len(x['fields_flagged'])} | {len(x['review_changes'])} | {x['model_decision']} | {x['shown_decision']}"
                 f"{' (held back)' if x['held_back'] else ''} | {'pass' if x['verdict_checks_passed'] else 'FAIL'} | "
                 f"{x['total_latency_s']} | {x['est_cost_usd'] if x['est_cost_usd'] is not None else ''} |")
    if ok:
        tot = sum(x["est_cost_usd"] or 0 for x in ok)
        L += ["", f"Estimated cost of this run: ${tot:.4f} at list prices. Real charges: Meta dashboard, Usage page (before and after this run)."]
    if cons:
        L += ["", "## Consistency between runs", "", "| Checkout | Same status and value | Same flags |", "| --- | --- | --- |"]
        for k, c in cons.items():
            L.append(f"| {SAMPLES[k]} | {c['same']} of {c['fields_compared']} fields | {'yes' if c['flags_same'] else 'no'} |")
    L += ["", "## Details", ""]
    for x in ok:
        L.append(f"### {x['checkout']}, run {x['run']}")
        L.append("")
        for w in x["wrong"]:
            L.append(f"- Wrong: {w}")
        for d in x["invented"]:
            L.append(f"- Invented: {d}")
        for d in x["extra_items"]:
            L.append(f"- Extra item: {d}")
        if x["flags_missed"]:
            L.append(f"- Flags missed: {', '.join(x['flags_missed'])}")
        if x["fields_flagged"]:
            L.append(f"- Flagged for review: {', '.join(x['fields_flagged'])}")
        for c in x["review_changes"]:
            L.append(f"- Review changed: {c}")
        for c in x["failed_verdict_checks"]:
            L.append(f"- Verdict check failed: {c}")
        for c in x["citations_normalized"]:
            L.append(f"- Citation read as: {c}")
        L.append("- Calls: " + "; ".join(f"{c['step']} {c['model']} {c['latency_s']}s, {c['input_tokens']} in / {c['output_tokens']} out" for c in x["calls"]))
        L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Run the sample checkouts against a deployed AI's Cart")
    ap.add_argument("--url", required=True, help="e.g. https://your-app.vercel.app")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--review", default="auto", choices=["auto", "always", "never"])
    a = ap.parse_args()
    url, token = a.url.rstrip("/"), os.environ.get("AISCART_TOKEN", "").strip()
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = HERE / "runs" / f"live_{started}"
    out.mkdir(parents=True, exist_ok=True)
    print("Note Meta's dashboard usage now; the report's costs are estimates.")
    rows, facts = [], {}
    for sample in SAMPLES:
        img = base64.b64encode((HERE / "samples" / f"{sample}.png").read_bytes()).decode()
        for run in range(1, a.runs + 1):
            print(f"{SAMPLES[sample]}, run {run}...", flush=True)
            status, r, wall = post(url, {"image": img, "question": QUESTION, "review": a.review}, token)
            (out / f"{sample}_run{run}.json").write_text(json.dumps(r, indent=2))
            row = summarize(sample, run, status, r, wall)
            rows.append(row)
            if status == 200:
                facts[(sample, run)] = r["facts"]
            print(f"  HTTP {status}, {wall}s" + (f", shown {row['shown_decision']}" if status == 200 else f", {row.get('error')}"))
    cons = {s: consistency(facts[(s, 1)], facts[(s, 2)]) for s in SAMPLES if (s, 1) in facts and (s, 2) in facts}
    (out / "summary.json").write_text(json.dumps({"url": url, "rows": rows, "consistency": cons}, indent=2))
    (out / "REPORT.md").write_text(report(rows, cons, url, a.runs, started))
    print(f"\nReport: {out / 'REPORT.md'}")
    viol = sum(1 for x in rows if x.get("approval_violation"))
    sys.exit(1 if viol or any(x["http_status"] != 200 for x in rows) else 0)


if __name__ == "__main__":
    main()
