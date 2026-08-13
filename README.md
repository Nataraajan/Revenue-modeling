# Revenue Architecture Model

A deterministic, multi-phase B2B SaaS revenue model — pipeline/capacity, revenue recognition, renewals, existing-book overlay, SaaS metrics rollup, and a formula-driven Excel export — built as a portfolio project grounded in a real operational problem, not a generic exercise.

**Live app:** [Streamlit deployment link]

---

## Why this exists

Most "revenue models" in FP&A portfolios stop at a bookings forecast. This one is built around a specific, lived failure: a prior attempt to build a multi-year P&L/cashflow plan in Excel/Google Sheets broke down because it conflated three genuinely different timelines — **when a deal is signed (bookings)**, **when cash is collected (billings)**, and **when revenue can actually be recognized (ASC 606)**. That gap — an account signed but not yet live, sitting invisible between bookings and revenue — is the specific thing this model is built to make visible and correct.

## Framework grounding

Built on the **Bowtie Model** (Winning by Design / Jacco van der Kooij's Revenue Architecture), which extends the traditional sales funnel across the full customer lifecycle rather than stopping at close:

- **Left side (pre-revenue):** Awareness → Education → Selection → Mutual Commit — demand generation, pipeline, AE/BDR capacity
- **Middle (the MEDFAR pain point):** Commit → Onboard — implementation lag, revenue recognition
- **Right side (post-revenue):** Onboard → Adopt → Impact → Expand/Renew — churn, expansion, NRR

Each side was built as an independent, standalone-demoable phase, then bridged together. Later additions (existing-book overlay, multi-pod Excel export, agent integration) extend this core rather than replace it.

## Architecture

| File | What it does |
|---|---|
| `capacity_engine.py` | **Phase 1.** Dual-constraint pipeline/capacity engine. Segments into "pods" (SMB/Mid-Market/Enterprise/Inbound presets, or custom), each with independently configurable existing/new AE and BDR headcount, comp, quota, demand assumptions, and seasonality. |
| `revenue_recognition_engine.py` | **Phase 2.** ASC 606 revenue recognition. Converts bookings into contracts, tracks implementation lag → go-live → ratable recognition, deferred revenue balance, and professional services fees (point-in-time, distinct performance obligation). |
| `renewal_engine.py` | **Phase 3.** Renewal/churn/expansion at contract term-end. Generates real follow-on contracts so ARR is genuinely continuous across renewal cycles (not just a diagnostic side-calculation). Produces the standard SaaS ARR waterfall and NRR. |
| `existing_book_engine.py` | Top-line ARR/revenue overlay for a company's **pre-existing customer base**, derived from an uploaded customer-revenue extract (CSV/Excel). Computes real trailing-twelve-month NRR/churn/expansion directly from matched customer data (not a guessed assumption), plus a full historical annual actuals series, and projects the existing book forward with smooth monthly runoff. Deliberately *not* run through the Contract engine — no individual contract dates exist in a revenue extract, so it's a pure top-line overlay, added to (not blended into) new-business output. |
| `saas_metrics.py` | Aggregates monthly output from Phases 1–3 (+ existing book, if included) into annual and quarterly periods: ARR, revenue, NRR, gross $ churn, logo churn, LTV. Powers the Executive Dashboard's hero metrics and ARR bridge waterfall. |
| `financial_model_export.py` | Generates a **multi-segment, fully formula-driven Excel workbook** (openpyxl) — real cell formulas throughout, not pasted values, following standard financial-model color conventions (blue = input, black = formula, green = cross-sheet link). One Capacity + Revenue Recognition sheet pair per segment, plus a consolidated Summary sheet with per-segment columns *and* a "Total Company" column that sums across them. Cohort-based revenue recognition with dynamically-bounded renewal generations (however many fit the horizon/term combination). Independently cross-validated against the Python engine's own output — not just checked for formula errors. |
| `scenario_cli.py` | Command-line wrapper around the engine, designed to be called by an external agent (e.g. OpenClaw) with structured JSON, not natural language. The agent's LLM may translate a plain-English request into JSON matching this script's schema — it never computes ARR/NRR/revenue itself. Maintains its own copy of preset defaults (documented as manually-synced with `app.py`, since this script runs standalone). |
| `app.py` | The Streamlit application — see **App Features** below. |

## Bridge pattern

Phase 2's `bookings_to_contracts()` and Phase 3's `run_full_lifecycle()` always pull assumptions (avg deal size, term, implementation lag, etc.) directly from the same `PodConfig` object Phase 1 used — never re-specified as separate parameters. This was a deliberate fix partway through development after finding a duplicate-assumption risk (two phases could silently disagree about the same pod's deal size).

## App Features (`app.py`)

- **Executive Dashboard** (formerly "SaaS Metrics Dashboard") — hero KPI tiles (Ending ARR, Recognized Revenue, NRR, Live Accounts, Deferred Revenue), an actual/forecast ARR bar chart when an existing book is uploaded, and an ARR bridge waterfall for the latest period.
- **Horizontal assumptions layout, not a sidebar.** All scenario inputs live in the main content area in a compact grid (Team & Quota, Deal Economics & Win Rates, Contract & Renewal), matching how a real financial model keeps assumptions in one visible band rather than buried in a long vertical pane. Every input has a hover tooltip explaining what it controls.
- **Segment presets** (SMB/Mid-Market/Enterprise/Inbound/Custom) load a full, differentiated starting set of assumptions (team size, deal economics, win rates, renewal rates) — not just a label. Every field remains editable after selection.
- **Advanced section** (collapsed by default): AE/BDR comp breakdown, hiring cadence, custom hire-month schedules, seasonality pattern, professional services fee. AE/BDR base+variable comp default to a 5.5x quota:OTE split (mid of the healthy 4–6x benchmark band) derived from quota, so the model runs correctly even if this section is never opened.
- **Marketing demand is a single flat "SQLs/month" input, not a lead→MQL→SQL funnel.** Channel mix (inbound content, outbound, partnerships) is too company/product-specific to generalize honestly — modeling a fake conversion funnel would imply false precision. This gets the same treatment BDR output already had (a flat SQL quota, not a simulated call→connect→meeting funnel), kept deliberately consistent.
- **Existing Customer Book upload** (CSV/Excel) — derives real trailing-twelve-month NRR/churn/expansion from actual customer-matched revenue data, shows it before any override, and projects it forward as a top-line overlay alongside new business. The Dashboard then shows a continuous **actual → forecast** timeline, not an isolated forward-only projection.
- **Compare Two Scenarios mode** — full side-by-side scenario configuration, KPI comparison with deltas, and two waterfall bridges (ARR and Revenue) explaining the gap between scenarios. The ARR bridge is an additive approximation with an explicit "Other/interaction" residual (cascading renewal timing creates real interaction effects between drivers); the Revenue bridge is an *exact* partition by origin (new-business vs. renewal-driven subscription, plus PS fees) — verified to sum exactly with no residual.
- **Excel export** — generates the multi-segment workbook described above, live from whatever's currently configured (not a fixed example), with a segment picker (defaults to the current scenario + all other standard presets, for a full company view out of the box).

## Key design decisions (read before flagging as a bug)

- **No randomization, anywhere.** Every input is an explicit, named, user-set variable — not a probability distribution or Monte Carlo draw. This was a direct instruction from the model's owner: the goal is a model where every number is defensible and explainable in an interview, not one that requires explaining away stochastic behavior.
- **Churn/expansion/contraction rates are applied directly as annual rates, with no term-based compounding.** Contracts are modeled as annual (12-month) by default, matching standard B2B SaaS practice, and since cohorts renew every month on a rolling basis, the annual rate already *is* the per-renewal-event rate.
- **Capacity is a hard ceiling, always** — even when `execution_efficiency` is set above 1.0. A rep cannot close more than their quota-adjusted capacity allows, no matter how well "execution" is modeled.
- **Commission accelerators are intentionally not modeled.** The pooled team-level attainment calculation (`actual_bookings = min(capacity, demand)`) mathematically cannot exceed 100% team attainment, so accelerators (which only trigger on individual reps exceeding their own quota) would be structurally dead code without per-rep stochastic variance — which conflicts with the no-randomization constraint above.
- **New-business bookings and renewal ARR are explicitly separated** (`Contract.origin` field: `"new"` vs `"renewal"`), so renewal-generated contracts never inflate apparent new-business growth in acquisition-lens metrics.
- **Professional services/implementation fees** default to point-in-time recognition at go-live (the "distinct performance obligation" treatment under ASC 606). The alternative treatment — bundled with subscription, recognized ratably — is also implemented and switchable via `Contract.ps_fee_treatment`, since which treatment applies is a real judgment call, not a settled fact.
- **Seasonality is a fully explicit, user-set 12-month multiplier pattern** (`PodConfig.seasonality_pattern`), not inferred or randomized — cycles automatically for multi-year scenarios.
- **"New ARR" is measured by go-live date, not signed date.** A contract signed in month 11 with a 2-month implementation lag doesn't join `live_arr` until month 13. Using signed-month bookings as "new ARR" would create a phantom reconciliation gap against `live_arr`. This distinction matters enough that it's worth double-checking any UI label using the word "New" actually preserves it.
- **The financial model Excel export dynamically computes how many renewal "generations" to build** based on horizon and contract term together (e.g., a 6-month term over an 18-month horizon needs up to 3 generations; a 12-month term over 24 months needs 2) — not a fixed count, so it stays correct as those inputs change.
- **The multi-segment Excel export rolls up via a "Total Company" column that sums each metric across segment columns**, the standard way a real multi-segment financial model consolidates (segment columns + total column), rather than re-deriving company totals independently (which would risk drifting from the segment-level detail).

## Known simplifications and limitations (flagged, not hidden)

- All reps within one pod share an identical comp/quota template — no rep-to-rep variance within a segment.
- Synthetic contracts are generated by dividing a pod's monthly bookings $ by its average deal size — real deal sizes vary around that average; this is an approximation, not individual deal-level data.
- BDR "quota" is denominated in SQL units, not dollars — deliberately kept separate from the AE quota:OTE ratio math, since dividing SQLs by OTE dollars is meaningless.
- Logo churn rate defaults to the revenue churn rate if not separately specified — in reality, churned logos usually skew smaller than average, so logo churn is often higher than revenue churn. Overridable via `RenewalAssumptions.logo_churn_rate_annual`.
- The last few months of any scenario window will show elevated "implementation backlog," since late-signed contracts don't have enough runway left in the window to reach go-live. A real boundary effect of finite simulation windows, not a bug.
- **A small, understood residual ("Other/Boundary Effect") appears in annual rollups and the Excel export's Summary sheet**, typically driven by a renewal event firing in a period's last month whose renewed contract's go-live falls just outside the observation window. The math is correct; the window just ends slightly before the full consequence is visible. Both the Python dashboard and the Excel export surface this explicitly rather than forcing a fake exact reconciliation.
- **The Excel export does not include:** professional services fees, seasonality patterns, or the Existing Book overlay. New-business only, and the annual Summary sheet covers full years only (a trailing partial year's months still appear in the monthly grids but aren't rolled into annual totals).
- **The interactive Streamlit dashboard configures one pod at a time** (or two, in Compare mode) — there's no interactive multi-pod "whole company" view in the app itself. Multi-pod consolidation currently exists only in the Excel export, which was built specifically because a shared Excel file is expected to represent the whole business, not one team.
- **`scenario_cli.py` maintains its own copy of preset defaults**, separate from `app.py`'s `_PRESET_DEFAULTS` — documented as manually-synced rather than imported, since the CLI is designed to run standalone without a Streamlit dependency. If presets change in one file, the other needs a manual update.

## Testing

29 automated edge-case tests across the three original engine files, all passing as of the last run:

- `edge_case_tests.py` (8 tests) — Phase 1: zero AEs/BDRs/leads, mid-scenario hiring, execution efficiency bounds, pod hire_months validation, empty pods in multi-pod scenarios.
- `edge_case_tests_revrec.py` (12 tests) — Phase 2: zero implementation lag, contract term exceeding observation window, late-signed contracts, all three billing frequencies, deferred revenue non-negativity, bridge consistency.
- `edge_case_tests_renewal.py` (9 tests) — Phase 3: 100% churn, 0% churn/expansion/contraction, unconfigured pods, cascading renewals, origin-tagging correctness, extreme rate combinations.

Run any test file directly: `python3 edge_case_tests.py`

**Not covered by automated tests** (flagged, not hidden): `existing_book_engine.py`, `saas_metrics.py`, `financial_model_export.py`, `scenario_cli.py`, and `app.py` itself have no formal test suite. These were validated manually during development — cross-checking Excel export output against independent Python computation, verifying derived NRR against known synthetic data, boot-testing the Streamlit app after every change — but that validation isn't captured as a re-runnable automated suite the way the three core engine files are.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Recommended: use a virtual environment (`python -m venv venv`, then activate it) to avoid dependency conflicts with global Python packages.

## Agent integration (OpenClaw / scenario_cli.py)

`scenario_cli.py` lets an external agent run scenarios via structured JSON rather than natural language directly touching the model:

```bash
python3 scenario_cli.py '{"num_aes": 5}' --base-preset Mid-Market
```

The intended architecture: **natural language → agent's LLM interprets into structured JSON → this script runs the deterministic engine → results returned → agent explains them back in plain language.** The LLM never computes a financial output itself — it only ever produces a field-override JSON object, which this script validates against known fields before running the same engine modules the Streamlit app uses.

## Author's note

This was built iteratively through an extended working session, with each phase stress-tested and numerous real bugs found and fixed along the way — not a single clean pass. Documented examples across the codebase and this README include: a revenue-recognition reconciliation bug where renewal math was computed correctly but never fed back into the live ARR trajectory; a new-business/renewal conflation bug where renewal-generated contracts silently inflated "new ARR booked"; a column-collision bug in the Excel generator that silently zeroed out every recognized-revenue formula; a renewal-event bucketing convention mismatch between the Python engine and the Excel export that dropped the final in-window renewal event; and a preset-switching bug in the Streamlit UI where changing the segment dropdown only changed a text label, not any of the underlying assumptions. Each is documented rather than quietly patched, since the debugging process itself — and the discipline of catching these before they reached a "working" state — is part of what this project is meant to demonstrate.
