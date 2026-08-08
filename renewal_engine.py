"""
Revenue Architecture — Phase 3: Renewal, Churn & Expansion Engine
====================================================================

Right side of the Bowtie Model: Onboard -> Adopt -> Impact -> Expand/Renew.

v2 changes from the first pass, based on real feedback:
1. Churn/expansion/contraction rates are applied DIRECTLY as given (annual
   rate = per-renewal-event rate), with no term-based compounding. Reasoning:
   contracts are modeled as annual (12-month term) by default — matching
   standard B2B SaaS practice — and since new cohorts sign every month on a
   rolling basis, "12% annual churn" already means "12% of any cohort
   churns at its renewal." No conversion needed. (The earlier compounding
   logic was solving a problem that doesn't exist once contracts are annual.)
2. Renewals now generate a REAL Contract object that gets added back into
   the contract list, so Phase 2's live_arr trajectory is genuinely
   continuous across renewal events — including cascading renewals (a
   contract that renews can renew again a year later). This closes the
   reconciliation gap from the first pass, where renewal math was computed
   but its output evaporated instead of feeding forward.

Design principle carried over: NO randomization anywhere. Churn/expansion/
contraction are explicit, deterministic rates applied to a cohort of ARR
reaching renewal — not a stochastic per-account event.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd

from revenue_recognition_engine import Contract, run_recognition, BillingFrequency


# ---------------------------------------------------------------------------
# 1. RENEWAL ASSUMPTIONS — explicit, deterministic, per pod
# ---------------------------------------------------------------------------

@dataclass
class RenewalAssumptions:
    pod_name: str
    gross_revenue_churn_rate_annual: float     # e.g. 0.12 = 12% of ARR up for renewal is lost, every renewal
    expansion_rate_annual: float               # e.g. 0.18 = 18% ARR gained via upsell, among renewing accounts
    contraction_rate_annual: float = 0.0       # e.g. downgrades among renewing accounts (distinct from full churn)
    logo_churn_rate_annual: Optional[float] = None
    # If not given, defaults to the revenue churn rate — a simplification
    # (in reality, churned logos usually skew smaller than average, so logo
    # churn is often HIGHER than revenue churn). Flagged, not hidden.

    def logo_churn_rate(self) -> float:
        return self.logo_churn_rate_annual if self.logo_churn_rate_annual is not None else self.gross_revenue_churn_rate_annual


# ---------------------------------------------------------------------------
# 2. RENEWAL COHORT MATH — one cohort (pod, one renewal month) at a time
# ---------------------------------------------------------------------------

def compute_renewal_outcome(cohort: list, assumptions: RenewalAssumptions) -> dict:
    """
    Applies the pod's annual rates directly to one renewal cohort's ARR.
    No term-based compounding — see module docstring for why.
    """
    arr_up_for_renewal = sum(c.annual_contract_value for c in cohort)
    logos_up_for_renewal = len(cohort)

    churn_rate = assumptions.gross_revenue_churn_rate_annual
    expansion_rate = assumptions.expansion_rate_annual
    contraction_rate = assumptions.contraction_rate_annual
    logo_churn_rate = assumptions.logo_churn_rate()

    churned_arr = arr_up_for_renewal * churn_rate
    retained_arr = arr_up_for_renewal - churned_arr
    expansion_arr = retained_arr * expansion_rate
    contraction_arr = retained_arr * contraction_rate
    renewed_arr = retained_arr + expansion_arr - contraction_arr

    logos_retained = logos_up_for_renewal * (1 - logo_churn_rate)  # expected value, not a literal integer count
    nrr_this_cohort = (renewed_arr / arr_up_for_renewal) if arr_up_for_renewal > 0 else None

    return {
        "logos_up_for_renewal": logos_up_for_renewal,
        "arr_up_for_renewal": arr_up_for_renewal,
        "churn_rate_applied_pct": round(churn_rate * 100, 2),
        "churned_arr": churned_arr,
        "expansion_arr": expansion_arr,
        "contraction_arr": contraction_arr,
        "renewed_arr": renewed_arr,
        "logos_retained_expected": logos_retained,
        "nrr_this_cohort_pct": round(nrr_this_cohort * 100, 1) if nrr_this_cohort is not None else None,
    }


# ---------------------------------------------------------------------------
# 3. FULL LIFECYCLE ENGINE — sequential month-by-month, renewals feed forward
# ---------------------------------------------------------------------------

def run_full_lifecycle(initial_contracts: list, assumptions_by_pod: dict, num_months: int):
    """
    Walks month by month. At each month, finds contracts whose term just
    ended, applies that pod's renewal math, and — if any ARR survived —
    generates a real renewal Contract and adds it to the working list, so
    it can itself renew again later (cascading). Returns the FULL contract
    list (original + all renewals), the renewal event log, and the final
    Phase 2 recognition DataFrame run over that complete list — so live_arr
    is genuinely continuous, not a diagnostic side calculation.
    """
    contracts = list(initial_contracts)   # grows as renewals are generated
    renewal_rows = []
    renewal_counter = 0

    for month in range(num_months):
        cohort_by_pod = {}
        for c in contracts:
            if c.recognition_end_month == month:
                cohort_by_pod.setdefault(c.pod_name, []).append(c)

        for pod_name, cohort in cohort_by_pod.items():
            if pod_name not in assumptions_by_pod:
                continue  # no renewal assumptions defined for this pod — skip, don't guess
            assumptions = assumptions_by_pod[pod_name]
            outcome = compute_renewal_outcome(cohort, assumptions)

            renewal_rows.append({"month": month + 1, "pod_name": pod_name, **{
                k: (round(v, 2) if isinstance(v, float) else v) for k, v in outcome.items()
            }})

            if outcome["renewed_arr"] > 0:
                renewal_counter += 1
                term = cohort[0].term_months
                # TCV = ARR * years — keeps the ACV/TCV identity correct even
                # if term isn't exactly 12 (still supported, just not the
                # default assumption per B2B SaaS norms).
                renewed_tcv = outcome["renewed_arr"] * (term / 12)
                contracts.append(Contract(
                    contract_id=f"{pod_name}-RENEW-{renewal_counter}",
                    pod_name=pod_name,
                    signed_month=month + 1,        # continues immediately after old term ends
                    contract_value=renewed_tcv,
                    term_months=term,
                    implementation_lag_months=0,   # no re-implementation — account is already live
                    billing_frequency=cohort[0].billing_frequency,
                    origin="renewal",
                ))

    renewals_df = pd.DataFrame(renewal_rows)
    phase2_df = run_recognition(contracts, num_months=num_months)
    return contracts, renewals_df, phase2_df


def summarize_renewals(renewals_df: pd.DataFrame) -> dict:
    if len(renewals_df) == 0:
        return {"note": "No renewal events occurred in this window — no contract reached its term end. "
                         "Expected if the observation window is shorter than the contract term."}

    total_arr_up = renewals_df["arr_up_for_renewal"].sum()
    total_renewed = renewals_df["renewed_arr"].sum()
    total_churned = renewals_df["churned_arr"].sum()
    total_expansion = renewals_df["expansion_arr"].sum()
    total_contraction = renewals_df["contraction_arr"].sum()

    blended_nrr = round(100 * total_renewed / total_arr_up, 1) if total_arr_up > 0 else None

    return {
        "total_renewal_events": len(renewals_df),
        "total_arr_up_for_renewal": round(total_arr_up, 2),
        "total_renewed_arr": round(total_renewed, 2),
        "total_churned_arr": round(total_churned, 2),
        "total_expansion_arr": round(total_expansion, 2),
        "total_contraction_arr": round(total_contraction, 2),
        "blended_nrr_pct": blended_nrr,
        "nrr_benchmark_check": (
            "Healthy (>100% — expansion outpacing churn, the goal of the whole right side of the bowtie)"
            if blended_nrr and blended_nrr >= 100
            else "Below 100% — churn/contraction exceeding expansion, a real retention problem"
            if blended_nrr is not None else "N/A"
        ),
    }


# ---------------------------------------------------------------------------
# 4. EXAMPLE RUN — annual contracts, standard B2B SaaS default
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from capacity_engine import PodConfig, RoleComp, MarketingFunnel, run_scenario
    from revenue_recognition_engine import bookings_to_contracts

    midmarket_pod = PodConfig(
        pod_name="MidMarket", num_aes=3, num_bdrs=2,
        ae_comp_template=RoleComp(annual_base=95_000, annual_variable_at_100pct=95_000, annual_quota=1_100_000),
        bdr_comp_template=RoleComp(annual_base=55_000, annual_variable_at_100pct=30_000, annual_quota=72),
        marketing=MarketingFunnel(monthly_leads=500, lead_to_mql_rate=0.30, mql_to_sql_rate=0.25),
        avg_deal_size=18_000, ae_self_sourced_sqls_per_month=2,
        contract_term_months=12, implementation_lag_months=2,   # annual — standard B2B SaaS
    )

    NUM_MONTHS = 30
    phase1_df = run_scenario(midmarket_pod.build_scenario(NUM_MONTHS))
    initial_contracts = bookings_to_contracts(midmarket_pod, phase1_df, billing_frequency=BillingFrequency.ANNUAL_UPFRONT)

    assumptions = {
        "MidMarket": RenewalAssumptions(
            pod_name="MidMarket",
            gross_revenue_churn_rate_annual=0.12,
            expansion_rate_annual=0.18,
            contraction_rate_annual=0.03,
        )
    }

    all_contracts, renewals_df, phase2_df = run_full_lifecycle(initial_contracts, assumptions, NUM_MONTHS)

    print(f"Started with {len(initial_contracts)} original contracts, ended with {len(all_contracts)} "
          f"total (including {len(all_contracts) - len(initial_contracts)} renewal-generated contracts).\n")

    print("--- RENEWAL EVENTS ---")
    print(renewals_df.to_string(index=False) if len(renewals_df) else "(none)")

    print("\n--- RENEWAL SUMMARY ---")
    for k, v in summarize_renewals(renewals_df).items():
        print(f"{k}: {v}")

    print("\n--- LIVE ARR TRAJECTORY (last 12 months, now includes renewals) ---")
    print(phase2_df[["month", "live_arr", "live_accounts", "new_arr_booked"]].tail(12).to_string(index=False))
