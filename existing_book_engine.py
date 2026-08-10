"""
Existing Book Engine — top-line ARR/revenue overlay for a pre-existing
customer base, layered alongside (not through) the Contract-based engine.

Why this is separate from Phase 1-3: those model NEW business from
individual contracts with real signed/go-live/term dates. An existing book
imported from a revenue extract has none of that — no contract dates, no
implementation lag, no deferred revenue schedule by customer. Per explicit
scope decision: this is a pure top-line ARR/revenue overlay, not run
through the Contract machinery.

Two pieces:
  1. derive_book_metrics() — computes REAL trailing-12-month churn,
     expansion, contraction, and NRR directly from a customer x month
     revenue extract, by matching each customer's revenue 12 months ago
     to their revenue today. This is the actual standard way SaaS
     companies calculate NRR — not a guessed input.
  2. project_existing_book_runoff() — takes an annual rate (either the
     derived one, or a manually overridden one) and projects smooth
     MONTHLY decay/growth forward, since without individual contract
     dates there's no real "renewal month" to anchor a discrete event to.
     An annual rate is converted to its monthly-equivalent via standard
     compounding (1/12 root) — this is unrelated to the term-compounding
     question resolved in Phase 3; that was about NOT scaling risk by
     contract length for a once-a-year event, this is just spreading one
     annual number across 12 equal monthly steps.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd


# ---------------------------------------------------------------------------
# 1. LOADING THE EXTRACT
# ---------------------------------------------------------------------------

def load_customer_revenue_extract(
    df: pd.DataFrame,
    customer_col: str = "customer_id",
    month_col: str = "month",
    revenue_col: str = "revenue",
) -> pd.DataFrame:
    """
    Expects LONG format: one row per customer per month.
      customer_id | month (YYYY-MM or date) | revenue

    Pivots to a customer x month matrix (customers as rows, months as
    columns, chronologically sorted), which is what the derivation
    function needs. Missing customer-month combinations fill as 0
    (customer didn't exist / had no revenue that month).
    """
    df = df.copy()
    df[month_col] = pd.to_datetime(df[month_col]).dt.to_period("M")
    matrix = df.pivot_table(index=customer_col, columns=month_col, values=revenue_col, aggfunc="sum", fill_value=0.0)
    matrix = matrix.reindex(sorted(matrix.columns), axis=1)
    return matrix


# ---------------------------------------------------------------------------
# 2. DERIVING REAL CHURN / EXPANSION / NRR FROM MATCHED CUSTOMERS
# ---------------------------------------------------------------------------

@dataclass
class DerivedBookMetrics:
    base_arr: float                    # last month's revenue x 12 — the starting point for projection
    matched_beginning_arr: float       # ARR-equivalent (x12) of customers who had revenue 12mo ago
    churned_arr: float
    contraction_arr: float
    expansion_arr: float
    nrr_pct: float
    implied_annual_churn_rate: float
    implied_annual_expansion_rate: float
    implied_annual_contraction_rate: float
    new_business_arr_last_12mo: float  # informational only — revenue from customers who started
                                        # within the window. NOT part of the churn/NRR calc (they
                                        # have no month-12-ago baseline to compare against).
    customers_matched: int
    customers_churned: int
    base_logo_count: int                # customers with revenue > 0 in the most recent month —
                                         # starting point for projecting logo count forward
    avg_customer_arpa: float            # matched_beginning_arr / customers_matched — used only as
                                         # a reference figure; NOT used to re-derive base_logo_count


def derive_book_metrics(revenue_matrix: pd.DataFrame, lookback_months: int = 12) -> DerivedBookMetrics:
    """
    Matches each customer's revenue `lookback_months` ago to their revenue
    in the most recent month, and classifies the outcome:
      - had revenue then, $0 now         -> churned
      - had revenue then, less now       -> contraction
      - had revenue then, more now       -> expansion
      - had revenue then, same now       -> flat (no bridge impact)
      - no revenue at the earlier point  -> new business (excluded from
        the churn/NRR calc entirely — there's nothing to compare against)

    All dollar bridge amounts are ARR-equivalent (single-month snapshot x
    12), consistent with how base_arr is defined elsewhere in this model.
    """
    if revenue_matrix.shape[1] < lookback_months + 1:
        raise ValueError(
            f"Need at least {lookback_months + 1} months of data to compare "
            f"'{lookback_months} months ago' vs. 'most recent month'; got {revenue_matrix.shape[1]}."
        )

    latest_month = revenue_matrix.columns[-1]
    earlier_month = revenue_matrix.columns[-1 - lookback_months]

    now = revenue_matrix[latest_month]
    then = revenue_matrix[earlier_month]

    matched = then[then > 0]  # customers who had revenue at the earlier point
    matched_now = now.reindex(matched.index).fillna(0.0)

    churned_mask = matched_now == 0
    contraction_mask = (matched_now > 0) & (matched_now < matched)
    expansion_mask = matched_now > matched

    churned_arr = matched[churned_mask].sum() * 12
    contraction_arr = (matched[contraction_mask] - matched_now[contraction_mask]).sum() * 12
    expansion_arr = (matched_now[expansion_mask] - matched[expansion_mask]).sum() * 12
    matched_beginning_arr = matched.sum() * 12

    nrr = (matched_beginning_arr + expansion_arr - contraction_arr - churned_arr) / matched_beginning_arr if matched_beginning_arr > 0 else None

    new_customers = now[~now.index.isin(matched.index) & (now > 0)]
    new_business_arr = new_customers.sum() * 12

    base_arr = now.sum() * 12
    base_logo_count = int((now > 0).sum())
    avg_customer_arpa = round(matched_beginning_arr / matched.shape[0], 2) if matched.shape[0] > 0 else 0.0

    return DerivedBookMetrics(
        base_arr=round(base_arr, 2),
        matched_beginning_arr=round(matched_beginning_arr, 2),
        churned_arr=round(churned_arr, 2),
        contraction_arr=round(contraction_arr, 2),
        expansion_arr=round(expansion_arr, 2),
        nrr_pct=round(nrr * 100, 1) if nrr is not None else None,
        implied_annual_churn_rate=round(churned_arr / matched_beginning_arr, 4) if matched_beginning_arr > 0 else None,
        implied_annual_expansion_rate=round(expansion_arr / matched_beginning_arr, 4) if matched_beginning_arr > 0 else None,
        implied_annual_contraction_rate=round(contraction_arr / matched_beginning_arr, 4) if matched_beginning_arr > 0 else None,
        new_business_arr_last_12mo=round(new_business_arr, 2),
        customers_matched=int(matched.shape[0]),
        customers_churned=int(churned_mask.sum()),
        base_logo_count=base_logo_count,
        avg_customer_arpa=avg_customer_arpa,
    )


# ---------------------------------------------------------------------------
# 3. PROJECTING SMOOTH MONTHLY RUNOFF
# ---------------------------------------------------------------------------

def project_existing_book_runoff(
    base_arr: float,
    annual_churn_rate: float,
    annual_expansion_rate: float,
    annual_contraction_rate: float,
    num_months: int,
    base_logo_count: int = 0,
) -> pd.DataFrame:
    """
    Projects the existing book forward with smooth monthly decay/growth.
    Annual rates are converted to their monthly-equivalent via standard
    compounding (not applied as flat annual_rate/12 — that would understate
    the true monthly effect needed to hit the stated annual rate).

    Churn/expansion/contraction dollar impact is tracked as three SEPARATE
    deltas each month (not just one blended ending number), so downstream
    reporting (e.g. a SaaS metrics dashboard) can show dollar churn,
    expansion, and contraction independently — consistent with how the
    Contract-based renewal engine already reports these for new business.

    Logo count is projected forward too, declining by churn only —
    expansion/contraction change dollars per logo, not logo count itself.
    """
    monthly_churn = 1 - (1 - annual_churn_rate) ** (1 / 12)
    monthly_expansion = (1 + annual_expansion_rate) ** (1 / 12) - 1
    monthly_contraction = 1 - (1 - annual_contraction_rate) ** (1 / 12)

    rows = []
    arr = base_arr
    logo_count = base_logo_count
    for month in range(num_months):
        after_churn = arr * (1 - monthly_churn)
        churn_dollar = arr - after_churn

        after_expansion = after_churn * (1 + monthly_expansion)
        expansion_dollar = after_expansion - after_churn

        after_contraction = after_expansion * (1 - monthly_contraction)
        contraction_dollar = after_expansion - after_contraction

        arr = after_contraction
        logo_count_before = logo_count
        logo_count = logo_count * (1 - monthly_churn)
        logos_churned = logo_count_before - logo_count
        monthly_revenue = arr / 12  # top-line proxy: this month's revenue ≈ ending ARR / 12

        rows.append({
            "month": month + 1,
            "existing_book_arr": round(arr, 2),
            "existing_book_monthly_revenue": round(monthly_revenue, 2),
            "existing_book_churn_dollar": round(churn_dollar, 2),
            "existing_book_expansion_dollar": round(expansion_dollar, 2),
            "existing_book_contraction_dollar": round(contraction_dollar, 2),
            "existing_book_logo_count": round(logo_count, 2),  # expected value, not a literal integer
            "existing_book_logos_churned": round(logos_churned, 2),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3B. HISTORICAL ANNUAL ACTUALS — real year-over-year metrics computed
#     directly from the extract itself (not projected/derived rates), for
#     every full year boundary present in the historical data. Lets the
#     dashboard show actual history continuing into the forward forecast,
#     rather than the forecast appearing to start from nothing.
# ---------------------------------------------------------------------------

def derive_annual_history(revenue_matrix: pd.DataFrame) -> pd.DataFrame:
    """
    Computes ACTUAL annual metrics (same column shape as saas_metrics'
    forecast output, so the two can be concatenated into one continuous
    timeline) for every full 12-month year present in the extract.
    The first available year has no prior-year baseline, so its
    NRR/churn/expansion fields are None — there's nothing to compare against.
    """
    months = list(revenue_matrix.columns)
    num_full_years = len(months) // 12
    rows = []

    for y in range(num_full_years):
        year_start_idx = y * 12
        year_end_idx = year_start_idx + 11
        year_months = months[year_start_idx:year_end_idx + 1]
        end_month = months[year_end_idx]

        ending_arr = revenue_matrix[end_month].sum() * 12
        ending_logos = int((revenue_matrix[end_month] > 0).sum())
        revenue = revenue_matrix[year_months].sum().sum()

        if year_start_idx - 1 >= 0:
            begin_month = months[year_start_idx - 1]
            then = revenue_matrix[begin_month]
            now = revenue_matrix[end_month]
            beginning_arr = then.sum() * 12
            beginning_logos = int((then > 0).sum())

            matched = then[then > 0]
            matched_now = now.reindex(matched.index).fillna(0.0)
            churned_mask = matched_now == 0
            contraction_mask = (matched_now > 0) & (matched_now < matched)
            expansion_mask = matched_now > matched

            churned_arr = matched[churned_mask].sum() * 12
            contraction_arr = (matched[contraction_mask] - matched_now[contraction_mask]).sum() * 12
            expansion_arr = (matched_now[expansion_mask] - matched[expansion_mask]).sum() * 12
            nrr = (beginning_arr + expansion_arr - contraction_arr - churned_arr) / beginning_arr if beginning_arr > 0 else None
            gross_churn_rate = churned_arr / beginning_arr if beginning_arr > 0 else None

            new_customers_mask = (then == 0) & (now > 0)
            new_arr = now[new_customers_mask].sum() * 12
            new_logos = int(new_customers_mask.sum())
            churned_logos = int(churned_mask.sum())
            logo_churn_rate = churned_logos / beginning_logos if beginning_logos > 0 else None
        else:
            beginning_arr = None
            new_arr = expansion_arr = contraction_arr = churned_arr = 0.0
            nrr = gross_churn_rate = logo_churn_rate = None
            new_logos = churned_logos = None
            beginning_logos = None

        arpa_ending = ending_arr / ending_logos if ending_logos > 0 else None

        rows.append({
            "period": f"Actual Y-{num_full_years - y}",
            "type": "Actual",
            "beginning_arr": round(beginning_arr, 2) if beginning_arr is not None else None,
            "ending_arr": round(ending_arr, 2),
            "new_arr_booked": round(new_arr, 2) if new_arr is not None else None,
            "expansion_arr": round(expansion_arr, 2),
            "contraction_arr": round(contraction_arr, 2),
            "churned_arr": round(churned_arr, 2),
            "nrr_pct": round(nrr * 100, 1) if nrr is not None else None,
            "gross_dollar_churn_rate_pct": round(gross_churn_rate * 100, 1) if gross_churn_rate is not None else None,
            "beginning_logos": beginning_logos,
            "ending_logos": ending_logos,
            "new_logos": new_logos,
            "churned_logos": churned_logos,
            "logo_churn_rate_pct": round(logo_churn_rate * 100, 1) if logo_churn_rate is not None else None,
            "revenue": round(revenue, 2),
            "arpa_ending": round(arpa_ending, 2) if arpa_ending is not None else None,
            "ltv": None,  # not computed for historical actuals — gross margin isn't in a revenue extract
            "other_boundary_effect": 0.0,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. EXAMPLE RUN — synthetic extract, 20 customers, 24 months, built-in
#    churn/expansion, to verify derivation math against known inputs
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random
    random.seed(42)  # deterministic test data generation only — NOT part of the model itself

    rows = []
    customers = [f"cust_{i}" for i in range(1, 21)]
    start_revenue = {c: random.uniform(2000, 15000) for c in customers}
    # Deliberately churn 3 customers after month 12, expand 4, contract 2, leave rest flat
    churned_custs = customers[0:3]
    expanded_custs = customers[3:7]
    contracted_custs = customers[7:9]
    new_custs_after_month12 = ["cust_new_1", "cust_new_2"]

    for month_idx in range(24):
        month_str = f"2024-{month_idx+1:02d}" if month_idx < 12 else f"2025-{month_idx-11:02d}"
        for c in customers:
            rev = start_revenue[c]
            if month_idx >= 12:
                if c in churned_custs:
                    rev = 0.0
                elif c in expanded_custs:
                    rev = rev * 1.25
                elif c in contracted_custs:
                    rev = rev * 0.7
            rows.append({"customer_id": c, "month": month_str, "revenue": rev})
        if month_idx >= 12:
            for nc in new_custs_after_month12:
                rows.append({"customer_id": nc, "month": month_str, "revenue": random.uniform(3000, 8000)})

    extract_df = pd.DataFrame(rows)
    matrix = load_customer_revenue_extract(extract_df)
    print(f"Loaded matrix: {matrix.shape[0]} customers x {matrix.shape[1]} months\n")

    metrics = derive_book_metrics(matrix, lookback_months=12)
    print("--- DERIVED BOOK METRICS ---")
    for k, v in metrics.__dict__.items():
        print(f"{k}: {v}")

    print("\n--- PROJECTED RUNOFF (using derived rates) ---")
    runoff_df = project_existing_book_runoff(
        base_arr=metrics.base_arr,
        annual_churn_rate=metrics.implied_annual_churn_rate,
        annual_expansion_rate=metrics.implied_annual_expansion_rate,
        annual_contraction_rate=metrics.implied_annual_contraction_rate,
        num_months=24,
        base_logo_count=metrics.base_logo_count,
    )
    print(runoff_df.to_string(index=False))
