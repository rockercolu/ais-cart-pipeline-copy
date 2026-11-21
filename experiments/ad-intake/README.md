# Ad intake experiment — frozen seed A1

Branch: `experiment/ad-intake-v1` (isolated from `main`).

## Goal
Allow a shopper to submit an advertisement screenshot, not only a checkout screenshot. Preserve the existing cart and goal-first paths and all checkout safety rules. This is a proposed feature, not a verified live capability.

## First dataset (user-supplied Facebook ad screenshots, 2026-11-20)
| Advertiser | Visible claim | Evidence status |
| --- | --- | --- |
| Kajabi | Content, website, audience, products; 30-day trial | Advertised, not verified |
| Explee AI | Finds prospects, drafts emails, books calls; $30 credits | Advertised, not verified |
| Braintrust | Model comparisons and evals | Advertised, not verified |
| Orbis | Outbound process and reply handling | Partial ad, not verified |
| Vibe.co | Growth advertising | Partial ad, not verified |
| OpenArt AI | Create app launch video from link and screenshots | Advertised, not verified |
| Babylovegrowth | Organic traffic / AI search visibility; 3-day trial | Advertised, not verified |
| Pancake AI | Sales/marketing assistance | Partial ad, not verified |
| Wynora | License original footage/audio/images for AI teams | Advertised, not verified |
| Workshop AI | Local offline AI, free/unlimited claims | Advertised, not verified |

Do not commit users' raw social-media screenshots to a public repository without explicit approval. The table is a text-only fixture.

## Product behavior
1. Add a third intake choice: `I saw an ad`.
2. Accept an image and optional product URL / shopper goal; label the uploaded content as an ad.
3. Extract advertiser, product, claims, trial/credit/price terms, links, and unknowns; retain per-claim evidence and confidence.
4. Compare to owned tools, but never assume an advertised feature works.
5. Return research-oriented advice with explicit observed/inferred/unknown status. Never treat a promotional claim as a verified fact. No BUY/TRIAL approval without checkout-grade verification.
6. Keep discovery status separate from owned-tool status: discovered, investigating, trial, active, rejected, canceled.
7. Treat ad text as untrusted input, never as executable instructions.

## Technical design
- Frontend: add `ad` mode to the existing `shot` / `goal` UI state. Keep screenshot selection, cancellation, stale-response protections and upload compression.
- API: add an ad-specific extraction/review path rather than routing ad images through checkout arithmetic and missing-renewal checks.
- Recommendation: use existing owned-tools and goal-first matching; clearly separate editorial alternatives from paid placements.
- Persistence: defer until consent and schema review; no new production database tables in this seed.
- Demo/sample mode: return a labeled `RESEARCH FURTHER` result for unverified ad uploads, not a fabricated analysis.

## Acceptance tests
- Existing checkout sample tests remain unchanged and passing.
- Existing goal-first flow remains unchanged and passing.
- Ad mode never reports checkout math errors for an ad.
- Extracted trial language is a claim, not an established price.
- Multiple ads are separate records; no mixing evidence across screenshots.
- Switching image/mode clears stale verdicts.
- No automatic trial signups, payments, outreach, or uploads to third parties.
- Mobile UI at 360px and 390px.
- Document what was tested versus what remains unverified.

## Review handoff
Open a draft PR only after the first functional implementation and regression checks. Ask Amir and Sanvi to assess backend routing, image extraction, matcher compatibility, privacy, and deployment. Do not merge without review.

## Live experiment log — 2026-11-21 (user-observed browser screenshots)
Source: user-shared screenshots of the experimental Vercel preview. These are visual observations, not automated test results. Both test images were purpose-built simulated advertisements, not authentic Facebook advertisements.

### A1 — Kajabi simulated advertisement
- Browser drag/drop preview: screenshot selected and displayed.
- Authenticated live vision response: yes, after an isolated preview-only SERVICE_TOKEN was configured.
- Advertiser: Kajabi (correct).
- Product: "courses and digital products" (category description, not a precise product name).
- Visible claims: "Build and sell your knowledge"; "Create courses and digital products"; "Website and audience tools"; "30-day free trial advertised" (all present in fixture).
- Advertised offer: 30-day free trial advertised (correct).
- Still needs verification: "Renewal price: NOT SHOWN" (correct).
- Verdict: RESEARCH — claims not verified (appropriate).
- Gap: results do not prominently flag that the fixture says "SIMULATED TEST AD — NOT A REAL OFFER."

### A2 — Explee AI simulated advertisement
- Authenticated live vision response: yes.
- Advertiser: Explee AI (correct).
- Product: "Not legible" (needs review; brand is legible but product may not be separately named).
- Visible claims: "Find prospects"; "Start conversations"; "AI-assisted prospect discovery"; "Automated outreach emails"; "$30 trial credits advertised" (all present in fixture).
- Verdict: RESEARCH — claims not verified (appropriate).
- The screenshot cuts off the lower output, so the advertised-offer section and ongoing-usage-cost warning were not independently inspected. Do not mark those as passed until the full result is captured.

### Status and open tests
- Two of two controlled fixtures produced visible analyses; not equivalent to two fully passing acceptance suites.
- Authentication, image selection, basic extraction, evidence display and research-first framing have been observed.
- Not yet validated: authentic Facebook ad, pricing/feature verification, inventory overlap beyond exact name, full Explee output, mobile widths, existing cart/goal regression suite, cost/latency, prompt injection, and checkout flow isolation.
- Next: test one authentic user-supplied Facebook ad, record visible extracted claims and unknowns, then compare against human reading.
- Security: experimental SERVICE_TOKEN is branch-specific; no secrets or screenshots containing secrets should be committed.
