# First-user account and payment pilot

Branch: `work/first-user-pilot`. Entry: `/pilot.html`. Existing screenshot/goal tester is preserved.
This is a private, **sandbox-only** implementation. No live charges are supported.

## What is built

- Supabase email/password signup and sign-in with confirmation handled by the provider; server-only HttpOnly, Secure, SameSite cookies, refresh and logout.
- Explicit invite-email allowlist, origin checks, user-scoped inventory with revision conflicts, saved check history and per-check deletion.
- A sample one-time **$5 for 10 checks** offer. This is a sandbox fixture, not an approved public price. No renewal, no credit expiry in this pilot.
- Stripe-hosted Checkout, server-side offer amounts and idempotent session creation. No card input exists in this app.
- Raw-body HMAC signature validation with a 5-minute timestamp tolerance; canonical Stripe session retrieval, sandbox/paid/amount/currency/owner checks; atomic, session-idempotent credit fulfillment.
- Atomic credit reservations, input-bound retry identifiers, completed-response replay, one-time release on failure, and reclaim of abandoned reservations older than 15 minutes (on account refresh). Vercel check duration is capped at 300 seconds.
- Automatic account history save after a completed check. WAIT/held-back outcomes consume a check because analysis ran. Failed model calls release the reservation when the database can be reached; stale-reservation recovery handles worker termination.
- Repeated checks of the same screenshot and question within 24 hours require explicit confirmation before spending another credit. Refresh reports the synced balance; upload validation accepts PNG/JPG/WebP/GIF up to 3 MB and clears stale results.
- The screenshot pipeline and recommendation library are reused. Raw screenshots are not written to account storage. The browser never receives service-role, model, Stripe-secret or shared service-token credentials.

## Provider setup verified (2026-11-25)

The `work/first-user-pilot` preview now reports `accountsConfigured: true` and `checkoutConfigured: true`, with no missing environment variables. The preview uses the dedicated `AisCart` Supabase project; the five pilot account, inventory, check, usage, and order tables are present with RLS enabled. Its public webhook route responds directly instead of being redirected to a sign-in page. Branch-scoped Vercel configuration includes the Supabase URL and keys, invited-email allowlist, exact pilot origin, reasoning settings, and Stripe sandbox credentials. Secret values are not recorded here.

The configuration check confirms setup and route reachability. The first signed-in pilot session and a sandbox order are now verified below. Do not present the sample $5 offer as approved pricing.

1. Keep all provider settings **on the pilot branch only**:

| Variable | Meaning |
| --- | --- |
| `SUPABASE_URL` | Pilot project's HTTPS API URL |
| `SUPABASE_ANON_KEY` | Pilot project anon JWT API key |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only pilot service-role JWT key |
| `PILOT_ORIGIN` | Exact stable pilot branch URL, without a trailing path |
| `PILOT_ALLOWED_EMAILS` | Comma-separated invited email addresses; start with the founder only |
| `STRIPE_SECRET_KEY` | Sandbox `sk_test_…` key; live keys are refused |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for this sandbox webhook endpoint |
| `EXTRACT_REASONING` / `VERDICT_REASONING` | `low` to retain the tested speed setting; review inherits `medium` |

2. Confirm Supabase's email-confirmation redirect points to the pilot origin.
3. Confirm the Stripe sandbox endpoint at `PILOT_ORIGIN/api/pilot?action=webhook` subscribes to `checkout.session.completed` and `checkout.session.async_payment_succeeded`.
4. Sign in to the same account in a separate browser session and on the physical phone. Confirm the inventory, 6-credit balance, and saved history follow the account.
5. Verify two distinct real user accounts cannot read each other's data. Verify duplicate webhook delivery adds credits once and cancellation/unpaid sessions add none.

Do not paste secrets into chat, code, screenshots, or commits. Configure them in provider/Vercel settings or use the connected services.

## First signed-in pilot run (2026-11-25)

- The user-provided screenshot shows an authenticated account, saved tool inventory, and a balance of 6 sandbox checks.
- A fresh cloud-browser session signed in to the same invited account and displayed the same saved tool inventory, 6-check balance, and all six saved checks. This confirms account data follows the user across separate browser sessions; it is not a physical-phone check.
- User-provided Android phone screenshots show the signed-in account, 6 sandbox checks, saved tool inventory, and all six saved checks in the mobile layout. This confirms cross-device persistence for the account data and history.
- A read-only Supabase RLS simulation with the authenticated database role confirmed that the real account sees its own inventory and six checks, while a different synthetic user ID sees zero of either. The `pilot_orders` and `pilot_usage` tables remain unreadable to the authenticated role. This tests row-level policies and grants, not a second real Auth account.
- Read-only Supabase aggregates show one fulfilled sandbox order for $5 / 10 credits, six completed check usages, and six saved check records. The database timestamps place two completed checks before the order and four after it.
- The remaining balance of 6 reconciles with two opening pilot credits before the order plus four credits used from the 10-credit pack. The schema has no credit ledger, so the source of those two opening credits cannot be reconstructed; do not attribute them to the Stripe payment.
- This verifies a separate-session sign-in and data sync, phone sign-in with the expected balance, inventory, and six saved checks, the row-policy boundary under two user identities, a paid sandbox order with fulfillment, and saved check history in the fresh browser session. Isolation between two real Auth accounts and real duplicate/unpaid webhook behavior remain unverified. No live charge occurred.

## Tests completed in the workspace

```sh
python3 tests/test_pilot.py
npm ci --ignore-scripts
npm run test:pilot:sql
python3 tests/test_service.py
python3 tests/test_journeys.py
node tests/test_page_journeys.js
```

- `test_pilot.py`: provider doubles exercise signup/signin/cookies, origins, allowlist, inventory versions, sandbox checkout, forged/expired/live/duplicate payment events, amounts, credits, failed checks, input-bound retries and cross-user history.
- `test_pilot_sql.js`: executes the actual migration and functions in PGlite Postgres, including RLS grants/denials, credit invariants, lost-update prevention, payment replay and abandoned-reservation recovery.
- Existing pipeline and recommendation regressions must remain green.

Latest local run (2026-11-25): `python3 tests/test_pilot.py` passed all 30 provider-double checks; `npm run test:pilot:sql` passed all 19 Postgres migration/RLS/ledger checks. Duplicate and unpaid webhook cases pass locally; a real Stripe webhook replay was not performed.

Provider-double and local-Postgres tests are **not** proof of real provider behavior; the first account and sandbox order are separately verified above.
The real second-account isolation check and duplicate/unpaid webhook checks remain pending. The phone screenshot predates the local sign-in-message copy fix; the preview is private-pilot infrastructure only.

## Before any paid public release

Decide and approve actual pricing, credit policy, refunds, privacy/terms and support contact. Complete account recovery/deletion flows,
production rate limiting, payment failure/refund/dispute handling, monitoring, and real-provider end-to-end tests. This code deliberately rejects live Stripe keys.
Authentication provider throttling exists, but requests currently originate from the app server; review per-user/IP throttling before broader access.
No public paid launch, financial account opening, live charge, or legal agreement was performed in this task.
