"""
SaaS Metrics Dashboard — aggregates monthly model output (Phase 1-3 new
business + optional Existing Book overlay) into annual and quarterly
periods, and computes standard SaaS metrics: ARR, Revenue, NRR, dollar
churn, logo churn, and LTV.

Design notes:
- LTV is only computed at the ANNUAL level. The formula (ARPA x Gross
  Margin / Annual Churn Rate) requires an annual churn rate — a single
  quarter's churn rate is noisy and not meaningful as an LTV input, so
  quarterly tables omit LTV rather than show a misleading number.
- All aggregation is pure arithmetic on already-computed, already-tested
  monthly output — no new modeling assumptions introduced here beyond
  the gross margin % needed for LTV.
"""

import pandas as pd


def _combined_monthly_series(phase2_df: pd.DataFrame, renewals_df: pd.DataFrame,
                              existing_book_df: pd.DataFrame, all_contracts: list, num_months: int) -> pd.DataFrame:
    """Builds one combined monthly table: new business + existing book (if present).

    IMPORTANT: "new ARR" here is ARR that went LIVE this month (based on
    each contract's go_live_month), not ARR signed/booked this month.
    Those are genuinely different quantities once implementation lag is
    involved — a contract signed in month 11 with a 2-month lag doesn't
    go live (and doesn't join live_arr) until month 13. Using signed-month
    bookings as the bridge's "new ARR" component would double-count nothing
    but would create a phantom reconciliation gap, since backlogged-but-
    not-yet-live ARR would be counted as "new" before it's actually part
    of live_arr. Using go-live-month makes the bridge reconcile exactly
    for new business.
    """
    has_existing = existing_book_df is not None and len(existing_book_df) > 0

    combined = pd.DataFrame({"month": phase2_df["month"]})
    combined["combined_arr"] = phase2_df["live_arr"]
    combined["combined_logo_count"] = phase2_df["live_accounts"]
    combined["combined_revenue"] = phase2_df["total_revenue_recognized"]

    # New ARR = ARR of "new"-origin contracts whose go_live_month falls in this month
    new_arr_by_month = {}
    new_logos_by_month = {}
    for c in all_contracts:
        if c.origin == "new" and 0 <= c.go_live_month < num_months:
            display_month = c.go_live_month + 1
            new_arr_by_month[display_month] = new_arr_by_month.get(display_month, 0.0) + c.annual_contract_value
            new_logos_by_month[display_month] = new_logos_by_month.get(display_month, 0) + 1
    combined["new_arr_booked"] = combined["month"].map(new_arr_by_month).fillna(0.0)
    combined["new_logos_signed"] = combined["month"].map(new_logos_by_month).fillna(0.0)

    # New-business expansion/contraction/churn, from renewal events, mapped to the month they occurred
    for col in ["expansion_arr", "contraction_arr", "churned_arr"]:
        per_month = renewals_df.groupby("month")[col].sum() if len(renewals_df) else pd.Series(dtype=float)
        combined[f"nb_{col}"] = combined["month"].map(per_month).fillna(0.0)

    nb_logo_churn = (
        renewals_df.assign(logos_churned=renewals_df["logos_up_for_renewal"] - renewals_df["logos_retained_expected"])
        .groupby("month")["logos_churned"].sum() if len(renewals_df) else pd.Series(dtype=float)
    )
    combined["nb_logos_churned"] = combined["month"].map(nb_logo_churn).fillna(0.0)

    if has_existing:
        combined["combined_arr"] += existing_book_df["existing_book_arr"].values
        combined["combined_logo_count"] += existing_book_df["existing_book_logo_count"].values
        combined["combined_revenue"] += existing_book_df["existing_book_monthly_revenue"].values
        combined["eb_expansion_arr"] = existing_book_df["existing_book_expansion_dollar"].values
        combined["eb_contraction_arr"] = existing_book_df["existing_book_contraction_dollar"].values
        combined["eb_churned_arr"] = existing_book_df["existing_book_churn_dollar"].values
        combined["eb_logos_churned"] = existing_book_df["existing_book_logos_churned"].values
    else:
        combined["eb_expansion_arr"] = 0.0
        combined["eb_contraction_arr"] = 0.0
        combined["eb_churned_arr"] = 0.0
        combined["eb_logos_churned"] = 0.0

    combined["total_expansion_arr"] = combined["nb_expansion_arr"] + combined["eb_expansion_arr"]
    combined["total_contraction_arr"] = combined["nb_contraction_arr"] + combined["eb_contraction_arr"]
    combined["total_churned_arr"] = combined["nb_churned_arr"] + combined["eb_churned_arr"]
    combined["total_logos_churned"] = combined["nb_logos_churned"] + combined["eb_logos_churned"]

    return combined


def aggregate_periods(phase2_df: pd.DataFrame, renewals_df: pd.DataFrame, existing_book_df, all_contracts: list,
                       num_months: int, period_months: int, gross_margin_pct: float = None,
                       existing_book_base_arr: float = 0.0, existing_book_base_logos: int = 0) -> pd.DataFrame:
    """
    period_months: 12 for annual, 3 for quarterly.
    gross_margin_pct: required to compute LTV — only populated when period_months == 12.
    """
    combined = _combined_monthly_series(phase2_df, renewals_df, existing_book_df, all_contracts, num_months)

    rows = []
    num_periods = (num_months + period_months - 1) // period_months

    for p in range(num_periods):
        start_month = p * period_months + 1
        end_month = min((p + 1) * period_months, num_months)
        period_rows = combined[(combined["month"] >= start_month) & (combined["month"] <= end_month)]
        if len(period_rows) == 0:
            continue

        beginning_arr = (
            combined.loc[combined["month"] == start_month - 1, "combined_arr"].iloc[0]
            if start_month > 1 else existing_book_base_arr
        )
        beginning_logos = (
            combined.loc[combined["month"] == start_month - 1, "combined_logo_count"].iloc[0]
            if start_month > 1 else existing_book_base_logos
        )
        ending_arr = period_rows["combined_arr"].iloc[-1]
        ending_logos = period_rows["combined_logo_count"].iloc[-1]

        new_arr = period_rows["new_arr_booked"].sum()
        expansion_arr = period_rows["total_expansion_arr"].sum()
        contraction_arr = period_rows["total_contraction_arr"].sum()
        churned_arr = period_rows["total_churned_arr"].sum()
        new_logos = period_rows["new_logos_signed"].sum()
        churned_logos = period_rows["total_logos_churned"].sum()
        revenue = period_rows["combined_revenue"].sum()

        nrr = (beginning_arr + expansion_arr - contraction_arr - churned_arr) / beginning_arr if beginning_arr > 0 else None
        dollar_churn_rate = churned_arr / beginning_arr if beginning_arr > 0 else None
        logo_churn_rate = churned_logos / beginning_logos if beginning_logos > 0 else None
        arpa_ending = ending_arr / ending_logos if ending_logos > 0 else None

        row = {
            "period": f"Y{p // (12 // period_months) + 1}" if period_months == 12 else f"Y{p // 4 + 1}-Q{p % 4 + 1}",
            "beginning_arr": round(beginning_arr, 2),
            "ending_arr": round(ending_arr, 2),
            "new_arr_booked": round(new_arr, 2),
            "expansion_arr": round(expansion_arr, 2),
            "contraction_arr": round(contraction_arr, 2),
            "churned_arr": round(churned_arr, 2),
            "nrr_pct": round(nrr * 100, 1) if nrr is not None else None,
            "gross_dollar_churn_rate_pct": round(dollar_churn_rate * 100, 1) if dollar_churn_rate is not None else None,
            "beginning_logos": round(beginning_logos, 1),
            "ending_logos": round(ending_logos, 1),
            "new_logos": round(new_logos, 1),
            "churned_logos": round(churned_logos, 1),
            "logo_churn_rate_pct": round(logo_churn_rate * 100, 1) if logo_churn_rate is not None else None,
            "revenue": round(revenue, 2),
            "arpa_ending": round(arpa_ending, 2) if arpa_ending is not None else None,
        }

        if period_months == 12 and gross_margin_pct is not None and dollar_churn_rate and dollar_churn_rate > 0 and arpa_ending:
            row["ltv"] = round((arpa_ending * gross_margin_pct) / dollar_churn_rate, 2)
        elif period_months == 12:
            row["ltv"] = None

        # Reconciliation residual: usually ~0. Non-zero mainly from a renewal
        # event firing in this period's LAST month, whose renewed contract's
        # go_live_month falls just outside the observation window — the
        # churn/expansion/contraction $ is counted here (it's a real event
        # that happened), but the resulting renewed ARR hasn't had time to
        # appear in ending_arr yet. Same boundary effect as late-signed
        # contracts elsewhere in this model — not a bridge error.
        row["other_boundary_effect"] = round(
            ending_arr - (beginning_arr + new_arr - contraction_arr - churned_arr + expansion_arr), 2
        )

        rows.append(row)

    return pd.DataFrame(rows)
