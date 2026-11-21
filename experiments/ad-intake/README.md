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
