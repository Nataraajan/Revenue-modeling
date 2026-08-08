# Revenue Architecture Model

A deterministic, three-phase B2B SaaS revenue model — pipeline/capacity, revenue recognition, and renewals — built as a portfolio project grounded in a real operational problem, not a generic exercise.

**Live app:** [Streamlit deployment link]

---

## Why this exists

Most "revenue models" in FP&A portfolios stop at a bookings forecast. This one is built around a specific, lived failure: a prior attempt to build a multi-year P&L/cashflow plan in Excel/Google Sheets broke down because it conflated three genuinely different timelines — **when a deal is signed (bookings)**, **when cash is collected (billings)**, and **when revenue can actually be recognized (ASC 606)**. That gap — an account signed but not yet live, sitting invisible between bookings and revenue — is the specific thing this model is built to make visible and correct.

## Framework grounding

Built on the **Bowtie Model** (Winning by Design / Jacco van der Kooij's Revenue Architecture), which extends the traditional sales funnel across the full customer lifecycle rather than stopping at close:

- **Left side (pre-revenue):** Awareness → Education → Selection → Mutual Commit — demand generation, pipeline, AE/BDR capacity
- **Middle (the MEDFAR pain point):** Commit → Onboard — implementation lag, revenue recognition
- **Right side (post-revenue):** Onboard → Adopt → Impact → Expand/Renew — churn, expansion, NRR

Each side is built as an independent, standalone-demoable phase, then bridged together.

## Architecture — three phases, one bridge pattern

| File | Phase | What it does |
|---|---|---|
| `capacity_engine.py` | 1 | Dual-constraint pipeline/capacity engine. Segments into "pods" (SMB/Mid-Market/Enterprise/Inbound), each with independently configurable AE/BDR headcount, comp, quota, demand assumptions, and seasonality. |
| `revenue_recognition_engine.py` | 2 | ASC 606 revenue recognition. Converts bookings into contracts, tracks implementation lag → go-live → ratable recognition, deferred revenue balance, and professional services fees (point-in-time, distinct performance obligation). |
| `renewal_engine.py` | 3 | Renewal/churn/expansion at contract term-end. Generates real follow-on contracts so ARR is genuinely continuous across renewal cycles (not just a diagnostic side-calculation). Produces the standard SaaS ARR waterfall and NRR. |
| `app.py` | — | Streamlit dashboard wiring all three phases together with live inputs. |

**Bridge pattern:** Phase 2's `bookings_to_contracts()` and Phase 3's `run_full_lifecycle()` always pull assumptions (avg deal size, term, implementation lag, etc.) directly from the same `PodConfig` object Phase 1 used — never re-specified as separate parameters. This was a deliberate fix partway through development after finding a duplicate-assumption risk (two phases could silently disagree about the same pod's deal size).

## Key design decisions (read before flagging as a bug)

- **No randomization, anywhere.** Every input is an explicit, named, user-set variable — not a probability distribution or Monte Carlo draw. This was a direct instruction from the model's owner: the goal is a model where every number is defensible and explainable in an interview, not one that requires explaining away stochastic behavior.
- **Churn/expansion/contraction rates are applied directly as annual rates, with no term-based compounding.** An earlier version compounded annual rates over contract term length (e.g., scaling a 12% annual churn rate up for a 24-month contract). This was deliberately removed: contracts are modeled as annual (12-month) by default, matching standard B2B SaaS practice, and since cohorts renew every month on a rolling basis, the annual rate already *is* the per-renewal-event rate.
- **Capacity is a hard ceiling, always** — even when `execution_efficiency` is set above 1.0. A rep cannot close more than their quota-adjusted capacity allows, no matter how well "execution" is modeled.
- **Commission accelerators are intentionally not modeled.** The pooled team-level attainment calculation used throughout (`actual_bookings = min(capacity, demand)`) mathematically cannot exceed 100% team attainment, so accelerators (which only trigger on individual reps exceeding their own quota) would be structurally dead code. Modeling them properly would require per-rep stochastic variance — which conflicts with the no-randomization constraint above.
- **New-business bookings and renewal ARR are explicitly separated** (`Contract.origin` field: `"new"` vs `"renewal"`). An earlier version let renewal-generated contracts silently count toward "new ARR booked," inflating apparent new-business growth. Fixed by tagging contract origin and filtering Phase 2's acquisition-lens metrics accordingly.
- **Professional services/implementation fees** default to point-in-time recognition at go-live (the "distinct performance obligation" treatment under ASC 606). The alternative treatment — bundled with subscription, recognized ratably (used when implementation isn't distinct from the subscription) — is also implemented and switchable via `Contract.ps_fee_treatment`, since which treatment applies is a real judgment call, not a settled fact.
- **Seasonality is a fully explicit, user-set 12-month multiplier pattern** (`PodConfig.seasonality_pattern`), not inferred or randomized — cycles automatically for multi-year scenarios.

## Known simplifications (flagged, not hidden)

- All reps within one pod share an identical comp/quota template — no rep-to-rep variance within a segment.
- Synthetic contracts are generated by dividing a pod's monthly bookings $ by its average deal size — real deal sizes vary around that average; this is an approximation, not individual deal-level data.
- BDR "quota" is denominated in SQL units, not dollars — deliberately kept separate from the AE quota:OTE ratio math, since dividing SQLs by OTE dollars is meaningless (this was caught and fixed during development; an earlier version silently produced a nonsensical `0.0` ratio for BDRs).
- Logo churn rate defaults to the revenue churn rate if not separately specified — in reality, churned logos usually skew smaller than average, so logo churn is often higher than revenue churn. Overridable via `RenewalAssumptions.logo_churn_rate_annual`.
- The last few months of any scenario window will show elevated "implementation backlog," since late-signed contracts don't have enough runway left in the window to reach go-live. This is a real boundary effect of finite simulation windows, not a bug — flagged here so it isn't misread as a performance problem when reviewing output near the end of any run.

## Testing

29 edge case tests across three files, all passing as of the last run:

- `edge_case_tests.py` (8 tests) — Phase 1: zero AEs/BDRs/leads, mid-scenario hiring, execution efficiency bounds, pod hire_months validation, empty pods in multi-pod scenarios.
- `edge_case_tests_revrec.py` (12 tests) — Phase 2: zero implementation lag, contract term exceeding observation window, late-signed contracts, all three billing frequencies, deferred revenue non-negativity, bridge consistency.
- `edge_case_tests_renewal.py` (9 tests) — Phase 3: 100% churn, 0% churn/expansion/contraction, unconfigured pods, cascading renewals, origin-tagging correctness, extreme rate combinations.

Run any test file directly: `python3 edge_case_tests.py`

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Author's note

This was built iteratively through an extended working session, with each phase stress-tested and several real bugs found and fixed along the way (not a single clean pass) — including a revenue-recognition reconciliation bug where renewal math was computed correctly but never fed back into the live ARR trajectory, and the new-business/renewal conflation bug noted above. Both are documented here rather than quietly patched, since the debugging process itself is part of what this project is meant to demonstrate.
