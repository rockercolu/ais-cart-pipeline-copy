# AI's Cart pipeline

**One picture. One question. A better purchase.**

AI's Cart checks a checkout screenshot before you pay. You send the screenshot and a question, and it returns a
BUY, TRIAL, WAIT or REJECT verdict. Every fact behind the verdict is marked as observed on screen, inferred, or
unknown, with the evidence for it.

Built for the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). All code in this repo was written during
the hackathon.

## How it works

| Step | Who | What happens |
| --- | --- | --- |
| 1. Extract | Muse Spark 1.3 | Reads every field from the screenshot: items, prices, totals, discounts, tax, renewal, trial and cancellation terms. Each field is observed, inferred or unknown, with evidence. |
| 2. Check | Plain code | Checks the math (items add up to the subtotal; subtotal minus discount plus tax equals the total; a renewal price is stated for recurring or multi-year charges) and picks fields worth a second look. |
| 3. Review | Muse Wonder 1.0 | Re-reads **only the flagged fields** against the screenshot. Skipped when nothing is flagged, so clean checkouts cost one fewer call. |
| 4. Verdict | Muse Spark 1.3, then code | Decides BUY / TRIAL / WAIT / REJECT from the checked facts only. The verdict model never sees the screenshot. The verdict can only cite this checkout's real field paths (they're listed in its prompt and enforced in its schema), and obvious variants such as `trial_terms.value` are read as the real field and recorded in `citations_normalized`. Code then checks the verdict: every cited field must exist, every dollar amount must come from the facts or simple arithmetic on them, and there's no BUY or TRIAL while a code check fails. **If any check fails, the verdict is held back and shown as WAIT**, so a failed check can never reach a user as an approval. The model's original answer is kept in `model_*` fields for the record. |

Why this design: in our tests both models read clean checkouts correctly, and the code checks alone caught a
checkout whose total didn't add up and a model that listed the same item twice. So the cheap check runs every time,
and the second model is only paid for when the check finds something.

## First live test

The three sample checkouts in `eval/samples/` have answer keys, so a live run can be scored automatically.
Whoever holds the service token runs:

```
export AISCART_TOKEN=...      # read from the environment only, never written to disk
python3 eval/live_run.py --url https://<your-app>.vercel.app --runs 2
```

It saves every raw response and writes `eval/runs/live_<time>/REPORT.md` with, per checkout and run: facts and
statuses correct, invented details, fields flagged, what the review changed, the model's decision and the decision
shown, verdict checks, time per call, tokens and estimated cost, plus consistency between the two runs and a count of
failed checks shown as approvals (which must be 0). Note the usage on Meta's dashboard before and after: the report's
costs are estimates at list prices, and the dashboard has the real charges.

The version the team reviewed before the first live test is kept on the `baseline-2026-11-02` branch.

## Try it locally

Python 3.9 or later, no packages to install.

```
MOCK=1 python3 server.py          # sample answers, no API key needed
MODEL_API_KEY=LLM_... python3 server.py   # live Meta models
```

Then open http://localhost:8000, pick a sample checkout (or upload your own) and press **Check before I buy**.
Mock mode recognizes the three sample screenshots in `eval/samples/` and answers the way the pipeline would.

## Deploy (Vercel)

1. Import this repo at [vercel.com/new](https://vercel.com/new). No build settings are needed.
2. Add environment variables:

| Variable | Required | Meaning |
| --- | --- | --- |
| `MODEL_API_KEY` | Yes, for live mode | Meta Model API key (starts with `LLM_`) |
| `SERVICE_TOKEN` | Recommended | Callers must send `Authorization: Bearer <token>`. Keeps strangers from spending your credits. |
| `MOCK` | No | `1` to serve sample answers instead of calling Meta |
| `EXTRACT_MODEL`, `REVIEW_MODEL`, `VERDICT_MODEL` | No | Defaults: `muse-spark-1.3`, `muse-wonder-1.0`, `muse-spark-1.3` |
| `TEMPERATURE`, `REASONING` | No | Defaults: `0` and `medium` |
| `RATE_LIMIT_PER_HOUR` | No | Requests per IP per hour, default 60. `0` turns it off. |
| `ALLOW_ORIGIN` | No | CORS origin, default `*` |

3. Deploy, then open `https://<your-app>.vercel.app/api/health`. It should say `"mode": "live"`.

Limits to know: Vercel allows up to 300 seconds per request on the free plan (a full run took 40 to 80
seconds in our live tests) and 4.5 MB per request. The demo page shrinks large screenshots before sending them.

## API

### `POST /api/analyze`

```http
POST /api/analyze
Authorization: Bearer <SERVICE_TOKEN>
Content-Type: application/json

{
  "image": "<base64 PNG/JPEG/WebP/GIF, or a data: URL>",
  "question": "Should I complete this purchase?",
  "review": "auto"
}
```

`review` is `auto` (default: only when checks flag something), `always` or `never`.

`verdict.decision` is what to show users. `verdict.held_back` is true when the model's answer failed a check; then
`decision` is WAIT, `reasons` explain why in plain words, and `model_decision`, `model_headline` and `model_reasons`
keep the model's original answer.

The demo page shows these codes to shoppers as BUY, TEST (for TRIAL), WAIT and DON'T BUY (for REJECT), with the
amount due today, the recurring billing risk and the one-line `headline` at the top. Other apps can use the same
mapping.

Response, shortened (the numbers are examples, not measurements):

```json
{
  "mode": "live",
  "verdict": {
    "decision": "WAIT",
    "headline": "You'd pay $100.00 now, but the renewal price isn't shown",
    "reasons": [{"text": "The renewal price is not stated.", "fields": ["renewal_terms"]}],
    "check_before_buying": ["Find the renewal price before paying"],
    "confidence": "medium",
    "model_decision": "WAIT",
    "held_back": false
  },
  "verdict_checks_passed": true,
  "verdict_checks": [{"check": "every dollar amount comes from the facts", "ok": true, "detail": "..."}],
  "facts": {
    "total_due_now": {"status": "observed", "value": "$100.00", "evidence": "Total due today $100.00"},
    "renewal_terms": {"status": "observed", "value": "Renews automatically at the then-current rate", "evidence": "..."},
    "line_items": [{"name": {"status": "observed", "value": "acme-robotics.com", "evidence": "..."}}]
  },
  "checks": {"math": [{"check": "subtotal - discount + tax = total", "ok": true, "detail": "..."}], "fields_flagged": {}},
  "review": {"ran": true, "model": "muse-wonder-1.0", "changes": []},
  "calls": [{"step": "extract", "model": "muse-spark-1.3", "latency_s": 14.0, "input_tokens": 3500, "output_tokens": 600, "est_cost_usd": 0.0069}],
  "total_latency_s": 31.2,
  "total_est_cost_usd": 0.021,
  "versions": {"extract_prompt": "d33cd6c8", "review_prompt": "4c693e1f", "verdict_prompt": "0a3a360f"}
}
```

Errors come back as `{"error": {"code", "message", ...}}`: 400 bad input, 401 wrong token, 413 too large,
429 rate limited, 502 a model call failed (with `step` and Meta's `http_status`), 503 no key configured.

Cost figures assume Meta's published list prices; the dashboard's Usage page has the real charges.

### `GET /api/health`

Shows the mode (live, mock or not configured), model settings and prompt versions.

### Calling it from another app (for example Floot)

Send the screenshot as base64 in `image` and show `verdict`, `facts` and `calls`. Call it from your app's server
side if you can, so the service token isn't visible in the browser.

## Repo layout

| Path | What it is |
| --- | --- |
| `aiscart/` | The pipeline: schema and prompt, code checks, review logic, verdict and guardrails, Meta client, HTTP layer |
| `api/` | Vercel functions (`/api/analyze`, `/api/health`) |
| `server.py`, `index.html` | Local server and the demo page |
| `tests/test_service.py` | End-to-end tests against a fake Meta API: live path, mock mode, guardrails and hold-back, auth, errors, Vercel function |
| `eval/` | The evaluation kit: sample checkouts with answer keys, scoring, the live test runner (`live_run.py`), the pipeline experiment and our Oct 30 playground results |

## Tests

```
python3 tests/test_service.py
cd eval && python3 tests/selftest.py && python3 tests/pipeline_selftest.py
```

All tests run offline against fakes of Meta's API. The live path was first run against Meta's real API on
Nov 3, 2026, with `eval/live_run.py`.

## Known limitations

- On a trial checkout, a plan row like "$25.00/mo" with $0.00 due today can be read either way, so the extracted
  line total varies between runs ($0.00 or $25.00/mo). Our answer key marks it ambiguous and doesn't score it. The
  line total doesn't feed the math checks when no subtotal is shown, and in both Nov 3 reruns the amount due today
  was read correctly as $0.00.

## Team

| Name | Role |
| --- | --- |
| Steven Lance Rocker | Founder/Product & Editorial Research |
| Amir Aman | AI Pipeline/Engineering |
