"""
Revenue Architecture Dashboard — Streamlit app
================================================
Single-scenario view, plus a Scenario A vs. B comparison mode with two
waterfall bridges (ARR and Revenue) explaining the gap between them.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from capacity_engine import PodConfig, RoleComp, MarketingFunnel, run_scenario
from revenue_recognition_engine import bookings_to_contracts, run_recognition, BillingFrequency
from renewal_engine import RenewalAssumptions, run_full_lifecycle, summarize_renewals
from existing_book_engine import load_customer_revenue_extract, derive_book_metrics, project_existing_book_runoff, derive_annual_history
from saas_metrics import aggregate_periods
from financial_model_export import generate_multi_pod_workbook_bytes

st.set_page_config(page_title="Revenue Architecture Model", layout="wide")
st.title("Revenue Architecture — Pipeline, Recognition & Renewal Model")
st.caption("Bowtie Model (Winning by Design) — deterministic, no randomization. Every number traces to an explicit input.")


# ---------------------------------------------------------------------------
# Reusable: transpose a df for display so months run left-to-right as
# columns, metrics as rows — matches how finance models are normally read,
# instead of the long/tidy format the engines compute in.
# ---------------------------------------------------------------------------
def wide(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0 or "month" not in df.columns:
        return df
    return df.set_index("month").T


# ---------------------------------------------------------------------------
# Formatting layer — every metric across every engine's output, mapped to
# how it should actually display (currency, percent, ratio/multiplier,
# or count). Applied to WIDE-format tables (metrics as rows) after
# transposing, so each row gets one consistent format across all its
# period columns. Unlisted fields (e.g. free-text like binding_constraint,
# pod_name) pass through as plain strings.
# ---------------------------------------------------------------------------
_CURRENCY_FIELDS = {
    "capacity_constrained_bookings", "demand_constrained_bookings", "theoretical_bookings", "actual_bookings",
    "ae_cost", "bdr_cost", "total_cost_of_capacity", "new_bookings_tcv", "new_arr_booked", "arpa_new_accounts",
    "cumulative_arr_booked", "blended_arpa_booked", "live_arr", "blended_arpa_live", "subscription_billings",
    "subscription_revenue_recognized", "ps_fee_billings", "ps_fee_revenue_recognized", "total_billings",
    "total_revenue_recognized", "cumulative_billings", "cumulative_revenue_recognized", "deferred_revenue_balance",
    "implementation_backlog_value", "arr_up_for_renewal", "churned_arr", "expansion_arr", "contraction_arr",
    "renewed_arr", "existing_book_arr", "existing_book_monthly_revenue", "existing_book_churn_dollar",
    "existing_book_expansion_dollar", "existing_book_contraction_dollar", "new_business_live_arr", "total_arr",
    "beginning_arr", "ending_arr", "revenue", "arpa_ending", "ltv", "other_boundary_effect",
}
_CURRENCY_PRECISE_FIELDS = {"cost_per_dollar_booked"}  # small $-per-$ figures, needs decimals not rounding to whole $
_PERCENT_FIELDS = {
    "overall_attainment_pct", "churn_rate_applied_pct", "nrr_this_cohort_pct", "nrr_pct",
    "gross_dollar_churn_rate_pct", "logo_churn_rate_pct",
}
_RATIO_FIELDS = {"execution_efficiency", "seasonal_multiplier", "pipeline_coverage_ratio", "coverage_target"}
_COUNT_FIELDS = {
    "active_aes", "active_bdrs", "new_accounts_signed", "cumulative_accounts_signed", "live_accounts",
    "implementation_backlog_count", "logos_up_for_renewal", "month", "customers_matched", "customers_churned",
    "base_logo_count",
}
_COUNT_DECIMAL_FIELDS = {  # counts that are legitimately fractional ("expected value", not a literal integer)
    "logos_retained_expected", "existing_book_logo_count", "existing_book_logos_churned", "beginning_logos",
    "ending_logos", "new_logos", "churned_logos", "sqls_marketing", "sqls_bdr", "sqls_ae_self_sourced",
}


def _format_cell(value, field_name: str) -> str:
    if pd.isna(value):
        return "—"
    if field_name in _CURRENCY_FIELDS:
        return f"${value:,.0f}"
    if field_name in _CURRENCY_PRECISE_FIELDS:
        return f"${value:,.3f}"
    if field_name in _PERCENT_FIELDS:
        return f"{value:.1f}%"
    if field_name in _RATIO_FIELDS:
        return f"{value:.2f}x"
    if field_name in _COUNT_FIELDS:
        return f"{value:,.0f}"
    if field_name in _COUNT_DECIMAL_FIELDS:
        return f"{value:,.1f}"
    return str(value)


_LABELS = {
    "month": "Month", "period": "Period",
    "active_aes": "Active AEs", "active_bdrs": "Active BDRs",
    "sqls_marketing": "SQLs — Marketing", "sqls_bdr": "SQLs — BDR", "sqls_ae_self_sourced": "SQLs — AE Self-Sourced",
    "capacity_constrained_bookings": "Capacity-Constrained Bookings", "demand_constrained_bookings": "Demand-Constrained Bookings",
    "theoretical_bookings": "Theoretical Bookings", "execution_efficiency": "Execution Efficiency",
    "seasonal_multiplier": "Seasonal Multiplier", "actual_bookings": "Actual Bookings",
    "overall_attainment_pct": "Attainment", "binding_constraint": "Binding Constraint",
    "pipeline_coverage_ratio": "Pipeline Coverage", "coverage_target": "Coverage Target",
    "ae_cost": "AE Cost", "bdr_cost": "BDR Cost", "total_cost_of_capacity": "Total Cost of Capacity",
    "cost_per_dollar_booked": "Cost per $ Booked",
    "new_bookings_tcv": "New Bookings (TCV)", "new_accounts_signed": "New Accounts Signed",
    "new_arr_booked": "New ARR", "arpa_new_accounts": "ARPA — New Accounts",
    "cumulative_accounts_signed": "Cumulative Accounts Signed", "cumulative_arr_booked": "Cumulative ARR Booked",
    "blended_arpa_booked": "Blended ARPA — Booked", "live_accounts": "Live Accounts", "live_arr": "ARR",
    "blended_arpa_live": "ARPA", "subscription_billings": "Subscription Billings",
    "subscription_revenue_recognized": "Subscription Revenue", "ps_fee_billings": "PS Fee Billings",
    "ps_fee_revenue_recognized": "PS Fee Revenue", "total_billings": "Total Billings",
    "total_revenue_recognized": "Total Revenue", "cumulative_billings": "Cumulative Billings",
    "cumulative_revenue_recognized": "Cumulative Revenue", "deferred_revenue_balance": "Deferred Revenue",
    "implementation_backlog_value": "Implementation Backlog ($)", "implementation_backlog_count": "Implementation Backlog (#)",
    "pod_name": "Pod", "logos_up_for_renewal": "Logos Up for Renewal", "arr_up_for_renewal": "ARR Up for Renewal",
    "churn_rate_applied_pct": "Churn Rate Applied", "churned_arr": "Churned ARR", "expansion_arr": "Expansion ARR",
    "contraction_arr": "Contraction ARR", "renewed_arr": "Renewed ARR", "logos_retained_expected": "Logos Retained (Expected)",
    "nrr_this_cohort_pct": "NRR — This Cohort",
    "existing_book_arr": "Existing Book ARR", "new_business_live_arr": "New Business ARR", "total_arr": "Total ARR",
    "existing_book_monthly_revenue": "Existing Book Revenue", "existing_book_churn_dollar": "Existing Book Churn ($)",
    "existing_book_expansion_dollar": "Existing Book Expansion ($)", "existing_book_contraction_dollar": "Existing Book Contraction ($)",
    "existing_book_logo_count": "Existing Book Customers", "existing_book_logos_churned": "Existing Book Customers Churned",
    "beginning_arr": "Beginning ARR", "ending_arr": "Ending ARR", "nrr_pct": "Net Revenue Retention (NRR)",
    "gross_dollar_churn_rate_pct": "Gross $ Churn Rate", "beginning_logos": "Beginning Customers",
    "ending_logos": "Ending Customers", "new_logos": "New Customers", "churned_logos": "Churned Customers",
    "logo_churn_rate_pct": "Logo Churn Rate", "revenue": "Revenue", "arpa_ending": "ARPA",
    "ltv": "Customer LTV", "other_boundary_effect": "Other / Boundary Effect",
}


def _relabel(name: str) -> str:
    return _LABELS.get(name, name.replace("_", " ").title())


def style_wide(df: pd.DataFrame, relabel: bool = True) -> pd.DataFrame:
    """Applies proper per-metric formatting to a WIDE table (metrics as rows,
    periods as columns) — the shape produced by wide() or .set_index('period').T."""
    if len(df) == 0:
        return df
    formatted = df.copy().astype(object)
    for row_label in formatted.index:
        formatted.loc[row_label] = formatted.loc[row_label].apply(lambda v: _format_cell(v, row_label))
    if relabel:
        formatted.index = [_relabel(name) for name in formatted.index]
    return formatted


# ---------------------------------------------------------------------------
# Sidebar input renderer — used for both single-scenario mode and each side
# of a comparison. `key` namespaces every widget so two instances can run
# side by side without Streamlit key collisions.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Segment presets — each one actually differs on the underlying economics,
# not just the label. Field names match the widget key suffixes used below
# exactly, so they can be injected straight into session_state.
# ---------------------------------------------------------------------------
_PRESET_DEFAULTS = {
    "SMB": dict(
        existing_aes=0, existing_bdrs=0, num_aes=4, num_bdrs=6, cadence=2,
        ae_base=60000, ae_var=60000, ae_quota=650000,
        bdr_base=50000, bdr_var=25000, bdr_sql=8,
        leads=1200, l2m=0.35, m2s=0.30, selfsrc=1.0,
        deal=6000, wm=0.28, wb=0.22, ws=0.30,
        term=12, lag=1, psfee=0.0, churn=0.15, exp=0.12, contr=0.04,
    ),
    "Mid-Market": dict(
        existing_aes=0, existing_bdrs=0, num_aes=3, num_bdrs=2, cadence=3,
        ae_base=95000, ae_var=95000, ae_quota=1100000,
        bdr_base=55000, bdr_var=30000, bdr_sql=6,
        leads=500, l2m=0.30, m2s=0.25, selfsrc=2.0,
        deal=18000, wm=0.25, wb=0.20, ws=0.35,
        term=12, lag=2, psfee=0.0, churn=0.12, exp=0.18, contr=0.03,
    ),
    "Enterprise": dict(
        existing_aes=0, existing_bdrs=0, num_aes=2, num_bdrs=3, cadence=4,
        ae_base=140000, ae_var=140000, ae_quota=1700000,
        bdr_base=65000, bdr_var=35000, bdr_sql=4,
        leads=150, l2m=0.25, m2s=0.35, selfsrc=1.5,
        deal=75000, wm=0.20, wb=0.15, ws=0.30,
        term=12, lag=4, psfee=0.10, churn=0.08, exp=0.20, contr=0.02,
    ),
    "Inbound": dict(
        existing_aes=0, existing_bdrs=0, num_aes=2, num_bdrs=0, cadence=3,
        ae_base=70000, ae_var=50000, ae_quota=600000,
        bdr_base=55000, bdr_var=30000, bdr_sql=6,  # unused — 0 BDRs on this segment
        leads=2500, l2m=0.45, m2s=0.35, selfsrc=0.0,
        deal=3500, wm=0.32, wb=0.0, ws=0.0,
        term=12, lag=1, psfee=0.0, churn=0.18, exp=0.10, contr=0.05,
    ),
}


_PRESET_SUFFIX_TO_CFG_FIELD = {
    "existing_aes": "num_existing_aes", "existing_bdrs": "num_existing_bdrs",
    "num_aes": "num_aes", "num_bdrs": "num_bdrs", "cadence": "hiring_cadence",
    "ae_base": "ae_base", "ae_var": "ae_variable", "ae_quota": "ae_quota",
    "bdr_base": "bdr_base", "bdr_var": "bdr_variable", "bdr_sql": "bdr_monthly_sql_quota",
    "leads": "monthly_leads", "l2m": "lead_to_mql", "m2s": "mql_to_sql", "selfsrc": "ae_self_sourced",
    "deal": "avg_deal_size", "wm": "win_marketing", "wb": "win_bdr", "ws": "win_self",
    "term": "contract_term", "lag": "implementation_lag", "psfee": "ps_fee_pct",
    "churn": "churn_rate", "exp": "expansion_rate", "contr": "contraction_rate",
}


def render_inputs(key: str, label: str) -> dict:
    st.sidebar.subheader(label)

    pod_preset = st.sidebar.selectbox(
        "Pod name", ["SMB", "Mid-Market", "Enterprise", "Inbound", "Other (custom)"],
        index=1, key=f"{key}_pod_preset",
    )

    # Detect a preset CHANGE and inject its defaults into session_state
    # *before* the affected widgets are created below — Streamlit widgets
    # read their initial value from session_state if already set, ignoring
    # the value= parameter in code once a key has been touched. Without
    # this, switching the dropdown only ever changed the pod_name label,
    # never the actual team/deal/rate assumptions underneath it.
    prev_key = f"{key}_applied_preset"
    if st.session_state.get(prev_key) != pod_preset and pod_preset in _PRESET_DEFAULTS:
        for suffix, val in _PRESET_DEFAULTS[pod_preset].items():
            st.session_state[f"{key}_{suffix}"] = val
        st.session_state[prev_key] = pod_preset

    if pod_preset == "Other (custom)":
        pod_name = st.sidebar.text_input("Custom pod name", "MidMarket", key=f"{key}_pod_name_custom")
    else:
        pod_name = pod_preset

    st.sidebar.caption("Team — Existing (already on the team, fully productive from month 1)")
    num_existing_aes = st.sidebar.number_input("Existing AEs", 0, 100, 0, key=f"{key}_existing_aes")
    num_existing_bdrs = st.sidebar.number_input("Existing BDRs", 0, 100, 0, key=f"{key}_existing_bdrs")

    st.sidebar.caption("Team — New Hires (ramp normally over 3 months)")
    num_aes = st.sidebar.number_input("New AE hires", 0, 50, 3, key=f"{key}_num_aes")
    num_bdrs = st.sidebar.number_input("New BDR hires", 0, 50, 2, key=f"{key}_num_bdrs")
    hiring_cadence = st.sidebar.number_input("Default hiring cadence (months between hires)", 1, 12, 3, key=f"{key}_cadence")

    custom_ae_schedule_raw = st.sidebar.text_input(
        "Custom AE hire-month schedule (optional, comma-separated)", "",
        key=f"{key}_ae_custom_sched",
        help=f"e.g. '0,0,6,6' to hire 2 now and 2 more in month 6. Leave blank to use the "
             f"default cadence above. Must have exactly {num_aes} entries if used.",
    )
    custom_bdr_schedule_raw = st.sidebar.text_input(
        "Custom BDR hire-month schedule (optional, comma-separated)", "",
        key=f"{key}_bdr_custom_sched",
        help=f"Same format as above. Must have exactly {num_bdrs} entries if used.",
    )

    ae_hire_months = None
    if custom_ae_schedule_raw.strip():
        try:
            ae_hire_months = [int(x.strip()) for x in custom_ae_schedule_raw.split(",")]
            if len(ae_hire_months) != num_aes:
                st.sidebar.error(f"Custom AE schedule has {len(ae_hire_months)} entries, need {num_aes}. Using default cadence instead.")
                ae_hire_months = None
        except ValueError:
            st.sidebar.error("Couldn't parse custom AE schedule (use whole numbers separated by commas). Using default cadence instead.")

    bdr_hire_months = None
    if custom_bdr_schedule_raw.strip():
        try:
            bdr_hire_months = [int(x.strip()) for x in custom_bdr_schedule_raw.split(",")]
            if len(bdr_hire_months) != num_bdrs:
                st.sidebar.error(f"Custom BDR schedule has {len(bdr_hire_months)} entries, need {num_bdrs}. Using default cadence instead.")
                bdr_hire_months = None
        except ValueError:
            st.sidebar.error("Couldn't parse custom BDR schedule (use whole numbers separated by commas). Using default cadence instead.")

    st.sidebar.caption("AE Compensation & Quota")
    ae_base = st.sidebar.number_input("AE annual base ($)", 0, 500_000, 95_000, step=5000, key=f"{key}_ae_base")
    ae_variable = st.sidebar.number_input("AE annual variable @ 100% ($)", 0, 500_000, 95_000, step=5000, key=f"{key}_ae_var")
    ae_quota = st.sidebar.number_input("AE annual quota ($)", 0, 5_000_000, 1_100_000, step=50_000, key=f"{key}_ae_quota")

    st.sidebar.caption("BDR Compensation & Quota")
    bdr_base = st.sidebar.number_input("BDR annual base ($)", 0, 300_000, 55_000, step=5000, key=f"{key}_bdr_base")
    bdr_variable = st.sidebar.number_input("BDR annual variable @ 100% ($)", 0, 300_000, 30_000, step=5000, key=f"{key}_bdr_var")
    bdr_monthly_sql_quota = st.sidebar.number_input("BDR monthly SQL quota", 0, 50, 6, key=f"{key}_bdr_sql")

    st.sidebar.caption("Demand")
    monthly_leads = st.sidebar.number_input("Marketing leads/month", 0, 20_000, 500, key=f"{key}_leads")
    lead_to_mql = st.sidebar.slider("Lead → MQL rate", 0.0, 1.0, 0.30, key=f"{key}_l2m")
    mql_to_sql = st.sidebar.slider("MQL → SQL rate", 0.0, 1.0, 0.25, key=f"{key}_m2s")
    ae_self_sourced = st.sidebar.number_input("AE self-sourced SQLs/month", 0.0, 20.0, 2.0, key=f"{key}_selfsrc")

    st.sidebar.caption("Deal Economics")
    avg_deal_size = st.sidebar.number_input("Avg deal size — TCV ($)", 0, 5_000_000, 18_000, step=1000, key=f"{key}_deal")
    win_marketing = st.sidebar.slider("Win rate — marketing", 0.0, 1.0, 0.25, key=f"{key}_wm")
    win_bdr = st.sidebar.slider("Win rate — BDR", 0.0, 1.0, 0.20, key=f"{key}_wb")
    win_self = st.sidebar.slider("Win rate — self-sourced", 0.0, 1.0, 0.35, key=f"{key}_ws")

    st.sidebar.caption("Execution")
    execution_efficiency = st.sidebar.slider("Execution efficiency", 0.0, 1.5, 1.0, key=f"{key}_exec")

    st.sidebar.caption("Contract & Revenue Recognition")
    contract_term = st.sidebar.number_input("Contract term (months)", 1, 60, 12, key=f"{key}_term")
    implementation_lag = st.sidebar.number_input("Implementation lag (months)", 0, 24, 2, key=f"{key}_lag")
    ps_fee_pct = st.sidebar.slider("Professional services fee (% of ARR)", 0.0, 0.5, 0.0, key=f"{key}_psfee")

    st.sidebar.caption("Renewal Assumptions")
    churn_rate = st.sidebar.slider("Annual gross revenue churn", 0.0, 1.0, 0.12, key=f"{key}_churn")
    expansion_rate = st.sidebar.slider("Annual expansion rate", 0.0, 1.0, 0.18, key=f"{key}_exp")
    contraction_rate = st.sidebar.slider("Annual contraction rate", 0.0, 1.0, 0.03, key=f"{key}_contr")

    use_seasonality = st.sidebar.checkbox("Apply seasonal pattern", value=False, key=f"{key}_useseason")
    seasonality_pattern = None
    if use_seasonality:
        months_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        seasonality_pattern = [
            st.sidebar.slider(months_labels[i], 0.0, 2.0, 1.0, key=f"{key}_season_{i}") for i in range(12)
        ]

    return dict(
        pod_name=pod_name, num_aes=num_aes, num_bdrs=num_bdrs, hiring_cadence=hiring_cadence,
        num_existing_aes=num_existing_aes, num_existing_bdrs=num_existing_bdrs,
        ae_hire_months=ae_hire_months, bdr_hire_months=bdr_hire_months,
        ae_base=ae_base, ae_variable=ae_variable, ae_quota=ae_quota,
        bdr_base=bdr_base, bdr_variable=bdr_variable, bdr_monthly_sql_quota=bdr_monthly_sql_quota,
        monthly_leads=monthly_leads, lead_to_mql=lead_to_mql, mql_to_sql=mql_to_sql,
        ae_self_sourced=ae_self_sourced, avg_deal_size=avg_deal_size,
        win_marketing=win_marketing, win_bdr=win_bdr, win_self=win_self,
        execution_efficiency=execution_efficiency, contract_term=contract_term,
        implementation_lag=implementation_lag, ps_fee_pct=ps_fee_pct,
        churn_rate=churn_rate, expansion_rate=expansion_rate, contraction_rate=contraction_rate,
        seasonality_pattern=seasonality_pattern,
    )


# ---------------------------------------------------------------------------
# Runs all three phases for one config dict. Returns everything needed for
# display AND for cross-scenario bridging (all_contracts is needed for the
# origin-split revenue bridge).
# ---------------------------------------------------------------------------
def run_full_model(cfg: dict, num_months: int):
    pod = PodConfig(
        pod_name=cfg["pod_name"], num_aes=int(cfg["num_aes"]), num_bdrs=int(cfg["num_bdrs"]),
        num_existing_aes=int(cfg["num_existing_aes"]), num_existing_bdrs=int(cfg["num_existing_bdrs"]),
        ae_comp_template=RoleComp(annual_base=cfg["ae_base"], annual_variable_at_100pct=cfg["ae_variable"], annual_quota=cfg["ae_quota"]),
        bdr_comp_template=RoleComp(annual_base=cfg["bdr_base"], annual_variable_at_100pct=cfg["bdr_variable"],
                                    annual_quota=cfg["bdr_monthly_sql_quota"] * 12) if (cfg["num_bdrs"] > 0 or cfg["num_existing_bdrs"] > 0) else None,
        marketing=MarketingFunnel(monthly_leads=cfg["monthly_leads"], lead_to_mql_rate=cfg["lead_to_mql"], mql_to_sql_rate=cfg["mql_to_sql"]),
        avg_deal_size=cfg["avg_deal_size"], win_rate_marketing_sourced=cfg["win_marketing"],
        win_rate_bdr_sourced=cfg["win_bdr"], win_rate_ae_self_sourced=cfg["win_self"],
        ae_self_sourced_sqls_per_month=cfg["ae_self_sourced"], execution_efficiency=cfg["execution_efficiency"],
        hiring_cadence_months=int(cfg["hiring_cadence"]), contract_term_months=int(cfg["contract_term"]),
        implementation_lag_months=int(cfg["implementation_lag"]), professional_services_fee_pct_of_arr=cfg["ps_fee_pct"],
        seasonality_pattern=cfg["seasonality_pattern"],
        ae_hire_months=cfg.get("ae_hire_months"), bdr_hire_months=cfg.get("bdr_hire_months"),
    )
    phase1_df = run_scenario(pod.build_scenario(num_months))
    initial_contracts = bookings_to_contracts(pod, phase1_df, billing_frequency=BillingFrequency.ANNUAL_UPFRONT)
    assumptions = {cfg["pod_name"]: RenewalAssumptions(
        pod_name=cfg["pod_name"], gross_revenue_churn_rate_annual=cfg["churn_rate"],
        expansion_rate_annual=cfg["expansion_rate"], contraction_rate_annual=cfg["contraction_rate"],
    )}
    all_contracts, renewals_df, phase2_df = run_full_lifecycle(initial_contracts, assumptions, num_months)
    return dict(pod=pod, phase1_df=phase1_df, phase2_df=phase2_df, renewals_df=renewals_df, all_contracts=all_contracts)


def revenue_by_origin(contracts: list, num_months: int) -> dict:
    """Exact partition of cumulative recognized revenue: new-origin subscription,
    renewal-origin subscription, and PS fees (always new-origin in practice,
    since renewal contracts carry no PS fee — you don't re-charge implementation
    on a renewal). These three sum exactly to total revenue recognized."""
    sub_new = sub_renewal = ps_fee = 0.0
    for month in range(num_months):
        for c in contracts:
            rev = c.revenue_recognized_in(month)
            if c.origin == "new":
                sub_new += rev
            else:
                sub_renewal += rev
            ps_fee += c.ps_fee_revenue_recognized_in(month)
    return {"subscription_new": sub_new, "subscription_renewal": sub_renewal, "ps_fee": ps_fee}


def make_waterfall(labels, values, title, measure=None):
    if measure is None:
        measure = ["absolute"] + ["relative"] * (len(values) - 2) + ["total"]
    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measure,
        connector={"line": {"color": "rgba(120,120,120,0.4)"}},
        increasing={"marker": {"color": "#2ca02c"}},
        decreasing={"marker": {"color": "#d62728"}},
        totals={"marker": {"color": "#1f77b4"}},
    ))
    fig.update_layout(title=title, showlegend=False, height=420, margin=dict(t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# MODE SELECTOR
# ---------------------------------------------------------------------------
mode = st.radio("Mode", ["Single Scenario", "Compare Two Scenarios"], horizontal=True)
num_months = st.slider("Scenario length (months)", 6, 48, 24)

# ===========================================================================
# SINGLE SCENARIO MODE
# ===========================================================================
if mode == "Single Scenario":
    cfg = render_inputs("s", "Scenario Inputs")

    # -----------------------------------------------------------------
    # EXISTING CUSTOMER BOOK (optional) — top-line ARR/revenue overlay,
    # NOT run through the Contract engine (no individual contract dates
    # available from a revenue extract). Runs alongside new business.
    # -----------------------------------------------------------------
    st.sidebar.subheader("Existing Customer Book (optional)")
    include_existing = st.sidebar.checkbox("Include existing customer book", value=False)

    existing_book_df = None
    derived_metrics = None
    historical_annual = None

    if include_existing:
        uploaded = st.sidebar.file_uploader("Upload customer revenue extract (CSV or Excel)", type=["csv", "xlsx"])
        st.sidebar.caption("Long format expected: one row per customer per month (customer, month, revenue). "
                            "At least 13 months of history needed to derive a trailing-12-month comparison.")

        if uploaded is not None:
            try:
                raw_df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
            except Exception as e:
                st.sidebar.error(f"Couldn't read file: {e}")
                raw_df = None

            if raw_df is not None:
                st.sidebar.caption("Map your columns:")
                cols = list(raw_df.columns)
                customer_col = st.sidebar.selectbox("Customer column", cols, index=0)
                month_col = st.sidebar.selectbox("Month column", cols, index=min(1, len(cols) - 1))
                revenue_col = st.sidebar.selectbox("Revenue column", cols, index=min(2, len(cols) - 1))
                lookback = st.sidebar.number_input("Lookback window (months)", 1, 24, 12)

                try:
                    matrix = load_customer_revenue_extract(raw_df, customer_col, month_col, revenue_col)
                    derived_metrics = derive_book_metrics(matrix, lookback_months=lookback)
                except Exception as e:
                    st.sidebar.error(f"Couldn't derive metrics: {e}")
                    derived_metrics = None

                if derived_metrics is not None:
                    st.sidebar.success(
                        f"Derived NRR: {derived_metrics.nrr_pct}% "
                        f"({derived_metrics.customers_matched} matched, {derived_metrics.customers_churned} churned)"
                    )
                    historical_annual = derive_annual_history(matrix)

                    override = st.sidebar.checkbox("Override derived rates manually", value=False)
                    if override:
                        eb_churn = st.sidebar.slider("Existing book — annual churn", 0.0, 1.0, derived_metrics.implied_annual_churn_rate or 0.10)
                        eb_expansion = st.sidebar.slider("Existing book — annual expansion", 0.0, 1.0, derived_metrics.implied_annual_expansion_rate or 0.10)
                        eb_contraction = st.sidebar.slider("Existing book — annual contraction", 0.0, 1.0, derived_metrics.implied_annual_contraction_rate or 0.02)
                    else:
                        eb_churn = derived_metrics.implied_annual_churn_rate or 0.0
                        eb_expansion = derived_metrics.implied_annual_expansion_rate or 0.0
                        eb_contraction = derived_metrics.implied_annual_contraction_rate or 0.0

                    existing_book_df = project_existing_book_runoff(
                        base_arr=derived_metrics.base_arr,
                        annual_churn_rate=eb_churn,
                        annual_expansion_rate=eb_expansion,
                        annual_contraction_rate=eb_contraction,
                        num_months=num_months,
                        base_logo_count=derived_metrics.base_logo_count,
                    )

    st.sidebar.subheader("SaaS Metrics Dashboard")
    gross_margin_pct = st.sidebar.slider("Gross margin % (for LTV)", 0.0, 1.0, 0.75)

    try:
        result = run_full_model(cfg, num_months)
    except Exception as e:
        st.error(f"Model error: {e}")
        st.stop()

    phase1_df, phase2_df, renewals_df = result["phase1_df"], result["phase2_df"], result["renewals_df"]

    eb_base_arr = derived_metrics.base_arr if derived_metrics is not None else 0.0
    eb_base_logos = derived_metrics.base_logo_count if derived_metrics is not None else 0

    tab_names = ["📐 SaaS Metrics Dashboard", "📈 Pipeline & Capacity", "💰 Revenue Recognition", "🔄 Renewals & NRR"]
    if existing_book_df is not None:
        tab_names.insert(1, "🏢 Total Company")
    tabs = st.tabs(tab_names)
    tab_offset = 1  # SaaS Metrics Dashboard is always tab 0 now
    if existing_book_df is not None:
        tab_offset = 2

    with tabs[0]:
        annual = aggregate_periods(
            phase2_df, renewals_df, existing_book_df, result["all_contracts"], num_months,
            period_months=12, gross_margin_pct=gross_margin_pct,
            existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
        )
        annual["type"] = "Forecast"

        if historical_annual is not None and len(historical_annual) > 0:
            combined_annual = pd.concat([historical_annual, annual], ignore_index=True)
        else:
            combined_annual = annual

        latest = combined_annual.iloc[-1]
        prior = combined_annual.iloc[-2] if len(combined_annual) > 1 else None

        def _delta(field):
            if prior is None or prior[field] in (None, 0):
                return None
            return latest[field] - prior[field]

        st.subheader(f"{cfg['pod_name']} — {latest['period']}")
        if historical_annual is not None and len(historical_annual) > 0:
            st.caption(f"Showing {len(historical_annual)} year(s) of actuals from your extract, "
                       f"continuing into {len(annual)} year(s) of forecast.")

        with st.expander("📥 Download as financial model (Excel — multi-segment)"):
            st.caption(
                "Real formulas, not pasted values — auditable in Excel, shareable with bankers/investors/corp dev. "
                "One Capacity + Revenue sheet pair per segment, plus a consolidated Summary with per-segment "
                "columns AND a Total Company column that sums across them — a real multi-segment model, not "
                "just one team. Not included: professional services fees, seasonality, Existing Book overlay. "
                "Annual summary covers full years only."
            )
            other_presets = [p for p in _PRESET_DEFAULTS.keys() if p != cfg["pod_name"]]
            additional = st.multiselect(
                f"Add other standard segments alongside '{cfg['pod_name']}' (currently configured in the sidebar)",
                other_presets, default=other_presets,
            )
            try:
                cfg_list = [cfg]
                for preset_name in additional:
                    preset_cfg = dict(cfg)  # inherit shared settings (execution_efficiency, seasonality=None, etc.)
                    mapped = {_PRESET_SUFFIX_TO_CFG_FIELD[k]: v for k, v in _PRESET_DEFAULTS[preset_name].items()}
                    preset_cfg.update(mapped)
                    preset_cfg["pod_name"] = preset_name
                    preset_cfg["ae_hire_months"] = None
                    preset_cfg["bdr_hire_months"] = None
                    cfg_list.append(preset_cfg)

                xlsx_bytes = generate_multi_pod_workbook_bytes(cfg_list, num_months)
                segment_names = ", ".join(c["pod_name"] for c in cfg_list)
                st.caption(f"This export covers: {segment_names}")
                st.download_button(
                    "Download financial_model.xlsx",
                    data=xlsx_bytes,
                    file_name="company_financial_model.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.error(f"Couldn't generate the workbook: {e}")

        c1, c2, c3, c4, c5 = st.columns(5)
        arr_growth_pct = ((latest["ending_arr"] / prior["ending_arr"]) - 1) * 100 if prior is not None and prior["ending_arr"] else None
        c1.metric("ARR", f"${latest['ending_arr']:,.0f}",
                   delta=f"{arr_growth_pct:.1f}% YoY" if arr_growth_pct is not None else None)
        c2.metric("Net Revenue Retention", f"{latest['nrr_pct']:.1f}%" if latest["nrr_pct"] is not None else "—",
                   delta=_delta("nrr_pct"), delta_color="normal")
        grr = 100 - latest["gross_dollar_churn_rate_pct"] if latest["gross_dollar_churn_rate_pct"] is not None else None
        c3.metric("Gross Revenue Retention", f"{grr:.1f}%" if grr is not None else "—")
        c4.metric("Logo Churn Rate", f"{latest['logo_churn_rate_pct']:.1f}%" if latest["logo_churn_rate_pct"] is not None else "—",
                   delta=_delta("logo_churn_rate_pct"), delta_color="inverse")
        c5.metric("Customer LTV", f"${latest['ltv']:,.0f}" if latest["ltv"] is not None else "—")

        st.divider()

        if len(combined_annual) > 1:
            st.caption("ARR — Actuals → Forecast")
            arr_fig = go.Figure()
            actual_rows = combined_annual[combined_annual["type"] == "Actual"]
            forecast_rows = combined_annual[combined_annual["type"] == "Forecast"]
            if len(actual_rows) > 0:
                arr_fig.add_trace(go.Bar(x=actual_rows["period"], y=actual_rows["ending_arr"],
                                          name="Actual", marker_color="#1f77b4"))
            if len(forecast_rows) > 0:
                arr_fig.add_trace(go.Bar(x=forecast_rows["period"], y=forecast_rows["ending_arr"],
                                          name="Forecast", marker_color="#aec7e8"))
            arr_fig.update_layout(showlegend=True, height=320, margin=dict(t=20, b=20))
            st.plotly_chart(arr_fig, use_container_width=True)

        st.caption(f"ARR Bridge — {latest['period']}")
        wf_labels = ["Beginning<br>ARR", "New<br>Business", "Expansion", "Contraction", "Churn", "Other /<br>Boundary", "Ending<br>ARR"]
        wf_values = [latest["beginning_arr"], latest["new_arr_booked"], latest["expansion_arr"],
                     -latest["contraction_arr"], -latest["churned_arr"], latest["other_boundary_effect"], latest["ending_arr"]]
        st.plotly_chart(make_waterfall(wf_labels, wf_values, ""), use_container_width=True)

        with st.expander("View underlying data"):
            st.caption(
                "'New ARR' is ARR that went LIVE this period (by go-live date), not ARR signed — "
                "those differ once implementation lag is involved. LTV is annual-only: a single "
                "quarter's churn rate is too noisy to use as an LTV input. Historical actual years "
                "have no LTV (gross margin isn't in a revenue extract) and the earliest actual year "
                "has no NRR/churn (no prior-year baseline to compare against)."
            )
            st.markdown("**Annual (Actual + Forecast)**")
            st.dataframe(style_wide(combined_annual.set_index("period").T), use_container_width=True)


            st.markdown("**Quarterly**")
            quarterly = aggregate_periods(
                phase2_df, renewals_df, existing_book_df, result["all_contracts"], num_months,
                period_months=3, existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
            )
            num_years = (num_months + 11) // 12
            for y in range(num_years):
                year_quarters = quarterly[quarterly["period"].str.startswith(f"Y{y+1}-")]
                if len(year_quarters) > 0:
                    st.markdown(f"*Year {y+1}*")
                    st.dataframe(style_wide(year_quarters.set_index("period").T), use_container_width=True)

    if existing_book_df is not None:
        with tabs[1]:
            combined = pd.DataFrame({
                "month": phase2_df["month"],
                "existing_book_arr": existing_book_df["existing_book_arr"],
                "new_business_live_arr": phase2_df["live_arr"],
            })
            combined["total_arr"] = combined["existing_book_arr"] + combined["new_business_live_arr"]

            c1, c2, c3 = st.columns(3)
            c1.metric("Existing Book — Ending ARR", f"${existing_book_df['existing_book_arr'].iloc[-1]:,.0f}")
            c2.metric("New Business — Ending ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
            c3.metric("Total Company — Ending ARR", f"${combined['total_arr'].iloc[-1]:,.0f}")
            st.line_chart(combined.set_index("month")[["existing_book_arr", "new_business_live_arr", "total_arr"]])

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Extract — Base ARR", f"${derived_metrics.base_arr:,.0f}")
            d2.metric("Extract — Trailing-12 NRR", f"{derived_metrics.nrr_pct}%")
            d3.metric("Extract — Churned ARR (TTM)", f"${derived_metrics.churned_arr:,.0f}")
            d4.metric("Extract — Expansion ARR (TTM)", f"${derived_metrics.expansion_arr:,.0f}")

            with st.expander("View underlying data"):
                st.caption(
                    "Existing book is a top-line ARR/revenue overlay derived from your uploaded extract "
                    "(smooth monthly runoff, no individual contract dates). New business runs through the "
                    "full Bowtie engine (Phase 1-3) with real deferred revenue mechanics."
                )
                st.dataframe(style_wide(wide(combined)), use_container_width=True)

    with tabs[0 + tab_offset]:
        st.subheader("Bookings: Capacity vs. Demand Constraint")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Bookings", f"${phase1_df['actual_bookings'].sum():,.0f}")
        col2.metric("Total Cost of Capacity", f"${phase1_df['total_cost_of_capacity'].sum():,.0f}")
        months_capacity_bound = (phase1_df["binding_constraint"] == "CAPACITY").sum()
        col3.metric("Months Capacity-Bound", f"{months_capacity_bound}/{len(phase1_df)}")
        st.line_chart(phase1_df.set_index("month")[["capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings"]])

        with st.expander("View underlying data"):
            st.dataframe(style_wide(wide(phase1_df)), use_container_width=True)

    with tabs[1 + tab_offset]:
        st.subheader("Live ARR Trajectory")
        col1, col2, col3 = st.columns(3)
        col1.metric("Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
        col2.metric("Ending Deferred Revenue", f"${phase2_df['deferred_revenue_balance'].iloc[-1]:,.0f}")
        col3.metric("Ending Live Accounts", f"{int(phase2_df['live_accounts'].iloc[-1])}")
        st.line_chart(phase2_df.set_index("month")[["live_arr", "cumulative_arr_booked"]])
        st.subheader("Revenue Streams")
        st.bar_chart(phase2_df.set_index("month")[["subscription_revenue_recognized", "ps_fee_revenue_recognized"]])

        with st.expander("View underlying data"):
            st.dataframe(style_wide(wide(phase2_df)), use_container_width=True)

    with tabs[2 + tab_offset]:
        st.subheader("Renewal Cohort Summary")
        if len(renewals_df) > 0:
            summary = summarize_renewals(renewals_df)
            col1, col2, col3 = st.columns(3)
            col1.metric("Blended NRR", f"{summary['blended_nrr_pct']}%")
            col2.metric("Total Renewal Events", summary['total_renewal_events'])
            col3.metric("Total Expansion ARR", f"${summary['total_expansion_arr']:,.0f}")
            st.info(summary["nrr_benchmark_check"])
            with st.expander("View underlying data"):
                st.dataframe(style_wide(wide(renewals_df)), use_container_width=True)
        else:
            st.info("No renewal events occurred — scenario length may be shorter than the contract term.")

# ===========================================================================
# COMPARE TWO SCENARIOS MODE
# ===========================================================================
else:
    with st.sidebar.expander("Scenario A", expanded=True):
        cfg_a = render_inputs("a", "Scenario A Inputs")
    with st.sidebar.expander("Scenario B", expanded=True):
        cfg_b = render_inputs("b", "Scenario B Inputs")

    try:
        result_a = run_full_model(cfg_a, num_months)
        result_b = run_full_model(cfg_b, num_months)
    except Exception as e:
        st.error(f"Model error: {e}")
        st.stop()

    p2a, p2b = result_a["phase2_df"], result_b["phase2_df"]
    rna, rnb = result_a["renewals_df"], result_b["renewals_df"]

    tab1, tab2, tab3 = st.tabs(["📊 KPI Comparison", "🌉 ARR & Revenue Bridges", "📋 Raw Data"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Scenario A")
            st.metric("Ending Live ARR", f"${p2a['live_arr'].iloc[-1]:,.0f}")
            st.metric("Total Revenue Recognized", f"${p2a['total_revenue_recognized'].sum():,.0f}")
            st.metric("Ending Deferred Revenue", f"${p2a['deferred_revenue_balance'].iloc[-1]:,.0f}")
        with col2:
            st.subheader("Scenario B")
            st.metric("Ending Live ARR", f"${p2b['live_arr'].iloc[-1]:,.0f}",
                       delta=f"${p2b['live_arr'].iloc[-1] - p2a['live_arr'].iloc[-1]:,.0f}")
            st.metric("Total Revenue Recognized", f"${p2b['total_revenue_recognized'].sum():,.0f}",
                       delta=f"${p2b['total_revenue_recognized'].sum() - p2a['total_revenue_recognized'].sum():,.0f}")
            st.metric("Ending Deferred Revenue", f"${p2b['deferred_revenue_balance'].iloc[-1]:,.0f}",
                       delta=f"${p2b['deferred_revenue_balance'].iloc[-1] - p2a['deferred_revenue_balance'].iloc[-1]:,.0f}")

    with tab2:
        st.subheader("ARR Bridge: Scenario A → Scenario B")
        st.caption(
            "Decomposed using each scenario's own cumulative New Business / Expansion / "
            "Contraction / Churn totals. This is an additive approximation, not a controlled "
            "marginal attribution — cascading renewal timing across months creates real "
            "interaction effects between drivers, shown explicitly as 'Other / interaction' "
            "below rather than hidden or forced to zero."
        )
        start_arr = p2a["live_arr"].iloc[-1]
        end_arr = p2b["live_arr"].iloc[-1]
        d_new = p2b["new_arr_booked"].sum() - p2a["new_arr_booked"].sum()
        d_exp = (rnb["expansion_arr"].sum() if len(rnb) else 0) - (rna["expansion_arr"].sum() if len(rna) else 0)
        d_contr = -((rnb["contraction_arr"].sum() if len(rnb) else 0) - (rna["contraction_arr"].sum() if len(rna) else 0))
        d_churn = -((rnb["churned_arr"].sum() if len(rnb) else 0) - (rna["churned_arr"].sum() if len(rna) else 0))
        other = end_arr - (start_arr + d_new + d_exp + d_contr + d_churn)

        fig_arr = make_waterfall(
            ["Scenario A<br>Ending ARR", "Δ New Business", "Δ Expansion", "Δ Contraction", "Δ Churn", "Other /<br>Interaction", "Scenario B<br>Ending ARR"],
            [start_arr, d_new, d_exp, d_contr, d_churn, other, end_arr],
            "ARR Bridge",
        )
        st.plotly_chart(fig_arr, use_container_width=True)

        st.divider()
        st.subheader("Revenue Bridge: Scenario A → Scenario B")
        st.caption(
            "Cumulative total revenue recognized over the full window, decomposed by origin "
            "(new-business subscription vs. renewal-driven subscription) plus professional "
            "services fees. This is an EXACT partition — the three buckets sum exactly to "
            "total revenue recognized, no residual needed."
        )
        rev_a = revenue_by_origin(result_a["all_contracts"], num_months)
        rev_b = revenue_by_origin(result_b["all_contracts"], num_months)
        start_rev = sum(rev_a.values())
        end_rev = sum(rev_b.values())
        d_sub_new = rev_b["subscription_new"] - rev_a["subscription_new"]
        d_sub_renewal = rev_b["subscription_renewal"] - rev_a["subscription_renewal"]
        d_ps = rev_b["ps_fee"] - rev_a["ps_fee"]

        fig_rev = make_waterfall(
            ["Scenario A<br>Total Revenue", "Δ New-Business<br>Subscription", "Δ Renewal-Driven<br>Subscription", "Δ PS Fees", "Scenario B<br>Total Revenue"],
            [start_rev, d_sub_new, d_sub_renewal, d_ps, end_rev],
            "Revenue Bridge",
        )
        st.plotly_chart(fig_rev, use_container_width=True)

    with tab3:
        st.caption("Tables shown with months as columns, metrics as rows.")
        st.subheader("Scenario A — Phase 2 Output")
        st.dataframe(style_wide(wide(p2a)), use_container_width=True)
        st.subheader("Scenario B — Phase 2 Output")
        st.dataframe(style_wide(wide(p2b)), use_container_width=True)

st.caption("Built on the Bowtie Model (Winning by Design). All math is deterministic — no randomized variables anywhere in this model.")
