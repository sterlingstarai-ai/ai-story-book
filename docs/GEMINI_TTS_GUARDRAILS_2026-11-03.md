# Gemini narration IAM and cost guardrails

The approved Korean narration uses `gemini-2.5-flash-tts`, three style prompts,
and Kore/Puck voices. These changes are prepared locally: they grant no IAM
permission, do not change the running VM or its backup identity, and make no
paid speech requests. Initial deployment, migration and focused tests remain
pending.

Production narration remains disabled until all three are in place: explicitly
chosen daily and monthly request limits appropriate to the whole product
budget; a reviewed dedicated identity and the smallest applicable permissions;
and real billing/usage monitoring with verified notification delivery. The
budget table migration, concurrency/failure behavior, both approved voices and
all three styles also require the final isolated and real-provider checks.
Limits, identity, monitoring, or a passing local test alone do not authorize
the feature.

Google documents that Gemini-TTS on the Cloud Text-to-Speech endpoint requires
`aiplatform.endpoints.predict`. The candidate role template contains only that
permission, but a project-level grant can permit prediction on more than the
approved model. The [official model documentation](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)
does not establish that this permission is restricted to this model. A separate
narration runtime and dedicated service identity would isolate it more cleanly.
The current VM has one attached backup identity: changing that identity would
also affect backup, and allowing it to impersonate a TTS account would expose
that capability to other processes that can reach its metadata credentials.
Do not add the prediction permission to the backup account or assume a new
service account becomes available to containers by itself. Select and review a
separate runtime/credential boundary before any IAM grant. No service-account
key is issued by this plan.

`google_gemini_tts_daily_request_limit` and
`google_gemini_tts_monthly_request_limit` default to zero, blocking Gemini
provider calls until both are explicitly positive. The migration
`d52b81c9a734` creates persistent PostgreSQL counters. Immediately before each
Gemini request, a single transaction reserves one daily and monthly slot.
Concurrent API and worker processes sharing the database serialize on the same
rows; a failed monthly reservation rolls back the daily reservation. Provider
errors and ambiguous timeouts consume slots and retries consume new slots.
Missing configuration, table, or database availability stops the request.
Periods use the existing Korea-local date convention. Other TTS providers are
unchanged. These counters do not depend on Redis, but a restored or rolled-back
database can restore old counts; a separately issued credential or external
client can also bypass them. Restore, cloning, account access and uniform
configuration across all producers need explicit operational controls.

These are **request limits, not a won-denominated spending cap**. Output length,
input tokens, model pricing, foreign-exchange rates, provider retries outside
this adapter, tax, other AI calls, VM and storage costs all affect the bill.
The [Google price table](https://cloud.google.com/text-to-speech/pricing) lists
no free Gemini 2.5 Flash TTS allowance and charges for input and output tokens.
For planning only, an initial private pilot might set daily `3` and monthly
`20` requests after migration and validation. A maximum documented output of
about 655 seconds at 25 audio tokens/second and $10 per million output tokens is
about $0.164 output per request, or $3.28 for 20 such outputs, before input,
tax, exchange rate and all other services. This example is not a billing cap,
provider guarantee, or estimate of the complete KRW 10,000 monthly bill.

The Cloud Billing Budget API was disabled during a read-only API inspection.
The already signed-in Chrome billing console showed an existing monthly
`AI Story Book monthly test alert` budget of KRW 10,000 scoped to the AI Story
Book Beta project, with 50%, 80%, and 100% alert thresholds and spend-cap status
"not applicable". It is an alert budget, not an automatic spending cutoff;
the precise notification recipients and actual delivery are unverified. No
budget was changed. Google's [billing documentation](https://docs.cloud.google.com/billing/docs/how-to/budgets)
states that alert-only budgets notify but do not automatically stop usage.
A separate [spend-cap budget](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
can pause eligible services, but the documented list does not list Cloud
Text-to-Speech; Vertex AI eligibility alone does not prove coverage of this
Cloud Text-to-Speech endpoint. Enforcement is not instant and overage is billed.
A safe cost plan needs actual account-level budget verification, meaningful
provider-side quotas where supported, the request guard, and monitoring of the
other services; no protection here guarantees a total bill of KRW 10,000.
