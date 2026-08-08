"""
Revenue Architecture — Phase 2: Revenue Recognition Engine
============================================================

Middle of the Bowtie Model: Commit -> Onboard.

This is the module grounded directly in the real pain point that started
this whole project: a signed deal is NOT revenue. There's a lag between
"signed" and "live," and only once live can revenue be recognized —
ratably, straight-line, over the contract term (ASC 606, performance
obligation satisfied over time — the standard treatment for SaaS
subscriptions).

Three separate timelines that a hung spreadsheet conflates:
  1. BOOKINGS   — when the deal is signed (Phase 1's output)
  2. BILLINGS   — when cash is actually invoiced/collected
  3. REVENUE    — when revenue can be recognized under ASC 606

Deferred revenue = cumulative billings - cumulative revenue recognized.
That gap is a real balance sheet liability, and it's exactly the number
that a naive "bookings = revenue" model gets wrong.

Design principles (unchanged from Phase 1):
- Pure, deterministic math. No AI in this file, ever — this is accounting
  logic, and it must be exactly right, not "approximately right."
- Every assumption explicit in a dataclass.
- Standalone module; connects to Phase 1 via a bridge function at the
  bottom, but doesn't require it to run or be tested independently.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd


# ---------------------------------------------------------------------------
# 1. BILLING FREQUENCY — determines when cash is invoiced, independent of
#    when revenue is recognized
# ---------------------------------------------------------------------------

class BillingFrequency(Enum):
    ANNUAL_UPFRONT = "annual_upfront"   # full contract value billed at signing
    MONTHLY = "monthly"                  # billed evenly across the term
    QUARTERLY = "quarterly"              # billed in equal quarterly installments


# ---------------------------------------------------------------------------
# 2. CONTRACT — one signed deal
# ---------------------------------------------------------------------------

@dataclass
class Contract:
    contract_id: str
    pod_name: str
    signed_month: int                  # absolute month index deal was signed (booked)
    contract_value: float              # total value over the full term
    term_months: int                   # subscription term length
    implementation_lag_months: int     # signed -> go-live gap (the MEDFAR pain point)
    billing_frequency: BillingFrequency = BillingFrequency.ANNUAL_UPFRONT
    origin: str = "new"                # "new" (organic acquisition) or "renewal" (continuation
                                        # of an existing account). Distinguishes genuine new-logo
                                        # bookings from renewal ARR — conflating the two would let
                                        # renewal continuations masquerade as new-business growth.
    professional_services_fee: float = 0.0
    # One-time implementation/onboarding fee, separate from subscription value.
    ps_fee_treatment: str = "point_in_time_at_go_live"
    # ASC 606 judgment call, made explicit rather than assumed:
    #   "point_in_time_at_go_live" — implementation is a DISTINCT performance
    #      obligation (customer could source it elsewhere; it's a real,
    #      separate deliverable). Recognized in full the month service
    #      completes (go-live). This is the default, matching "recognized
    #      when an account is implemented."
    #   "ratable_with_subscription" — implementation is NOT distinct (so
    #      integrated the subscription is unusable without it). Must be
    #      bundled with subscription revenue and recognized ratably over
    #      the term instead — a real, common audit finding when companies
    #      get this judgment call wrong. Supported here for comparison,
    #      not the default.

    @property
    def go_live_month(self) -> int:
        """Revenue recognition cannot begin before this month."""
        return self.signed_month + self.implementation_lag_months

    @property
    def recognition_end_month(self) -> int:
        return self.go_live_month + self.term_months - 1

    @property
    def monthly_recognized_amount(self) -> float:
        return self.contract_value / self.term_months if self.term_months else 0.0

    @property
    def annual_contract_value(self) -> float:
        """ACV — the annualized run-rate value of this contract, distinct from
        contract_value (total contract value over the FULL term). A 24-month,
        $220K TCV deal is $110K ACV/ARR, not $220K — conflating these two is a
        common and misleading error when reporting 'ARR booked'."""
        years = self.term_months / 12
        return self.contract_value / years if years else 0.0

    def revenue_recognized_in(self, month: int) -> float:
        """ASC 606 ratable recognition: zero before go-live, zero after term
        ends, straight-line in between. This is intentionally the ONLY
        recognition method modeled — usage-based/milestone recognition is
        a real alternative pattern but out of scope here."""
        if self.go_live_month <= month <= self.recognition_end_month:
            return self.monthly_recognized_amount
        return 0.0

    def billed_in(self, month: int) -> float:
        """Cash billed this month — independent of revenue recognition.
        This is what actually shows up as a receivable/cash event."""
        if self.billing_frequency == BillingFrequency.ANNUAL_UPFRONT:
            return self.contract_value if month == self.signed_month else 0.0

        if self.billing_frequency == BillingFrequency.MONTHLY:
            # Billed evenly across the term, starting at signing (not go-live —
            # many SaaS contracts bill from signature regardless of implementation
            # status; this is a real source of customer friction worth flagging
            # in Phase 3's CS/adoption layer, not silently assumed away here).
            if self.signed_month <= month < self.signed_month + self.term_months:
                return self.contract_value / self.term_months
            return 0.0

        if self.billing_frequency == BillingFrequency.QUARTERLY:
            installment = self.contract_value / max(1, (self.term_months // 3))
            months_since_signed = month - self.signed_month
            if 0 <= months_since_signed < self.term_months and months_since_signed % 3 == 0:
                return installment
            return 0.0

        return 0.0

    def is_in_implementation_backlog(self, month: int) -> bool:
        """True if this contract is signed but not yet live in `month` —
        the exact status that broke the MEDFAR spreadsheet: real dollars,
        signed and committed, sitting invisible between bookings and revenue."""
        return self.signed_month <= month < self.go_live_month

    def ps_fee_billed_in(self, month: int) -> float:
        """Professional services fee is billed once, upfront at signing —
        standard practice (companies collect for implementation before
        performing it, distinct from ongoing subscription billing)."""
        return self.professional_services_fee if month == self.signed_month else 0.0

    def ps_fee_revenue_recognized_in(self, month: int) -> float:
        if self.professional_services_fee <= 0:
            return 0.0

        if self.ps_fee_treatment == "point_in_time_at_go_live":
            # Distinct performance obligation: fully recognized the month
            # implementation completes (go-live), not spread out.
            return self.professional_services_fee if month == self.go_live_month else 0.0

        if self.ps_fee_treatment == "ratable_with_subscription":
            # Not distinct: bundled with subscription, recognized ratably
            # over the same term and window as subscription revenue.
            if self.go_live_month <= month <= self.recognition_end_month:
                return self.professional_services_fee / self.term_months if self.term_months else 0.0
            return 0.0

        raise ValueError(f"Unknown ps_fee_treatment: {self.ps_fee_treatment}")


# ---------------------------------------------------------------------------
# 3. RECOGNITION ENGINE — runs the whole contract book month by month
# ---------------------------------------------------------------------------

def run_recognition(contracts: list, num_months: int) -> pd.DataFrame:
    rows = []
    cumulative_billings = 0.0
    cumulative_revenue = 0.0

    for month in range(num_months):
        month_billings = sum(c.billed_in(month) for c in contracts)
        month_revenue = sum(c.revenue_recognized_in(month) for c in contracts)
        month_new_bookings = sum(c.contract_value for c in contracts if c.signed_month == month)

        # --- Professional services fee: tracked as a separate line item,
        # not conflated with subscription revenue — different recognition
        # timing, different nature (one-time service vs. recurring). ---
        month_ps_billings = sum(c.ps_fee_billed_in(month) for c in contracts)
        month_ps_revenue = sum(c.ps_fee_revenue_recognized_in(month) for c in contracts)

        # --- Accounts / ARPA decomposition (new bookings this month) ---
        # Only ORGANIC new-logo contracts count here — renewal continuations
        # are a different thing (retention, not acquisition) and must not
        # inflate this metric. See Contract.origin.
        new_contracts_this_month = [c for c in contracts if c.signed_month == month and c.origin == "new"]
        new_accounts_signed = len(new_contracts_this_month)
        new_arr_booked = sum(c.annual_contract_value for c in new_contracts_this_month)
        arpa_new_accounts = (new_arr_booked / new_accounts_signed) if new_accounts_signed else None

        # --- Booked ARR: cumulative ORGANIC bookings only (excludes renewal
        # continuations, which would otherwise double-count the same logo's
        # ARR every time it renews) ---
        signed_to_date = [c for c in contracts if c.signed_month <= month and c.origin == "new"]
        cumulative_accounts_signed = len(signed_to_date)
        cumulative_arr_booked = sum(c.annual_contract_value for c in signed_to_date)
        blended_arpa_booked = (
            cumulative_arr_booked / cumulative_accounts_signed if cumulative_accounts_signed else None
        )

        # --- Live ARR: origin-agnostic by design — a renewed account is
        # just as "live" as a brand-new one, and this is the number that
        # should actually keep growing through renewals + expansion ---
        live_contracts = [c for c in contracts if c.go_live_month <= month <= c.recognition_end_month]
        live_accounts = len(live_contracts)
        live_arr = sum(c.annual_contract_value for c in live_contracts)
        blended_arpa_live = (live_arr / live_accounts) if live_accounts else None

        backlog_contracts = [c for c in contracts if c.is_in_implementation_backlog(month)]
        implementation_backlog_value = sum(c.contract_value for c in backlog_contracts)
        implementation_backlog_count = len(backlog_contracts)

        cumulative_billings += month_billings + month_ps_billings
        cumulative_revenue += month_revenue + month_ps_revenue
        deferred_revenue_balance = cumulative_billings - cumulative_revenue

        rows.append({
            "month": month + 1,
            "new_bookings_tcv": round(month_new_bookings, 2),
            "new_accounts_signed": new_accounts_signed,
            "new_arr_booked": round(new_arr_booked, 2),
            "arpa_new_accounts": round(arpa_new_accounts, 2) if arpa_new_accounts else None,
            "cumulative_accounts_signed": cumulative_accounts_signed,
            "cumulative_arr_booked": round(cumulative_arr_booked, 2),
            "blended_arpa_booked": round(blended_arpa_booked, 2) if blended_arpa_booked else None,
            "live_accounts": live_accounts,
            "live_arr": round(live_arr, 2),
            "blended_arpa_live": round(blended_arpa_live, 2) if blended_arpa_live else None,
            "subscription_billings": round(month_billings, 2),
            "subscription_revenue_recognized": round(month_revenue, 2),
            "ps_fee_billings": round(month_ps_billings, 2),
            "ps_fee_revenue_recognized": round(month_ps_revenue, 2),
            "total_billings": round(month_billings + month_ps_billings, 2),
            "total_revenue_recognized": round(month_revenue + month_ps_revenue, 2),
            "cumulative_billings": round(cumulative_billings, 2),
            "cumulative_revenue_recognized": round(cumulative_revenue, 2),
            "deferred_revenue_balance": round(deferred_revenue_balance, 2),
            "implementation_backlog_value": round(implementation_backlog_value, 2),
            "implementation_backlog_count": implementation_backlog_count,
        })

    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, contracts: list) -> dict:
    if len(df) == 0 or not contracts:
        return {"note": "No contracts or zero-month scenario — nothing to summarize."}

    avg_lag = sum(c.implementation_lag_months for c in contracts) / len(contracts)
    max_backlog = df["implementation_backlog_value"].max()
    max_backlog_month = df.loc[df["implementation_backlog_value"].idxmax(), "month"]

    bookings_vs_revenue_gap = df["new_bookings_tcv"].sum() - df["total_revenue_recognized"].sum()

    ending_booked_arr = df["cumulative_arr_booked"].iloc[-1]
    ending_live_arr = df["live_arr"].iloc[-1]
    ending_accounts_signed = df["cumulative_accounts_signed"].iloc[-1]
    ending_live_accounts = df["live_accounts"].iloc[-1]
    ending_arpa_booked = round(ending_booked_arr / ending_accounts_signed, 2) if ending_accounts_signed else None
    ending_arpa_live = round(ending_live_arr / ending_live_accounts, 2) if ending_live_accounts else None

    return {
        "total_bookings_tcv": round(df["new_bookings_tcv"].sum(), 2),
        "total_revenue_recognized": round(df["total_revenue_recognized"].sum(), 2),
        "total_billings": round(df["total_billings"].sum(), 2),
        "total_ps_fee_revenue": round(df["ps_fee_revenue_recognized"].sum(), 2),
        "total_subscription_revenue": round(df["subscription_revenue_recognized"].sum(), 2),
        "ending_deferred_revenue_balance": round(df["deferred_revenue_balance"].iloc[-1], 2),
        "ending_booked_arr": round(ending_booked_arr, 2),
        "ending_live_arr": round(ending_live_arr, 2),
        "booked_vs_live_arr_gap": round(ending_booked_arr - ending_live_arr, 2),
        "ending_accounts_signed": int(ending_accounts_signed),
        "ending_live_accounts": int(ending_live_accounts),
        "ending_arpa_booked": ending_arpa_booked,
        "ending_arpa_live": ending_arpa_live,
        "avg_implementation_lag_months": round(avg_lag, 1),
        "peak_implementation_backlog_value": round(max_backlog, 2),
        "peak_implementation_backlog_month": int(max_backlog_month),
        "bookings_tcv_not_yet_recognized_as_revenue": round(bookings_vs_revenue_gap, 2),
        "interpretation": (
            f"Booked ARR (${ending_booked_arr:,.0f}) vs. Live ARR (${ending_live_arr:,.0f}) "
            f"differ by ${ending_booked_arr - ending_live_arr:,.0f} — that gap is signed "
            f"revenue not yet live, invisible in a bookings-only or even an ARR-only view "
            f"unless booked-vs-live is tracked separately. ARPA booked (${ending_arpa_booked:,.0f}) "
            f"vs. ARPA live (${ending_arpa_live:,.0f}) shows whether the accounts still in "
            f"implementation skew larger or smaller than the live book."
        ),
    }


# ---------------------------------------------------------------------------
# 4. BRIDGE — converts Phase 1 bookings output into synthetic contracts
# ---------------------------------------------------------------------------

def bookings_to_contracts(
    pod_config,                    # capacity_engine.PodConfig — the actual pod, not a re-typed copy
    pod_bookings_df,               # capacity_engine.run_scenario() output for this exact pod
    billing_frequency: BillingFrequency = BillingFrequency.ANNUAL_UPFRONT,
) -> list:
    """
    Converts a pod's Phase 1 output into synthetic contracts, pulling
    avg_deal_size, term, and implementation lag DIRECTLY from the pod's own
    config — never re-specified here. This guarantees Phase 1 and Phase 2
    can't silently disagree about what a given pod's deals look like.

    billing_frequency is the one assumption not on PodConfig (it's a finance
    policy choice, not a GTM assumption) — passed explicitly here.

    Note: this still approximates individual contracts by dividing each
    month's bookings $ by the pod's avg_deal_size (real deals vary in size
    around that average) — flagged as a simplification, not a hidden one.
    """
    contracts = []
    contract_counter = 0
    for _, row in pod_bookings_df.iterrows():
        month = int(row["month"]) - 1  # convert 1-indexed display month back to 0-indexed
        bookings_dollars = row["actual_bookings"]
        if bookings_dollars <= 0:
            continue
        num_deals = max(1, round(bookings_dollars / pod_config.avg_deal_size))
        value_per_deal = bookings_dollars / num_deals
        arr_per_deal = value_per_deal / (pod_config.contract_term_months / 12)
        ps_fee_per_deal = arr_per_deal * pod_config.professional_services_fee_pct_of_arr
        for _ in range(num_deals):
            contract_counter += 1
            contracts.append(Contract(
                contract_id=f"{pod_config.pod_name}-C{contract_counter}",
                pod_name=pod_config.pod_name,
                signed_month=month,
                contract_value=value_per_deal,
                term_months=pod_config.contract_term_months,
                implementation_lag_months=pod_config.implementation_lag_months,
                professional_services_fee=ps_fee_per_deal,
                billing_frequency=billing_frequency,
            ))
    return contracts


# ---------------------------------------------------------------------------
# 5. EXAMPLE RUN — the MEDFAR scenario: real implementation lag, annual
#    upfront billing, 12-month term
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    contracts = [
        Contract("C1", "MidMarket", signed_month=0, contract_value=180_000,
                 term_months=12, implementation_lag_months=2),
        Contract("C2", "MidMarket", signed_month=1, contract_value=200_000,
                 term_months=12, implementation_lag_months=3),
        Contract("C3", "MidMarket", signed_month=2, contract_value=150_000,
                 term_months=12, implementation_lag_months=1),
        Contract("C4", "MidMarket", signed_month=3, contract_value=220_000,
                 term_months=24, implementation_lag_months=4),  # multi-year, longer lag
        Contract("C5", "MidMarket", signed_month=4, contract_value=190_000,
                 term_months=12, implementation_lag_months=2),
    ]

    df = run_recognition(contracts, num_months=18)
    print(df.to_string(index=False))
    print("\n--- SUMMARY ---")
    for k, v in summarize(df, contracts).items():
        print(f"{k}: {v}")
