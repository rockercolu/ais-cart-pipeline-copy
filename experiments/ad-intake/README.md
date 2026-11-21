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

## Paired authentic-ad experiment — A3/A4, 2026-11-21
Evidence: user-provided screenshots of the same genuine Kajabi Facebook ad and two browser outputs, not an automated regression suite.

- **A3 — Checkout mode (accidental routing):** The ad was uploaded through "I have a screenshot." The checkout-specific pipeline recognized Kajabi and the free 30-day trial, found no subtotal, tax, due-now amount or renewal price, and returned **WAIT**. It reported "No better option found" without a stated purchase goal. Muse Wonder re-read three flagged fields and changed none. Reported processing 32.286 s and estimated model cost $0.0440. This is an appropriately cautious checkout check but a mismatched analysis type for an ad.
- **A4 — Ad mode (intended routing):** The same ad was uploaded through "I saw an ad." The ad pipeline returned **RESEARCH — claims not verified**, extracted Kajabi's advertised content, website, audience and product-sales claims and free 30-day trial, and flagged unknown post-trial pricing, trial conditions and subscription fees. It said **"No exact product-name match; functional overlap not assessed."**
- **Unexpected discovery:** A user-selection mistake created a controlled comparison: identical image, different pipelines and different questions. It supports explicit screenshot-type routing, and suggests future automatic ad/checkout classification with user confirmation.
- **Caveat:** The results do not independently verify Kajabi's promises or whether the user's existing tools replace Kajabi. A3's WAIT and A4's RESEARCH are not directly comparable purchase verdicts.
- **UX observation:** Clicking a blue action button while scrolled down left the user staring at the lower form with no visible loading feedback on desktop.

## Experimental follow-up — A5
- Changed `showAnswerPanel()` to scroll to the answer area on **desktop and mobile**, not just small screens.
- When clicking **Review this ad**, show the loading message and scroll to it immediately, before the model responds; scroll again after success or failure.
- Added an explainable **potential capability overlap** screen against tools explicitly saved in the browser inventory. Ad claims trigger limited capability categories; matching saved names are displayed with a caution to verify actual functionality, plan limits and pricing.
- No claim of automatic subscription detection, verified features, universal tool coverage or confirmed redundancy. No automatic purchase approval.
- Still to test manually: Safari scroll position when the button is pressed, same-screen loading indicator, Kajabi with Squarespace explicitly saved, Kajabi with no saved tools, Explee with an outreach tool saved, mobile behavior, and unchanged checkout/goal workflows.

## A5 — Live user-observed result, 2026-11-21
Evidence: user-provided Safari screenshots of real Kajabi advertisement analysis in experimental A5 preview, plus user's explicit confirmation of scrolling behavior.

- **PASS — immediate scroll:** User reports that clicking the blue **Review this ad** button immediately jumped to the answer area. This confirms the intended scroll behavior in that browser session; the intermediate loading text was not independently captured.
- **PASS — advertisement extraction:** Kajabi identified, content/website/audience/product sales claims and 30-day trial extracted; unverified post-trial price, terms and destination URL surfaced.
- **PASS — browser inventory association:** Squarespace shown as one saved tool; output identified potential website building, digital product/course sales, and email marketing/audience growth overlap. It explicitly cautioned that this is preliminary screening, not feature-by-feature verification.
- **Open:** duplicated trial offer text; actual Squarespace plan and feature eligibility not checked; mobile behavior not checked; checkout/goal regression not rerun.

## A6 — Explee AI paired inventory experiment (planned, not yet executed)
- **Source:** original user-provided Explee AI advertisement screenshot (not a synthetic fixture).
- **Ad claims to look for, not independently verified:** prospect discovery, outreach emails, starting conversations, and $30 trial credits. Do not assume a subscription price or promise successful booked meetings.
- **Controlled baseline:** In **I saw an ad**, upload the Explee image with an empty browser tool inventory; review the extraction and missing-cost/terms flags.
- **Treatment:** Add a real already-owned lead-generation or outreach tool to **Tools you already have** and rerun the identical ad, keeping the optional goal unchanged. Record the exact tool name and plan, if known.
- **Expected:** A6 should flag a potential functional overlap only when the saved tool matches a relevant capability. It must not imply that trial credits are a price, or claim verified feature parity.
- **Capture:** screenshot of the ad extraction, overlap section, warnings, and whether the page scrolls immediately.
- **Status:** protocol documented; pending live browser test and results.
