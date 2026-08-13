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

# Tighter number inputs — Streamlit stretches them to fill their column,
# which looks bulky once columns are wide (desktop, 4-6 per row). Caps
# width so short numbers don't sit in a lot of empty box.
st.markdown("""
<style>
    div[data-testid="stNumberInput"] input { max-width: 110px; }
    div[data-testid="stNumberInput"] { max-width: 150px; }
    div[data-testid="stSelectbox"] { max-width: 260px; }
</style>
""", unsafe_allow_html=True)

st.title("Revenue Architecture — Pipeline, Recognition & Renewal Model")
st.caption("Bowtie Model (Winning by Design) — deterministic, no randomization. Every number traces to an explicit input.")
st.caption("Model how GTM capacity, pipeline, implementation timing and customer retention translate into ARR and recognized revenue. Start by selecting a segment and adjusting the assumptions below.")


# ---------------------------------------------------------------------------
# Reusable: transpose a df for display so months run left-to-right as
# columns, metrics as rows — matches how finance models are normally read,
# instead of the long/tidy format the engines compute in.
# ---------------------------------------------------------------------------
def wide(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0 or "month" not in df.columns:
        return df
    transposed = df.set_index("month").T
    transposed.columns = [f"M{c}" for c in transposed.columns]
    return transposed


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
    "ae_cost", "bdr_cost", "total_cost_of_capacity", "new_bookings_tcv", "new_arr_booked", "new_arr_live", "arpa_new_accounts",
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
    "capacity_constrained_bookings": "Capacity-Constrained Bookings (TCV)", "demand_constrained_bookings": "Demand-Constrained Bookings (TCV)",
    "theoretical_bookings": "Theoretical Bookings (TCV)", "execution_efficiency": "Execution Efficiency",
    "seasonal_multiplier": "Seasonal Multiplier", "actual_bookings": "Actual Bookings (TCV)",
    "overall_attainment_pct": "Attainment", "binding_constraint": "Binding Constraint",
    "pipeline_coverage_ratio": "Pipeline Coverage", "coverage_target": "Coverage Target",
    "ae_cost": "AE Cost", "bdr_cost": "BDR Cost", "total_cost_of_capacity": "Total Cost of Capacity",
    "cost_per_dollar_booked": "Cost per $ Booked",
    "new_bookings_tcv": "New Bookings (TCV)", "new_accounts_signed": "New Accounts Signed",
    # "new_arr_booked" is genuinely signed-date-based here (Phase 2 output —
    # revenue_recognition_engine.py, c.signed_month == month). The SAME field
    # name is reused in saas_metrics.py's annual/quarterly rollup for a
    # go-live-date-based figure instead — a real naming collision across two
    # dataframes. That one is renamed to "new_arr_live" locally in app.py
    # (see aggregate_periods() call sites) precisely so it doesn't share this
    # label and get misread as booking-date-based.
    "new_arr_booked": "New ARR Booked (Signed)", "new_arr_live": "New ARR (Went Live)",
    "arpa_new_accounts": "ARPA — New Accounts",
    "cumulative_accounts_signed": "Cumulative Accounts Signed", "cumulative_arr_booked": "Cumulative ARR Booked",
    "blended_arpa_booked": "Blended ARPA — Booked", "live_accounts": "Live Accounts", "live_arr": "Live ARR",
    "blended_arpa_live": "ARPA (Live)", "subscription_billings": "Subscription Billings",
    "subscription_revenue_recognized": "Subscription Revenue Recognized", "ps_fee_billings": "PS Fee Billings",
    "ps_fee_revenue_recognized": "PS Fee Revenue Recognized", "total_billings": "Total Billings",
    "total_revenue_recognized": "Total Revenue Recognized", "cumulative_billings": "Cumulative Billings",
    "cumulative_revenue_recognized": "Cumulative Revenue Recognized", "deferred_revenue_balance": "Deferred Revenue",
    "implementation_backlog_value": "Implementation Backlog ($)", "implementation_backlog_count": "Implementation Backlog (#)",
    "pod_name": "Pod", "logos_up_for_renewal": "Logos Up for Renewal", "arr_up_for_renewal": "ARR Up for Renewal",
    "churn_rate_applied_pct": "Churn Rate Applied", "churned_arr": "Churned ARR", "expansion_arr": "Expansion ARR",
    "contraction_arr": "Contraction ARR", "renewed_arr": "Renewed ARR", "logos_retained_expected": "Logos Retained (Expected)",
    "nrr_this_cohort_pct": "NRR — This Cohort",
    "existing_book_arr": "Existing Book ARR", "new_business_live_arr": "New Business ARR (Live)", "total_arr": "Total ARR",
    "existing_book_monthly_revenue": "Existing Book Revenue", "existing_book_churn_dollar": "Existing Book Churn ($)",
    "existing_book_expansion_dollar": "Existing Book Expansion ($)", "existing_book_contraction_dollar": "Existing Book Contraction ($)",
    "existing_book_logo_count": "Existing Book Customers", "existing_book_logos_churned": "Existing Book Customers Churned",
    "beginning_arr": "Beginning ARR", "ending_arr": "Ending ARR", "nrr_pct": "Net Revenue Retention (NRR)",
    "gross_dollar_churn_rate_pct": "Gross $ Churn Rate", "beginning_logos": "Beginning Customers",
    "ending_logos": "Ending Customers", "new_logos": "New Customers", "churned_logos": "Churned Customers",
    "logo_churn_rate_pct": "Logo Churn Rate", "revenue": "Recognized Revenue", "arpa_ending": "ARPA",
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
        ae_quota_m=0.65, bdr_sql=8,
        marketing_sqls=126.0, selfsrc=1.0,  # was leads=1200*0.35*0.30 — preserved effective SQL output
        deal=6000, wm=0.28, wb=0.22, ws=0.30,
        term=12, lag=1, psfee=0.0, churn=0.15, exp=0.12, contr=0.04,
    ),
    "Mid-Market": dict(
        existing_aes=0, existing_bdrs=0, num_aes=3, num_bdrs=2, cadence=3,
        ae_quota_m=1.1, bdr_sql=6,
        marketing_sqls=37.5, selfsrc=2.0,  # was leads=500*0.30*0.25
        deal=18000, wm=0.25, wb=0.20, ws=0.35,
        term=12, lag=2, psfee=0.0, churn=0.12, exp=0.18, contr=0.03,
    ),
    "Enterprise": dict(
        existing_aes=0, existing_bdrs=0, num_aes=2, num_bdrs=3, cadence=4,
        ae_quota_m=1.7, bdr_sql=4,
        marketing_sqls=13.1, selfsrc=1.5,  # was leads=150*0.25*0.35
        deal=75000, wm=0.20, wb=0.15, ws=0.30,
        term=12, lag=4, psfee=0.10, churn=0.08, exp=0.20, contr=0.02,
    ),
    "Inbound": dict(
        existing_aes=0, existing_bdrs=0, num_aes=2, num_bdrs=0, cadence=3,
        ae_quota_m=0.6, bdr_sql=6,  # bdr_sql unused — 0 BDRs on this segment
        marketing_sqls=393.75, selfsrc=0.0,  # was leads=2500*0.45*0.35
        deal=3500, wm=0.32, wb=0.0, ws=0.0,
        term=12, lag=1, psfee=0.0, churn=0.18, exp=0.10, contr=0.05,
    ),
}
# Comp (ae_base/ae_var/bdr_base/bdr_var) intentionally not in presets — it now
# lives in the Advanced section with a smart default derived from quota,
# consistent with keeping comp detail out of the headline assumptions.


def render_inputs(key: str, label: str, num_months_default: int = 24, show_gross_margin: bool = False,
                   fixed_segment: str = None, show_horizon: bool = True) -> dict:
    st.subheader(label)

    if fixed_segment is not None:
        # Full Company mode: segment is fixed to this box (no dropdown), and
        # horizon/gross margin are shared top-level controls collected once,
        # outside this function — so this box skips that whole top row.
        pod_preset = fixed_segment
        gross_margin_pct = None
        num_months = num_months_default
    else:
        # Same 8-column grid as the "Team & Quota" row below, so the Segment /
        # Horizon / Gross margin boxes line up at the same width instead of
        # stretching across 1/2 or 1/3 of the page.
        top1, top2, top3, *_ = st.columns(8)
        if show_gross_margin:
            gross_margin_pct = top3.number_input("Gross margin %", 0.0, 1.0, 0.75, step=0.01, key=f"{key}_gm",
                                                  help="Used for LTV. Blended gross margin on subscription revenue. Used only in the LTV formula: LTV = ARPA × Gross Margin ÷ Annual Churn Rate.")
        else:
            gross_margin_pct = None
        pod_preset = top1.selectbox(
            "Segment", ["SMB", "Mid-Market", "Enterprise", "Inbound", "Other (custom)"],
            index=1, key=f"{key}_pod_preset",
            help="Loads a starting set of assumptions for that segment (team size, deal size, win rates, renewal rates). Every field below is still editable after — this just sets sensible defaults.",
        )
        if show_horizon:
            num_months = top2.number_input("Horizon (months)", 6, 48, num_months_default, key=f"{key}_num_months",
                                            help="How many months forward the model projects, starting from month 1 of new bookings.")
        else:
            num_months = num_months_default

    # Detect a preset CHANGE and inject its defaults into session_state
    # *before* the affected widgets are created below — Streamlit widgets
    # read their initial value from session_state if already set, ignoring
    # the value= parameter in code once a key has been touched.
    prev_key = f"{key}_applied_preset"
    if st.session_state.get(prev_key) != pod_preset and pod_preset in _PRESET_DEFAULTS:
        for suffix, val in _PRESET_DEFAULTS[pod_preset].items():
            st.session_state[f"{key}_{suffix}"] = val
        st.session_state[prev_key] = pod_preset

    if pod_preset == "Other (custom)":
        pod_name = st.text_input("Custom segment name", "MidMarket", key=f"{key}_pod_name_custom",
                                  help="Just a label — doesn't affect any of the math.")
    else:
        pod_name = pod_preset

    # --- Horizontal assumptions grid — headline inputs only. Matches how a
    # real financial model keeps assumptions in one visible band (top row
    # or frozen pane), not buried in a long vertical sidebar. Secondary/
    # detail inputs (comp breakdown, hiring cadence, seasonality) live in
    # the collapsed "Advanced" section below, the same way a real model
    # keeps headcount/comp detail on its own separate sheet. ---
    st.caption("Team & Quota")
    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    num_existing_aes = c1.number_input("Existing AEs", 0, 100, 0, key=f"{key}_existing_aes",
                                        help="Already on the team — fully productive from month 1, no ramp-up period.")
    num_aes = c2.number_input("New AEs", 0, 50, 3, key=f"{key}_num_aes",
                               help="New hires — ramp up over 3 months (33%/66%/100% of full quota-carrying capacity), phased in per the hiring cadence set in Advanced.")
    num_existing_bdrs = c3.number_input("Existing BDRs", 0, 100, 0, key=f"{key}_existing_bdrs",
                                         help="Already on the team — fully productive from month 1.")
    num_bdrs = c4.number_input("New BDRs", 0, 50, 2, key=f"{key}_num_bdrs",
                                help="New hires — same 3-month ramp as new AEs.")
    ae_quota_millions = c5.number_input("AE quota ($M)", 0.0, 10.0, 1.1, step=0.1, key=f"{key}_ae_quota_m",
                                         help="Annual bookings quota per fully-ramped AE, in TCV (Total Contract Value) — the same unit as Avg Deal Size, not ARR. Only equals an ARR quota when the contract term is 12 months. Sets the hard capacity ceiling on how much this team can close, and drives the default comp split in Advanced (5.5x quota:OTE).")
    bdr_sql = c6.number_input("BDR SQLs/mo", 0, 50, 6, key=f"{key}_bdr_sql",
                               help="SQLs (sales-qualified leads) each fully-ramped BDR produces per month, feeding the AE pipeline.")
    marketing_sqls = c7.number_input("Mktg SQLs/mo", 0.0, 500.0, 12.0, key=f"{key}_marketing_sqls",
                                      help="Marketing/inbound-sourced SQLs per month — a flat number, not a lead→MQL→SQL funnel. Channel mix (content, paid, partnerships) is too company-specific to model generically; see README.")
    ae_self_sourced = c8.number_input("AE self-src/mo", 0.0, 20.0, 2.0, step=1.0, key=f"{key}_selfsrc",
                                       help="SQLs each AE generates on their own (existing network, outbound), on top of what BDRs and marketing feed them.")

    st.caption("Deal Economics & Win Rates")
    e1, e2, e3, e4 = st.columns(4)
    avg_deal_size = e1.number_input("Avg deal size — TCV ($)", 0, 5_000_000, 18_000, step=1000, key=f"{key}_deal",
                                     help="Average Total Contract Value per deal — the full value over the entire contract term, not annualized. Used to convert monthly bookings $ into individual synthetic contracts.")
    win_marketing = e2.slider("Win rate — marketing", 0.0, 1.0, 0.25, key=f"{key}_wm",
                               help="% of marketing-sourced SQLs that close as won deals.")
    win_bdr = e3.slider("Win rate — BDR", 0.0, 1.0, 0.20, key=f"{key}_wb",
                         help="% of BDR-sourced SQLs that close as won deals. Typically lower than marketing/self-sourced — colder outbound leads.")
    win_self = e4.slider("Win rate — self-sourced", 0.0, 1.0, 0.35, key=f"{key}_ws",
                          help="% of AE-self-sourced SQLs that close as won deals. Typically the highest — warmest, highest-intent source.")

    st.caption("Contract & Renewal")
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    contract_term = f1.number_input("Term (mo)", 1, 60, 12, key=f"{key}_term",
                                     help="Subscription contract length. Revenue is recognized ratably (evenly) over this period, starting at go-live.")
    implementation_lag = f2.number_input("Impl. lag (mo)", 0, 24, 2, key=f"{key}_lag",
                                          help="Months between signing and go-live. Revenue recognition can't start until go-live, even though the deal is already booked — this is the gap that breaks naive 'bookings = revenue' models.")
    churn_rate = f3.number_input("Churn %", 0.0, 1.0, 0.12, step=0.01, key=f"{key}_churn",
                                  help="Annual gross revenue churn rate — % of ARR lost at renewal from customers who don't renew at all.")
    expansion_rate = f4.number_input("Expansion %", 0.0, 1.0, 0.18, step=0.01, key=f"{key}_exp",
                                      help="Annual expansion rate — % ARR gained from upsell/cross-sell among renewing accounts (applied after churn, to the retained base).")
    contraction_rate = f5.number_input("Contraction %", 0.0, 1.0, 0.03, step=0.01, key=f"{key}_contr",
                                        help="Annual contraction rate — % ARR lost from downgrades among renewing accounts (distinct from full churn — the account stays, just pays less).")
    execution_efficiency = f6.number_input("Exec. efficiency", 0.0, 1.5, 1.0, step=0.01, key=f"{key}_exec",
                                            help="Real-world execution quality, independent of funnel/capacity math — deal slippage, discounting, a rep having a bad quarter. 1.0 = perfect execution. Still capped by capacity even above 1.0.")

    # --- Advanced: comp breakdown, hiring cadence, custom schedules,
    # seasonality, PS fee. Collapsed by default — a smart comp default is
    # derived from quota so the model runs correctly even if never opened. ---
    with st.expander("Advanced: Comp, Hiring Schedule, Seasonality"):
        st.caption("AE comp defaults to a 5.5x quota:OTE split (mid of the healthy 4-6x band) unless overridden.")
        default_ae_ote = (ae_quota_millions * 1_000_000) / 5.5
        ac1, ac2 = st.columns(2)
        ae_base = ac1.number_input("AE annual base ($)", 0, 500_000, int(default_ae_ote / 2), step=5000, key=f"{key}_ae_base",
                                    help="AE annual base salary. Paid every month regardless of ramp or attainment.")
        ae_variable = ac2.number_input("AE annual variable @ 100% ($)", 0, 500_000, int(default_ae_ote / 2), step=5000, key=f"{key}_ae_var",
                                        help="AE commission/bonus at 100% quota attainment. Paid proportionally to actual attainment, scaled by ramp.")

        bc1, bc2 = st.columns(2)
        bdr_base = bc1.number_input("BDR annual base ($)", 0, 300_000, 55_000, step=5000, key=f"{key}_bdr_base",
                                     help="BDR annual base salary.")
        bdr_variable = bc2.number_input("BDR annual variable @ 100% ($)", 0, 300_000, 30_000, step=5000, key=f"{key}_bdr_var",
                                         help="BDR commission/bonus at 100% SQL quota attainment.")

        hiring_cadence = st.number_input("Default hiring cadence (months between hires)", 1, 12, 3, key=f"{key}_cadence",
                                          help="New hires are staggered this many months apart by default (e.g. 3 = one new hire every 3 months). Overridden by a custom schedule below if you set one.")
        custom_ae_schedule_raw = st.text_input(
            "Custom AE hire-month schedule (optional, comma-separated)", "", key=f"{key}_ae_custom_sched",
            help=f"e.g. '0,0,6,6' to hire 2 now and 2 more in month 6. Must have exactly {num_aes} entries if used. Leave blank to use the cadence above.",
        )
        custom_bdr_schedule_raw = st.text_input(
            "Custom BDR hire-month schedule (optional, comma-separated)", "", key=f"{key}_bdr_custom_sched",
            help=f"Same format. Must have exactly {num_bdrs} entries if used. Leave blank to use the cadence above.",
        )
        ae_hire_months = None
        if custom_ae_schedule_raw.strip():
            try:
                ae_hire_months = [int(x.strip()) for x in custom_ae_schedule_raw.split(",")]
                if len(ae_hire_months) != num_aes:
                    st.error(f"Custom AE schedule has {len(ae_hire_months)} entries, need {num_aes}. Using default cadence.")
                    ae_hire_months = None
            except ValueError:
                st.error("Couldn't parse custom AE schedule. Using default cadence.")

        bdr_hire_months = None
        if custom_bdr_schedule_raw.strip():
            try:
                bdr_hire_months = [int(x.strip()) for x in custom_bdr_schedule_raw.split(",")]
                if len(bdr_hire_months) != num_bdrs:
                    st.error(f"Custom BDR schedule has {len(bdr_hire_months)} entries, need {num_bdrs}. Using default cadence.")
                    bdr_hire_months = None
            except ValueError:
                st.error("Couldn't parse custom BDR schedule. Using default cadence.")

        ps_fee_pct = st.slider("Professional services fee (% of ARR)", 0.0, 0.5, 0.0, key=f"{key}_psfee",
                                help="One-time implementation fee, as a % of the account's ARR. Billed upfront at signing, but recognized as revenue only at go-live (point-in-time, distinct performance obligation under ASC 606).")

        use_seasonality = st.checkbox("Apply seasonal pattern", value=False, key=f"{key}_useseason",
                                       help="Apply a repeating 12-month multiplier pattern to realized bookings (e.g. December slowdown, Q4 push). Still capped by the hard capacity ceiling.")
        seasonality_pattern = None
        if use_seasonality:
            months_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            season_cols = st.columns(6)
            seasonality_pattern = [
                season_cols[i % 6].slider(months_labels[i], 0.0, 2.0, 1.0, key=f"{key}_season_{i}",
                                           help=f"Bookings multiplier for {months_labels[i]}. 1.0 = normal, 0.5 = half, 1.5 = 50% above normal.")
                for i in range(12)
            ]

    return dict(
        pod_name=pod_name, num_aes=num_aes, num_bdrs=num_bdrs, hiring_cadence=hiring_cadence,
        num_existing_aes=num_existing_aes, num_existing_bdrs=num_existing_bdrs,
        ae_hire_months=ae_hire_months, bdr_hire_months=bdr_hire_months,
        ae_base=ae_base, ae_variable=ae_variable, ae_quota=ae_quota_millions * 1_000_000,
        bdr_base=bdr_base, bdr_variable=bdr_variable, bdr_monthly_sql_quota=bdr_sql,
        marketing_sqls=marketing_sqls,
        ae_self_sourced=ae_self_sourced, avg_deal_size=avg_deal_size,
        win_marketing=win_marketing, win_bdr=win_bdr, win_self=win_self,
        execution_efficiency=execution_efficiency, contract_term=contract_term,
        implementation_lag=implementation_lag, ps_fee_pct=ps_fee_pct,
        churn_rate=churn_rate, expansion_rate=expansion_rate, contraction_rate=contraction_rate,
        seasonality_pattern=seasonality_pattern, num_months=num_months, gross_margin_pct=gross_margin_pct,
    )


# ---------------------------------------------------------------------------
# Runs all three phases for one config dict. Returns everything needed for
# display AND for cross-scenario bridging (all_contracts is needed for the
# origin-split revenue bridge).
# ---------------------------------------------------------------------------
def build_pod(cfg: dict) -> PodConfig:
    return PodConfig(
        pod_name=cfg["pod_name"], num_aes=int(cfg["num_aes"]), num_bdrs=int(cfg["num_bdrs"]),
        num_existing_aes=int(cfg["num_existing_aes"]), num_existing_bdrs=int(cfg["num_existing_bdrs"]),
        ae_comp_template=RoleComp(annual_base=cfg["ae_base"], annual_variable_at_100pct=cfg["ae_variable"], annual_quota=cfg["ae_quota"]),
        bdr_comp_template=RoleComp(annual_base=cfg["bdr_base"], annual_variable_at_100pct=cfg["bdr_variable"],
                                    annual_quota=cfg["bdr_monthly_sql_quota"] * 12) if (cfg["num_bdrs"] > 0 or cfg["num_existing_bdrs"] > 0) else None,
        # Marketing funnel mechanics (lead->MQL->SQL conversion) are deliberately
        # not modeled — channel mix is too company/product-specific to generalize
        # honestly (see README). marketing_sqls is a flat pass-through: leads=SQLs,
        # both conversion rates=100%, so sqls_generated() reduces to marketing_sqls
        # exactly. Same treatment BDR output already gets (a flat SQL quota, not
        # a simulated call->connect->meeting funnel) — kept consistent on purpose.
        marketing=MarketingFunnel(monthly_leads=cfg["marketing_sqls"], lead_to_mql_rate=1.0, mql_to_sql_rate=1.0),
        avg_deal_size=cfg["avg_deal_size"], win_rate_marketing_sourced=cfg["win_marketing"],
        win_rate_bdr_sourced=cfg["win_bdr"], win_rate_ae_self_sourced=cfg["win_self"],
        ae_self_sourced_sqls_per_month=cfg["ae_self_sourced"], execution_efficiency=cfg["execution_efficiency"],
        hiring_cadence_months=int(cfg["hiring_cadence"]), contract_term_months=int(cfg["contract_term"]),
        implementation_lag_months=int(cfg["implementation_lag"]), professional_services_fee_pct_of_arr=cfg["ps_fee_pct"],
        seasonality_pattern=cfg["seasonality_pattern"],
        ae_hire_months=cfg.get("ae_hire_months"), bdr_hire_months=cfg.get("bdr_hire_months"),
    )


def attainment_summary(cfg: dict, num_months: int) -> dict:
    """Cheap Phase-1-only preview (no Phase 2/3) — used to show AE quota
    attainment right under a market's assumptions, before running the full
    model. Attainment is actual_bookings/capacity_constrained_bookings, which
    is mathematically capped at 100% (capacity is a hard ceiling) — so it
    can never itself "exceed 100%". The actionable signal for "is this
    assumption realistic" is how FAR BELOW 100% it sits, plus how many
    months are capacity- vs. demand-bound: low attainment + mostly
    demand-bound months means AEs have slack, so more pipeline (e.g. one
    more BDR) can close a lot more without hitting the capacity ceiling.
    """
    pod = build_pod(cfg)
    phase1_df = run_scenario(pod.build_scenario(num_months))
    if len(phase1_df) == 0:
        return {"avg_attainment_pct": None, "months_capacity_bound": 0, "total_months": 0}
    return {
        "avg_attainment_pct": round(phase1_df["overall_attainment_pct"].mean(), 1),
        "months_capacity_bound": int((phase1_df["binding_constraint"] == "CAPACITY").sum()),
        "total_months": len(phase1_df),
    }


def run_full_model(cfg: dict, num_months: int):
    pod = build_pod(cfg)
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
# MULTI-MARKET COMBINING — sums genuinely additive columns across markets'
# Phase 1 / Phase 2 output, then RE-DERIVES ratio/categorical fields
# (binding_constraint, attainment, ARPA, cost-per-dollar) from the summed
# components using the same formulas the engines use — a blind sum of a
# ratio or a string field would be wrong. Fields that are set per-pod and
# have no meaningful combined value (execution_efficiency, seasonal
# multiplier, coverage) are dropped from the combined view rather than
# faked; they're still visible in each market's own per-market breakdown.
# ---------------------------------------------------------------------------
def combine_phase1_dfs(phase1_dfs: list) -> pd.DataFrame:
    if len(phase1_dfs) == 1:
        return phase1_dfs[0].copy()
    additive_cols = ["active_aes", "active_bdrs", "sqls_marketing", "sqls_bdr", "sqls_ae_self_sourced",
                      "capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings",
                      "ae_cost", "bdr_cost", "total_cost_of_capacity"]
    combined = phase1_dfs[0][["month"]].copy()
    for col in additive_cols:
        combined[col] = sum(df[col].values for df in phase1_dfs)

    combined["theoretical_bookings"] = combined[["capacity_constrained_bookings", "demand_constrained_bookings"]].min(axis=1)

    def _binding(row):
        if row["capacity_constrained_bookings"] < row["demand_constrained_bookings"]:
            return "CAPACITY"
        elif row["demand_constrained_bookings"] < row["capacity_constrained_bookings"]:
            return "DEMAND"
        return "BALANCED"
    combined["binding_constraint"] = combined.apply(_binding, axis=1)

    combined["overall_attainment_pct"] = combined.apply(
        lambda r: round(100 * r["actual_bookings"] / r["capacity_constrained_bookings"], 1)
        if r["capacity_constrained_bookings"] > 0 else 0.0, axis=1,
    )
    combined["cost_per_dollar_booked"] = combined.apply(
        lambda r: round(r["total_cost_of_capacity"] / r["actual_bookings"], 3)
        if r["actual_bookings"] > 0 else None, axis=1,
    )
    return combined


def combine_phase2_dfs(phase2_dfs: list) -> pd.DataFrame:
    if len(phase2_dfs) == 1:
        return phase2_dfs[0].copy()
    additive_cols = ["new_bookings_tcv", "new_accounts_signed", "new_arr_booked", "cumulative_accounts_signed",
                      "cumulative_arr_booked", "live_accounts", "live_arr", "subscription_billings",
                      "subscription_revenue_recognized", "ps_fee_billings", "ps_fee_revenue_recognized",
                      "total_billings", "total_revenue_recognized", "cumulative_billings",
                      "cumulative_revenue_recognized", "deferred_revenue_balance",
                      "implementation_backlog_value", "implementation_backlog_count"]
    combined = phase2_dfs[0][["month"]].copy()
    for col in additive_cols:
        combined[col] = sum(df[col].values for df in phase2_dfs)

    combined["arpa_new_accounts"] = combined.apply(
        lambda r: round(r["new_arr_booked"] / r["new_accounts_signed"], 2) if r["new_accounts_signed"] else None, axis=1)
    combined["blended_arpa_booked"] = combined.apply(
        lambda r: round(r["cumulative_arr_booked"] / r["cumulative_accounts_signed"], 2) if r["cumulative_accounts_signed"] else None, axis=1)
    combined["blended_arpa_live"] = combined.apply(
        lambda r: round(r["live_arr"] / r["live_accounts"], 2) if r["live_accounts"] else None, axis=1)
    return combined


def combine_renewals_for_display(renewals_df: pd.DataFrame) -> pd.DataFrame:
    """renewals_df (from concatenating multiple markets) can have several rows
    per month — one per pod whose cohort ended that month. That's correct
    for summarize_renewals() (an accurate per-event count) and for
    aggregate_periods() (which groups by month internally either way), but
    wide()'s month-indexed transpose needs exactly one row per month or it
    produces duplicate column labels, which breaks Arrow serialization.
    Sums the $ /count columns per month and re-derives the 2 rate fields
    from the summed components, dropping pod_name (mixed across pods here).
    """
    if len(renewals_df) == 0:
        return renewals_df
    sum_cols = ["logos_up_for_renewal", "arr_up_for_renewal", "churned_arr", "expansion_arr",
                "contraction_arr", "renewed_arr", "logos_retained_expected"]
    combined = renewals_df.groupby("month", as_index=False)[sum_cols].sum()
    combined["churn_rate_applied_pct"] = combined.apply(
        lambda r: round(100 * r["churned_arr"] / r["arr_up_for_renewal"], 2) if r["arr_up_for_renewal"] else None, axis=1)
    combined["nrr_this_cohort_pct"] = combined.apply(
        lambda r: round(100 * r["renewed_arr"] / r["arr_up_for_renewal"], 1) if r["arr_up_for_renewal"] else None, axis=1)
    return combined.sort_values("month").reset_index(drop=True)


# ---------------------------------------------------------------------------
# MODE SELECTOR
# ---------------------------------------------------------------------------
mode = st.radio("Mode", ["Full Company (All Segments)", "Compare Two Scenarios"], horizontal=True)

# ===========================================================================
# FULL COMPANY MODE — all 4 standard segments configured and run together
# (previously one segment at a time behind a dropdown). Horizon and gross
# margin are shared, top-level controls here rather than duplicated per box,
# since all 4 markets need to run over the same window for a coherent
# consolidated total.
# ===========================================================================
if mode == "Full Company (All Segments)":
    MARKET_NAMES = ["SMB", "Mid-Market", "Enterprise", "Inbound"]
    MARKET_KEYS = {"SMB": "smb", "Mid-Market": "mm", "Enterprise": "ent", "Inbound": "inb"}

    fc1, fc2 = st.columns(8)[:2]
    num_months = fc1.number_input("Horizon (months)", 6, 48, 24, key="fc_num_months",
                                   help="How many months forward the model projects, starting from month 1 of new bookings. Shared across all 4 markets so the consolidated total is coherent.")
    gross_margin_pct = fc2.number_input("Gross margin % (for LTV)", 0.0, 1.0, 0.75, step=0.01, key="fc_gm",
                                         help="Used for LTV. Blended gross margin on subscription revenue. Used only in the LTV formula: LTV = ARPA × Gross Margin ÷ Annual Churn Rate.")

    cfgs = {}
    for market in MARKET_NAMES:
        with st.expander(market, expanded=True):
            cfg_m = render_inputs(MARKET_KEYS[market], market, num_months_default=num_months,
                                   fixed_segment=market, show_horizon=False)
            att = attainment_summary(cfg_m, num_months)
            if att["avg_attainment_pct"] is not None:
                st.caption(
                    f"Avg AE Attainment: {att['avg_attainment_pct']:.1f}% · "
                    f"Capacity-bound in {att['months_capacity_bound']}/{att['total_months']} months. "
                    + ("AEs are fully utilized — more pipeline alone won't grow bookings here."
                       if att["months_capacity_bound"] == att["total_months"]
                       else "AEs have slack capacity — more pipeline (marketing/BDR) can still convert to bookings.")
                )
            cfgs[market] = cfg_m

    # -----------------------------------------------------------------
    # EXISTING CUSTOMER BOOK (optional) — top-line ARR/revenue overlay,
    # NOT run through the Contract engine (no individual contract dates
    # available from a revenue extract). Runs alongside new business.
    # Lives in the main area, not a sidebar — nothing in this app should
    # sit in a separate vertical pane the assumptions grid doesn't.
    # -----------------------------------------------------------------
    existing_book_df = None
    derived_metrics = None
    historical_annual = None

    include_existing = st.checkbox("Use historical customer data to ground the forecast", value=False,
                                    help="Upload customer-level monthly revenue to derive historical NRR, churn and expansion and project the existing customer base alongside new business.")

    if include_existing:
        with st.expander("Existing Customer Book", expanded=True):
            uploaded = st.file_uploader("Upload customer revenue extract (CSV or Excel)", type=["csv", "xlsx"],
                                         help="Long format: one row per customer per month. Used to derive real trailing-12-month NRR/churn directly from your data, instead of guessing a rate.")
            st.caption("Long format expected: one row per customer per month (customer, month, revenue). "
                       "At least 13 months of history needed to derive a trailing-12-month comparison.")

            if uploaded is not None:
                try:
                    raw_df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
                except Exception as e:
                    st.error(f"Couldn't read file: {e}")
                    raw_df = None

                if raw_df is not None:
                    st.caption("Map your columns:")
                    cols = list(raw_df.columns)
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    customer_col = mc1.selectbox("Customer column", cols, index=0,
                                                  help="Which column identifies each customer (name or ID).")
                    month_col = mc2.selectbox("Month column", cols, index=min(1, len(cols) - 1),
                                               help="Which column has the month/date for each revenue row.")
                    revenue_col = mc3.selectbox("Revenue column", cols, index=min(2, len(cols) - 1),
                                                 help="Which column has the recognized revenue amount for that customer-month.")
                    lookback = mc4.number_input("Lookback (months)", 1, 24, 12,
                                                 help="How far back to compare for the churn/expansion/NRR calculation — 12 months is the standard trailing-twelve-month convention.")

                    try:
                        matrix = load_customer_revenue_extract(raw_df, customer_col, month_col, revenue_col)
                        derived_metrics = derive_book_metrics(matrix, lookback_months=lookback)
                    except Exception as e:
                        st.error(f"Couldn't derive metrics: {e}")
                        derived_metrics = None

                    if derived_metrics is not None:
                        st.success(
                            f"Derived NRR: {derived_metrics.nrr_pct}% "
                            f"({derived_metrics.customers_matched} matched, {derived_metrics.customers_churned} churned)"
                        )
                        historical_annual = derive_annual_history(matrix).rename(columns={"new_arr_booked": "new_arr_live"})

                        override = st.checkbox("Override derived rates manually", value=False,
                                                help="The derived rates above come straight from your data — this lets you adjust them (e.g. if you know a one-off event skewed the numbers).")
                        if override:
                            oc1, oc2, oc3 = st.columns(3)
                            eb_churn = oc1.slider("Existing book — annual churn", 0.0, 1.0, derived_metrics.implied_annual_churn_rate or 0.10)
                            eb_expansion = oc2.slider("Existing book — annual expansion", 0.0, 1.0, derived_metrics.implied_annual_expansion_rate or 0.10)
                            eb_contraction = oc3.slider("Existing book — annual contraction", 0.0, 1.0, derived_metrics.implied_annual_contraction_rate or 0.02)
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

    try:
        results = {m: run_full_model(cfgs[m], num_months) for m in MARKET_NAMES}
    except Exception as e:
        st.error(f"Model error: {e}")
        st.stop()

    selected_markets = st.multiselect(
        "Markets to include", MARKET_NAMES, default=MARKET_NAMES, key="fc_market_filter",
        help="Governs the Executive Dashboard and every tab below — charts/metrics show the sum across whichever markets are selected here, and raw data tables break out each selected market separately underneath the combined view.",
    )
    if not selected_markets:
        st.warning("Select at least one market above to see results.")
        st.stop()

    phase1_df = combine_phase1_dfs([results[m]["phase1_df"] for m in selected_markets])
    phase2_df = combine_phase2_dfs([results[m]["phase2_df"] for m in selected_markets])
    renewals_df = pd.concat([results[m]["renewals_df"] for m in selected_markets], ignore_index=True)
    all_contracts = [c for m in selected_markets for c in results[m]["all_contracts"]]

    eb_base_arr = derived_metrics.base_arr if derived_metrics is not None else 0.0
    eb_base_logos = derived_metrics.base_logo_count if derived_metrics is not None else 0

    tab_names = ["📐 Executive Dashboard", "📈 Pipeline & Capacity", "💰 Revenue Recognition", "🔄 Renewals & NRR"]
    if existing_book_df is not None:
        tab_names.insert(1, "🏢 Total Company")
    tabs = st.tabs(tab_names)
    tab_offset = 1  # SaaS Metrics Dashboard is always tab 0 now
    if existing_book_df is not None:
        tab_offset = 2

    with tabs[0]:
        st.caption("ARR, revenue, retention and key forecast drivers.")
        annual = aggregate_periods(
            phase2_df, renewals_df, existing_book_df, all_contracts, num_months,
            period_months=12, gross_margin_pct=gross_margin_pct,
            existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
        )
        # aggregate_periods()'s "new_arr_booked" is go-live-date-based (see
        # saas_metrics.py docstring), not signed-date — renamed locally so it
        # doesn't collide with the genuinely signed-date "new_arr_booked" that
        # comes straight from Phase 2 (revenue_recognition_engine.py) elsewhere
        # in this app. See _LABELS for the full explanation.
        annual = annual.rename(columns={"new_arr_booked": "new_arr_live"})
        # Per-period deferred revenue for the "By Year" table below — not an
        # aggregate_periods() field (it's a point-in-time balance, not a
        # period sum), so pulled from combined phase2_df at each forecast
        # period's last month. annual's row order matches period index p
        # exactly (aggregate_periods builds it that way), so position i's
        # end month is min((i+1)*12, num_months).
        annual["deferred_revenue"] = [
            (lambda match: match.iloc[0] if len(match) else None)(
                phase2_df.loc[phase2_df["month"] == min((i + 1) * 12, num_months), "deferred_revenue_balance"]
            )
            for i in range(len(annual))
        ]
        annual["type"] = "Forecast"

        if historical_annual is not None and len(historical_annual) > 0:
            historical_annual = historical_annual.copy()
            historical_annual["deferred_revenue"] = None  # no deferred-revenue concept in a revenue extract
            combined_annual = pd.concat([historical_annual, annual], ignore_index=True)
        else:
            combined_annual = annual

        latest = combined_annual.iloc[-1]
        prior = combined_annual.iloc[-2] if len(combined_annual) > 1 else None

        def _delta(field):
            if prior is None or pd.isna(prior[field]) or prior[field] == 0 or pd.isna(latest[field]):
                return None
            return latest[field] - prior[field]

        st.subheader(f"Full Company — {latest['period']}")
        st.caption(f"Markets included: {', '.join(selected_markets)}.")
        if historical_annual is not None and len(historical_annual) > 0:
            st.caption(f"Showing {len(historical_annual)} year(s) of actuals from your extract, "
                       f"continuing into {len(annual)} year(s) of forecast.")

        with st.expander("↓ Export Auditable Excel Model", icon="📥"):
            st.caption(
                "Real formulas, not pasted values — auditable in Excel, shareable with bankers/investors/corp dev. "
                "One Capacity + Revenue sheet pair per segment, plus a consolidated Summary with per-segment "
                "columns AND a Total Company column that sums across them — a real multi-segment model, not "
                "just one team. Not included: professional services fees, seasonality, Existing Book overlay. "
                "Annual summary covers full years only."
            )
            st.caption(f"This export covers the markets currently selected above: {', '.join(selected_markets)}.")
            try:
                cfg_list = [cfgs[m] for m in selected_markets]
                xlsx_bytes = generate_multi_pod_workbook_bytes(cfg_list, num_months)
                st.download_button(
                    "Download financial_model.xlsx",
                    data=xlsx_bytes,
                    file_name="company_financial_model.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as e:
                st.error(f"Couldn't generate the workbook: {e}")

        # Hero tiles: primary audience is FP&A/CFO, not investors — accounting-
        # operational metrics (Recognized Revenue, Deferred Revenue) take
        # priority over investor-deck metrics (LTV, GRR), which move to the
        # secondary "More metrics" expander below instead of disappearing.
        ending_deferred_revenue = phase2_df["deferred_revenue_balance"].iloc[-1]

        revenue_delta = _delta("revenue")
        logos_delta = _delta("ending_logos")
        nrr_delta = _delta("nrr_pct")

        c1, c2, c3, c4, c5 = st.columns(5)
        arr_growth_pct = ((latest["ending_arr"] / prior["ending_arr"]) - 1) * 100 if prior is not None and prior["ending_arr"] else None
        c1.metric("Ending ARR", f"${latest['ending_arr']:,.0f}",
                   delta=f"{arr_growth_pct:.1f}% YoY" if arr_growth_pct is not None else None)
        c2.metric("Recognized Revenue", f"${latest['revenue']:,.0f}" if latest["revenue"] is not None else "—",
                   delta=f"${revenue_delta:,.0f}" if revenue_delta is not None else None)
        c3.metric("Net Revenue Retention", f"{latest['nrr_pct']:.1f}%" if latest["nrr_pct"] is not None else "—",
                   delta=f"{nrr_delta:.1f} pts" if nrr_delta is not None else None, delta_color="normal")
        c4.metric("Live Accounts", f"{int(latest['ending_logos']):,}" if latest["ending_logos"] is not None else "—",
                   delta=f"{logos_delta:,.0f}" if logos_delta is not None else None)
        c5.metric("Deferred Revenue", f"${ending_deferred_revenue:,.0f}",
                   help="New-business deferred revenue balance (billed but not yet recognized). Doesn't include the Existing Book overlay — a revenue extract has no individual contract dates to derive a deferred balance from.")

        with st.expander("More metrics (GRR, Logo Churn, LTV)"):
            m1, m2, m3 = st.columns(3)
            grr = 100 - latest["gross_dollar_churn_rate_pct"] if latest["gross_dollar_churn_rate_pct"] is not None else None
            m1.metric("Gross Revenue Retention", f"{grr:.1f}%" if grr is not None else "—")
            logo_churn_delta = _delta("logo_churn_rate_pct")
            m2.metric("Logo Churn Rate", f"{latest['logo_churn_rate_pct']:.1f}%" if latest["logo_churn_rate_pct"] is not None else "—",
                       delta=f"{logo_churn_delta:.1f} pts" if logo_churn_delta is not None else None, delta_color="inverse")
            m3.metric("Customer LTV", f"${latest['ltv']:,.0f}" if latest["ltv"] is not None else "—")

        st.markdown("**By Year**")
        by_year = pd.DataFrame({
            "Ending ARR": combined_annual["ending_arr"].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—"),
            "Recognized Revenue": combined_annual["revenue"].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—"),
            "NRR": combined_annual["nrr_pct"].apply(lambda v: f"{v:.1f}%" if pd.notna(v) else "—"),
            "Live Accounts": combined_annual["ending_logos"].apply(lambda v: f"{int(v):,}" if pd.notna(v) else "—"),
            "Deferred Revenue": combined_annual["deferred_revenue"].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—"),
        }, index=combined_annual["period"]).T
        st.dataframe(by_year, width='stretch')

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
            st.plotly_chart(arr_fig, width='stretch')

        st.caption(f"ARR Bridge — {latest['period']}")
        wf_labels = ["Beginning<br>ARR", "New ARR<br>(Went Live)", "Expansion", "Contraction", "Churn", "Other /<br>Boundary", "Ending<br>ARR"]
        wf_values = [latest["beginning_arr"], latest["new_arr_live"], latest["expansion_arr"],
                     -latest["contraction_arr"], -latest["churned_arr"], latest["other_boundary_effect"], latest["ending_arr"]]
        st.plotly_chart(make_waterfall(wf_labels, wf_values, ""), width='stretch')

        with st.expander("View underlying data"):
            st.caption(
                "'New ARR (Went Live)' is ARR that went LIVE this period (by go-live date), not ARR signed — "
                "those differ once implementation lag is involved. That's distinct from 'New ARR Booked (Signed)', "
                "shown in the Revenue Recognition tab's raw data, which is signed-date-based. LTV is annual-only: a single "
                "quarter's churn rate is too noisy to use as an LTV input. Historical actual years "
                "have no LTV (gross margin isn't in a revenue extract) and the earliest actual year "
                "has no NRR/churn (no prior-year baseline to compare against)."
            )
            st.markdown("**Annual (Actual + Forecast)**")
            st.dataframe(style_wide(combined_annual.set_index("period").T), width='stretch')


            st.markdown("**Quarterly**")
            quarterly = aggregate_periods(
                phase2_df, renewals_df, existing_book_df, all_contracts, num_months,
                period_months=3, existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
            )
            quarterly = quarterly.rename(columns={"new_arr_booked": "new_arr_live"})
            num_years = (num_months + 11) // 12
            for y in range(num_years):
                year_quarters = quarterly[quarterly["period"].str.startswith(f"Y{y+1}-")]
                if len(year_quarters) > 0:
                    st.markdown(f"*Year {y+1}*")
                    st.dataframe(style_wide(year_quarters.set_index("period").T), width='stretch')

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
            c2.metric("New Business — Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
            c3.metric("Total Company — Ending ARR", f"${combined['total_arr'].iloc[-1]:,.0f}")
            st.line_chart(combined.set_index("month")[["existing_book_arr", "new_business_live_arr", "total_arr"]].rename(
                columns={"existing_book_arr": "Existing Book ARR", "new_business_live_arr": "New Business ARR (Live)", "total_arr": "Total ARR"}
            ))

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
                st.dataframe(style_wide(wide(combined)), width='stretch')

    with tabs[0 + tab_offset]:
        st.subheader("Bookings: Capacity vs. Demand Constraint")
        st.caption("Actual bookings are constrained by whichever is lower: qualified demand or sales capacity. "
                    "All bookings figures on this tab are TCV (Total Contract Value) — the same unit as Avg Deal Size and AE quota — not ARR.")
        with st.expander("What do these terms mean?"):
            st.markdown(
                "- **Capacity-Constrained Bookings (TCV)** — what AEs *could* close this month given headcount, ramp, and quota alone.\n"
                "- **Demand-Constrained Bookings (TCV)** — what the pipeline *could* support this month, given SQLs (marketing + BDR + AE self-sourced) × win rate × deal size.\n"
                "- **Theoretical Bookings (TCV)** — the lower of the two above: the hard ceiling before execution/seasonality are applied.\n"
                "- **Execution Efficiency** — a realism multiplier applied on top of that ceiling (deal slippage, discounting, a rep having a bad quarter). 1.0 = perfect execution.\n"
                "- **Binding Constraint** — which side (CAPACITY or DEMAND) is actually limiting Actual Bookings this month. CAPACITY means AEs are maxed out; DEMAND means AEs have slack and more pipeline would close more."
            )
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Bookings (TCV)", f"${phase1_df['actual_bookings'].sum():,.0f}")
        col2.metric("Total Cost of Capacity", f"${phase1_df['total_cost_of_capacity'].sum():,.0f}")
        months_capacity_bound = (phase1_df["binding_constraint"] == "CAPACITY").sum()
        col3.metric("Months Capacity-Bound", f"{months_capacity_bound}/{len(phase1_df)}")
        st.info(f"Binding constraint: Capacity in {months_capacity_bound} of {len(phase1_df)} months.")
        st.line_chart(phase1_df.set_index("month")[["capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings"]].rename(
            columns={"capacity_constrained_bookings": "Capacity-Constrained Bookings (TCV)",
                     "demand_constrained_bookings": "Demand-Constrained Bookings (TCV)", "actual_bookings": "Actual Bookings (TCV)"}
        ))

        with st.expander("View underlying data"):
            st.caption("Execution Efficiency, Seasonal Multiplier and Pipeline Coverage aren't shown in the combined "
                       "view — they're set per market and have no single meaningful combined value. See each market below.")
            st.markdown("**Combined (selected markets)**")
            st.dataframe(style_wide(wide(phase1_df)), width='stretch')
            for m in selected_markets:
                st.markdown(f"**{m}**")
                st.dataframe(style_wide(wide(results[m]["phase1_df"])), width='stretch')

    with tabs[1 + tab_offset]:
        st.subheader("Live ARR Trajectory")
        st.caption("Bookings ≠ revenue. Implementation lag delays go-live and revenue recognition, creating a gap between contracted ARR, billings and recognized revenue.")
        col1, col2, col3 = st.columns(3)
        col1.metric("Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
        col2.metric("Ending Deferred Revenue", f"${phase2_df['deferred_revenue_balance'].iloc[-1]:,.0f}")
        col3.metric("Ending Live Accounts", f"{int(phase2_df['live_accounts'].iloc[-1])}")
        st.line_chart(phase2_df.set_index("month")[["live_arr", "cumulative_arr_booked"]].rename(
            columns={"live_arr": "Live ARR", "cumulative_arr_booked": "Cumulative ARR Booked"}
        ))
        st.subheader("Revenue Streams")
        st.bar_chart(phase2_df.set_index("month")[["subscription_revenue_recognized", "ps_fee_revenue_recognized"]].rename(
            columns={"subscription_revenue_recognized": "Subscription Revenue Recognized", "ps_fee_revenue_recognized": "PS Fee Revenue Recognized"}
        ))

        with st.expander("View underlying data"):
            st.markdown("**Combined (selected markets)**")
            st.dataframe(style_wide(wide(phase2_df)), width='stretch')
            for m in selected_markets:
                st.markdown(f"**{m}**")
                st.dataframe(style_wide(wide(results[m]["phase2_df"])), width='stretch')

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
                st.markdown("**Combined (selected markets)**")
                st.dataframe(style_wide(wide(combine_renewals_for_display(renewals_df))), width='stretch')
                for m in selected_markets:
                    market_renewals = results[m]["renewals_df"]
                    if len(market_renewals) > 0:
                        st.markdown(f"**{m}**")
                        st.dataframe(style_wide(wide(market_renewals)), width='stretch')
        else:
            st.info("No renewal events occurred — scenario length may be shorter than the contract term.")

# ===========================================================================
# COMPARE TWO SCENARIOS MODE
# ===========================================================================
else:
    # User-editable scenario names — let labels read as actual business
    # scenarios ("Base Plan" vs. "Aggressive Hiring") instead of the generic
    # "Scenario A"/"Scenario B" everywhere below reads from these two
    # variables now, so a custom name propagates through every chart, table
    # and metric label in this mode.
    name1, name2 = st.columns(2)
    scenario_a_name = name1.text_input("Scenario A label", "Scenario A — Base Plan", key="scenario_a_label")
    scenario_b_name = name2.text_input("Scenario B label", "Scenario B — Alternative Plan", key="scenario_b_label")

    with st.expander(scenario_a_name, expanded=True):
        cfg_a = render_inputs("a", scenario_a_name)
    with st.expander(scenario_b_name, expanded=True):
        cfg_b = render_inputs("b", scenario_b_name)

    # Both scenarios must share one horizon for the bridge math to mean
    # anything — bridging one scenario's ending ARR against the other's
    # from two different-length windows would be comparing apples to
    # oranges. Scenario A's horizon governs; forced explicitly here rather
    # than just hoping the user sets both fields the same.
    if cfg_a["num_months"] != cfg_b["num_months"]:
        st.info(f"{scenario_a_name}'s horizon ({cfg_a['num_months']} months) governs both scenarios "
                f"for a valid comparison — {scenario_b_name}'s horizon setting is ignored.")
    num_months = cfg_a["num_months"]
    cfg_b["num_months"] = num_months

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
            st.subheader(scenario_a_name)
            st.metric("Ending Live ARR", f"${p2a['live_arr'].iloc[-1]:,.0f}")
            st.metric("Total Revenue Recognized", f"${p2a['total_revenue_recognized'].sum():,.0f}")
            st.metric("Ending Deferred Revenue", f"${p2a['deferred_revenue_balance'].iloc[-1]:,.0f}")
        with col2:
            st.subheader(scenario_b_name)
            st.metric("Ending Live ARR", f"${p2b['live_arr'].iloc[-1]:,.0f}",
                       delta=f"${p2b['live_arr'].iloc[-1] - p2a['live_arr'].iloc[-1]:,.0f}")
            st.metric("Total Revenue Recognized", f"${p2b['total_revenue_recognized'].sum():,.0f}",
                       delta=f"${p2b['total_revenue_recognized'].sum() - p2a['total_revenue_recognized'].sum():,.0f}")
            st.metric("Ending Deferred Revenue", f"${p2b['deferred_revenue_balance'].iloc[-1]:,.0f}",
                       delta=f"${p2b['deferred_revenue_balance'].iloc[-1] - p2a['deferred_revenue_balance'].iloc[-1]:,.0f}")

    with tab2:
        # Compact answer-first table, before the waterfalls — Ending ARR,
        # Recognized Revenue and NRR are the latest full-year figure (same
        # scope as the Executive Dashboard's hero tiles); Capacity Cost is
        # cumulative over the full horizon (there's no annual breakdown of
        # capacity cost elsewhere in the app to stay consistent with).
        cmp_annual_a = aggregate_periods(p2a, rna, None, result_a["all_contracts"], num_months, period_months=12)
        cmp_annual_b = aggregate_periods(p2b, rnb, None, result_b["all_contracts"], num_months, period_months=12)
        cmp_latest_a, cmp_latest_b = cmp_annual_a.iloc[-1], cmp_annual_b.iloc[-1]
        capacity_cost_a = result_a["phase1_df"]["total_cost_of_capacity"].sum()
        capacity_cost_b = result_b["phase1_df"]["total_cost_of_capacity"].sum()

        col_a_label = scenario_a_name if scenario_a_name != scenario_b_name else f"{scenario_a_name} (A)"
        col_b_label = scenario_b_name if scenario_a_name != scenario_b_name else f"{scenario_b_name} (B)"

        def _fmt_dollar(v):
            return f"${v:,.0f}" if v is not None and not pd.isna(v) else "—"

        def _fmt_pct(v):
            return f"{v:.1f}%" if v is not None and not pd.isna(v) else "—"

        summary_table = pd.DataFrame([
            {"Metric": "Ending ARR", col_a_label: _fmt_dollar(cmp_latest_a["ending_arr"]), col_b_label: _fmt_dollar(cmp_latest_b["ending_arr"]),
             "Δ (B − A)": _fmt_dollar(cmp_latest_b["ending_arr"] - cmp_latest_a["ending_arr"])},
            {"Metric": "Recognized Revenue", col_a_label: _fmt_dollar(cmp_latest_a["revenue"]), col_b_label: _fmt_dollar(cmp_latest_b["revenue"]),
             "Δ (B − A)": _fmt_dollar(cmp_latest_b["revenue"] - cmp_latest_a["revenue"])},
            {"Metric": "NRR", col_a_label: _fmt_pct(cmp_latest_a["nrr_pct"]), col_b_label: _fmt_pct(cmp_latest_b["nrr_pct"]),
             "Δ (B − A)": (f"{cmp_latest_b['nrr_pct'] - cmp_latest_a['nrr_pct']:.1f} pts"
                            if pd.notna(cmp_latest_a["nrr_pct"]) and pd.notna(cmp_latest_b["nrr_pct"]) else "—")},
            {"Metric": "Capacity Cost", col_a_label: _fmt_dollar(capacity_cost_a), col_b_label: _fmt_dollar(capacity_cost_b),
             "Δ (B − A)": _fmt_dollar(capacity_cost_b - capacity_cost_a)},
        ])
        st.dataframe(summary_table.set_index("Metric"), width='stretch')
        st.caption("Ending ARR, Recognized Revenue and NRR reflect the latest full year; Capacity Cost is cumulative over the full horizon.")

        st.divider()
        st.subheader(f"ARR Bridge: {scenario_a_name} → {scenario_b_name}")
        st.caption(
            "Decomposed using each scenario's own cumulative New Business / Expansion / "
            "Contraction / Churn totals. This is an additive approximation, not a controlled "
            "marginal attribution — cascading renewal timing across months creates real "
            "interaction effects between drivers, shown explicitly as 'Other / interaction' "
            "below rather than hidden or forced to zero. Note: 'Δ New Business (Booked)' is "
            "signed-date-based (Phase 2 bookings), not go-live-date-based like the Executive "
            "Dashboard's 'New ARR (Went Live)' bridge component — the two aren't directly comparable."
        )
        start_arr = p2a["live_arr"].iloc[-1]
        end_arr = p2b["live_arr"].iloc[-1]
        d_new = p2b["new_arr_booked"].sum() - p2a["new_arr_booked"].sum()
        d_exp = (rnb["expansion_arr"].sum() if len(rnb) else 0) - (rna["expansion_arr"].sum() if len(rna) else 0)
        d_contr = -((rnb["contraction_arr"].sum() if len(rnb) else 0) - (rna["contraction_arr"].sum() if len(rna) else 0))
        d_churn = -((rnb["churned_arr"].sum() if len(rnb) else 0) - (rna["churned_arr"].sum() if len(rna) else 0))
        other = end_arr - (start_arr + d_new + d_exp + d_contr + d_churn)

        fig_arr = make_waterfall(
            [f"{scenario_a_name}<br>Ending ARR", "Δ New Business<br>(Booked)", "Δ Expansion", "Δ Contraction", "Δ Churn", "Other /<br>Interaction", f"{scenario_b_name}<br>Ending ARR"],
            [start_arr, d_new, d_exp, d_contr, d_churn, other, end_arr],
            "ARR Bridge",
        )
        st.plotly_chart(fig_arr, width='stretch')

        st.divider()
        st.subheader(f"Revenue Bridge: {scenario_a_name} → {scenario_b_name}")
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
            [f"{scenario_a_name}<br>Total Revenue<br>Recognized", "Δ New-Business<br>Subscription", "Δ Renewal-Driven<br>Subscription", "Δ PS Fees", f"{scenario_b_name}<br>Total Revenue<br>Recognized"],
            [start_rev, d_sub_new, d_sub_renewal, d_ps, end_rev],
            "Revenue Bridge",
        )
        st.plotly_chart(fig_rev, width='stretch')

    with tab3:
        st.caption("Tables shown with months as columns, metrics as rows.")
        st.subheader(f"{scenario_a_name} — Phase 2 Output")
        st.dataframe(style_wide(wide(p2a)), width='stretch')
        st.subheader(f"{scenario_b_name} — Phase 2 Output")
        st.dataframe(style_wide(wide(p2b)), width='stretch')

st.caption("Built on the Bowtie Model (Winning by Design). All math is deterministic — no randomized variables anywhere in this model.")
