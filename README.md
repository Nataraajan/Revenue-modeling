# Revenue Architecture Model

A deterministic, multi-phase B2B SaaS revenue model — pipeline/capacity, revenue recognition, renewals, an existing-book overlay, a SaaS metrics dashboard, a formula-driven Excel export, and a natural-language assistant — built as a portfolio project grounded in a real operational problem, not a generic exercise.

**Live app:** [revenue-modeling-nat.streamlit.app](https://revenue-modeling-nat.streamlit.app/)

---

## Why this exists

Most "revenue models" in FP&A portfolios stop at a bookings forecast. This one is built around a specific, lived failure: a prior attempt to build a multi-year P&L/cashflow plan in Excel/Google Sheets broke down because it conflated three genuinely different timelines — **when a deal is signed (bookings)**, **when cash is collected (billings)**, and **when revenue can actually be recognized (ASC 606)**. That gap — an account signed but not yet live, sitting invisible between bookings and revenue — is the specific thing this model is built to make visible and correct.

## Framework grounding

Built on the **Bowtie Model** (Winning by Design / Jacco van der Kooij's Revenue Architecture), which extends the traditional sales funnel across the full customer lifecycle rather than stopping at close:

- **Left side (pre-revenue):** Awareness → Education → Selection → Mutual Commit — demand generation, pipeline, AE/BDR capacity
- **Middle (the MEDFAR pain point):** Commit → Onboard — implementation lag, revenue recognition
- **Right side (post-revenue):** Onboard → Adopt → Impact → Expand/Renew — churn, expansion, NRR

Each side was built as an independent, standalone-demoable phase, then bridged together. Later additions (existing-book overlay, multi-pod Excel export, the AI assistant) extend this core rather than replace it.

## Architecture

| File | What it does |
|---|---|
| `capacity_engine.py` | **Phase 1.** Dual-constraint pipeline/capacity engine. Segments into "pods" (SMB/Mid-Market/Enterprise/Inbound presets, or custom), each with independently configurable existing/new AE and BDR headcount, comp, quota, demand assumptions, and seasonality. |
| `revenue_recognition_engine.py` | **Phase 2.** ASC 606 revenue recognition. Converts bookings into contracts, tracks implementation lag → go-live → ratable recognition, deferred revenue balance, and professional services fees (point-in-time, distinct performance obligation). |
| `renewal_engine.py` | **Phase 3.** Renewal/churn/expansion at contract term-end. Generates real follow-on contracts so ARR is genuinely continuous across renewal cycles (not just a diagnostic side-calculation). Produces the standard SaaS ARR waterfall and NRR. |
| `existing_book_engine.py` | Top-line ARR/revenue overlay for a company's **pre-existing customer base**, derived from an uploaded customer-revenue extract (CSV/Excel). Computes real trailing-twelve-month NRR/churn/expansion directly from matched customer data (not a guessed assumption), plus a full historical annual actuals series, and projects the existing book forward with smooth monthly runoff. Deliberately *not* run through the Contract engine — no individual contract dates exist in a revenue extract, so it's a pure top-line overlay, added to (not blended into) new-business output. |
| `saas_metrics.py` | Aggregates monthly output from Phases 1–3 (+ existing book, if included) into annual and quarterly periods: ARR, revenue, NRR, gross $ churn, logo churn, LTV. Powers the Executive Dashboard's hero metrics and ARR bridge waterfall. |
| `financial_model_export.py` | Generates a **multi-segment, fully formula-driven Excel workbook** (openpyxl) — real cell formulas throughout, not pasted values, following standard financial-model color conventions (blue = input, black = formula, green = cross-sheet link). One Capacity + Revenue Recognition sheet pair per segment, plus a consolidated Summary sheet with per-segment columns *and* a "Total Company" column that sums across them. Cohort-based revenue recognition with dynamically-bounded renewal generations (however many fit the horizon/term combination). Independently cross-validated against the Python engine's own output — not just checked for formula errors. |
| `scenario_cli.py` | Command-line wrapper around the engine, designed to be called by an external agent (e.g. OpenClaw) with structured JSON, not natural language. Maintains its own copy of preset defaults (documented as manually-synced with `app.py`, since this script runs standalone, independent of the in-app AI assistant below). |
| `app.py` | The Streamlit application — dashboard, scenario comparison, Excel export, and the in-app AI assistant. See **App Features** below. |

## Bridge pattern

Phase 2's `bookings_to_contracts()` and Phase 3's `run_full_lifecycle()` always pull assumptions (avg deal size, term, implementation lag, etc.) directly from the same `PodConfig` object Phase 1 used — never re-specified as separate parameters. This was a deliberate fix partway through development after finding a duplicate-assumption risk (two phases could silently disagree about the same pod's deal size).

## App Features (`app.py`)

- **Two modes:** "All Segments" — a combined, whole-company Executive Dashboard across every included segment — and "Compare Two Scenarios" — full side-by-side scenario configuration with a KPI comparison table and ARR/Revenue waterfall bridges.
- **Executive Dashboard** — hero KPI tiles (Ending ARR, Recognized Revenue, Blended NRR, Live Accounts, Deferred Revenue, Total Cost of Capacity) with sparklines, an Annual Performance table, a Market Growth Contribution chart (net new ARR by segment, per year), and an ARR Bridge waterfall. For horizons of 3 years or fewer, the bridge renders as one continuous multi-year chain (Beginning → each year's New/Expansion/Contraction/Churn → Ending); beyond that it falls back to the latest year alone with an explicit "Other/Boundary" residual, since a multi-year bridge stops being readable past that length.
- **Segment presets** (SMB/Mid-Market/Enterprise/Inbound/Custom) load a full, differentiated starting set of assumptions (team size, deal economics, win rates, renewal rates) — not just a label. Every field remains editable after selection.
- **Company-wide marketing pool.** Marketing-sourced demand is a single shared "total SQLs/month" figure, split across segments by an explicit, user-set allocation percentage (must sum to 100%) — not derived independently per segment. This replaced an earlier design where each segment had its own flat marketing figure, after testing showed the combined "All Segments" view could produce unrealistic total demand when four independently-tuned assumptions were simply summed.
- **Advanced section** (collapsed by default): AE/BDR comp breakdown, hiring cadence, custom hire-month schedules, seasonality pattern, professional services fee. AE/BDR base+variable comp default to a 5.5x quota:OTE split (mid of the healthy 4–6x benchmark band) derived from quota, so the model runs correctly even if this section is never opened.
- **Existing Customer Book upload** (CSV/Excel) — derives real trailing-twelve-month NRR/churn/expansion from actual customer-matched revenue data, shows it before any override, and projects it forward as a top-line overlay alongside new business. The Dashboard then shows a continuous **actual → forecast** timeline, not an isolated forward-only projection.
- **Excel export** — generates the multi-segment workbook described above, live from whatever's currently configured (not a fixed example), with a segment picker so a single click can produce a full-company file, not just one team's numbers.
- **AI Assistant** — a floating action button opens a chat panel (Claude Haiku, chosen deliberately as a cheap/fast model since this is structured extraction, not complex reasoning) that can:
  - **Answer factual questions** ("what's the ending ARR this year") by retrieving the real value from a comprehensive registry built from the model's own already-computed output — the LLM is instructed to quote the value exactly and never perform its own arithmetic. If a field genuinely isn't in the registry, it says so rather than guessing.
  - **Run what-if simulations** ("what would happen if we hired 2 more Enterprise AEs") by returning a structured JSON override, which the app runs through the real deterministic engine — shown as a preview with current/simulated/change columns before anything is actually applied to the live scenario.
  - **Answer segment-comparison questions** ("which market contributes most to churn") with all three legitimate lenses labeled separately (highest own rate, biggest weighted contributor to the blended rate, biggest dollar impact) rather than picking one and calling it "the" answer, since these genuinely answer different questions.
  - The system prompt explicitly forbids referencing internal variable or session-state names in any response, and caps the LLM's role at translation and retrieval — it never computes a financial output itself, matching the same principle `scenario_cli.py` was built around.

## Key design decisions (read before flagging as a bug)

- **No randomization, anywhere.** Every input is an explicit, named, user-set variable — not a probability distribution or Monte Carlo draw. This was a direct instruction from the model's owner: the goal is a model where every number is defensible and explainable in an interview, not one that requires explaining away stochastic behavior. This also shaped the AI assistant's design — it interprets language into structured inputs, but the deterministic engine remains the only thing that ever computes a result.
- **Churn/expansion/contraction rates are applied directly as annual rates, with no term-based compounding.** Contracts are modeled as annual (12-month) by default, matching standard B2B SaaS practice, and since cohorts renew every month on a rolling basis, the annual rate already *is* the per-renewal-event rate.
- **Capacity is a hard ceiling, always** — even when `execution_efficiency` is set above 1.0, and even when a seasonal multiplier would otherwise push a month's bookings higher. A rep cannot close more than their quota-adjusted capacity allows, no matter how the other levers are set.
- **Commission accelerators are intentionally not modeled.** The pooled team-level attainment calculation (`actual_bookings = min(capacity, demand)`) mathematically cannot exceed 100% team attainment, so accelerators (which only trigger on individual reps exceeding their own quota) would be structurally dead code without per-rep stochastic variance — which conflicts with the no-randomization constraint above.
- **Lead→MQL→SQL funnel mechanics are not modeled.** Marketing-sourced demand is a flat SQL figure (now pooled company-wide and allocated by segment — see App Features), not simulated through conversion-rate stages. Channel mix — inbound content, outbound, partnerships — is too company/product-specific to generalize honestly, and modeling a fake funnel would imply false precision. This mirrors the treatment BDR output already had (a flat quota, not a simulated call→connect→meeting funnel).
- **New-business bookings and renewal ARR are explicitly separated** (`Contract.origin` field: `"new"` vs `"renewal"`), so renewal-generated contracts never inflate apparent new-business growth in acquisition-lens metrics.
- **Professional services/implementation fees** default to point-in-time recognition at go-live (the "distinct performance obligation" treatment under ASC 606). The alternative treatment — bundled with subscription, recognized ratably — is also implemented and switchable via `Contract.ps_fee_treatment`, since which treatment applies is a real judgment call, not a settled fact.
- **Seasonality is a fully explicit, user-set 12-month multiplier pattern** (`PodConfig.seasonality_pattern`), not inferred or randomized — cycles automatically for multi-year scenarios.
- **"New ARR" is measured by go-live date, not signed date.** A contract signed in month 11 with a 2-month implementation lag doesn't join `live_arr` until month 13. Using signed-month bookings as "new ARR" would create a phantom reconciliation gap against `live_arr`. This distinction is enforced both in the core aggregation logic and in the AI assistant's registry field labels.
- **The financial model Excel export dynamically computes how many renewal "generations" to build** based on horizon and contract term together (e.g., a 6-month term over an 18-month horizon needs up to 3 generations; a 12-month term over 24 months needs 2) — not a fixed count, so it stays correct as those inputs change.
- **The multi-segment Excel export rolls up via a "Total Company" column that sums each metric across segment columns**, the standard way a real multi-segment financial model consolidates (segment columns + total column), rather than re-deriving company totals independently (which would risk drifting from the segment-level detail).
- **Currency values auto-scale to $K/$M in dashboard summary views** (hero cards, Annual Performance, chart tooltips), but the "View underlying data" / raw audit tables always keep full, unscaled precision — summary views prioritize readability, audit views prioritize exactness, and neither should compromise the other.

## Known simplifications and limitations (flagged, not hidden)

- All reps within one pod share an identical comp/quota template — no rep-to-rep variance within a segment.
- Synthetic contracts are generated by dividing a pod's monthly bookings $ by its average deal size — real deal sizes vary around that average; this is an approximation, not individual deal-level data.
- BDR "quota" is denominated in SQL units, not dollars — deliberately kept separate from the AE quota:OTE ratio math, since dividing SQLs by OTE dollars is meaningless.
- Logo churn rate defaults to the revenue churn rate if not separately specified — in reality, churned logos usually skew smaller than average, so logo churn is often higher than revenue churn. Overridable via `RenewalAssumptions.logo_churn_rate_annual`.
- The last few months of any scenario window will show elevated "implementation backlog," since late-signed contracts don't have enough runway left in the window to reach go-live. A real boundary effect of finite simulation windows, not a bug.
- **A small, understood residual ("Other/Boundary Effect") appears in annual rollups and the Excel export's Summary sheet**, typically driven by a renewal event firing in a period's last month whose renewed contract's go-live falls just outside the observation window. The math is correct; the window just ends slightly before the full consequence is visible. Both the Python dashboard and the Excel export surface this explicitly rather than forcing a fake exact reconciliation.
- **The Excel export does not include:** professional services fees, seasonality patterns, or the Existing Book overlay. New-business only, and the annual Summary sheet covers full years only (a trailing partial year's months still appear in the monthly grids but aren't rolled into annual totals).
- **The AI assistant's what-if simulations are previews, not commitments** — a simulated change is never silently applied to the live scenario. Applying it requires the same manual input change the preview describes.
- **`scenario_cli.py` maintains its own copy of preset defaults**, separate from `app.py`'s `_PRESET_DEFAULTS` — documented as manually-synced rather than imported, since the CLI is designed to run standalone without a Streamlit dependency. If presets change in one file, the other needs a manual update.
- **The AI assistant requires an `ANTHROPIC_API_KEY`** set via Streamlit Cloud's Secrets manager (or a local environment variable when running locally) — it fails without one, since there's no local fallback for the chat feature.

## Testing

29 automated edge-case tests across the three original engine files, all passing as of the last run:

- `edge_case_tests.py` (8 tests) — Phase 1: zero AEs/BDRs/leads, mid-scenario hiring, execution efficiency bounds, pod hire_months validation, empty pods in multi-pod scenarios.
- `edge_case_tests_revrec.py` (12 tests) — Phase 2: zero implementation lag, contract term exceeding observation window, late-signed contracts, all three billing frequencies, deferred revenue non-negativity, bridge consistency.
- `edge_case_tests_renewal.py` (9 tests) — Phase 3: 100% churn, 0% churn/expansion/contraction, unconfigured pods, cascading renewals, origin-tagging correctness, extreme rate combinations.

Run any test file directly: `python3 edge_case_tests.py`

**Not covered by automated tests** (flagged, not hidden): `existing_book_engine.py`, `saas_metrics.py`, `financial_model_export.py`, `scenario_cli.py`, the AI assistant, and `app.py` itself have no formal test suite. These were validated manually during development — cross-checking Excel export output against independent Python computation, verifying derived NRR against known synthetic data, tracing the AI assistant's registry and system-prompt rules against the actual code rather than trusting a summary, boot-testing the Streamlit app after every change — but that validation isn't captured as a re-runnable automated suite the way the three core engine files are.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Set `ANTHROPIC_API_KEY` as an environment variable (or in Streamlit's secrets file) for the AI assistant to work — every other feature runs without it.

Recommended: use a virtual environment (`python -m venv venv`, then activate it) to avoid dependency conflicts with global Python packages.

## Agent integration (OpenClaw / scenario_cli.py)

Separate from the in-app AI assistant above, `scenario_cli.py` lets an *external* agent (e.g. OpenClaw running on its own schedule or messaging channel) run scenarios via structured JSON:

```bash
python3 scenario_cli.py '{"num_aes": 5}' --base-preset Mid-Market
```

Same underlying principle as the in-app assistant: **natural language → an LLM interprets into structured JSON → the deterministic engine runs → results returned → the agent explains them back in plain language.** The LLM never computes a financial output itself in either path.

## Author's note

This was built iteratively through an extended working session, with each phase stress-tested and numerous real bugs found and fixed along the way — not a single clean pass. Documented examples across the codebase and this README include: a revenue-recognition reconciliation bug where renewal math was computed correctly but never fed back into the live ARR trajectory; a new-business/renewal conflation bug where renewal-generated contracts silently inflated "new ARR booked"; a column-collision bug in the Excel generator that silently zeroed out every recognized-revenue formula; a renewal-event bucketing convention mismatch between the Python engine and the Excel export that dropped the final in-window renewal event; a preset-switching bug in the Streamlit UI where changing the segment dropdown only changed a text label, not any of the underlying assumptions; and — in the AI assistant specifically — an early version that occasionally attempted its own arithmetic instead of retrieving real computed values, fixed by building the comprehensive registry and system-prompt rules described above. Each is documented rather than quietly patched, since the debugging process itself — and the discipline of catching these before they reached a "working" state — is part of what this project is meant to demonstrate.
