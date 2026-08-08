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
# Sidebar input renderer — used for both single-scenario mode and each side
# of a comparison. `key` namespaces every widget so two instances can run
# side by side without Streamlit key collisions.
# ---------------------------------------------------------------------------
def render_inputs(key: str, label: str) -> dict:
    st.sidebar.subheader(label)

    pod_name = st.sidebar.text_input("Pod name", "MidMarket", key=f"{key}_pod_name")

    st.sidebar.caption("Team")
    num_aes = st.sidebar.number_input("Number of AEs", 0, 50, 3, key=f"{key}_num_aes")
    num_bdrs = st.sidebar.number_input("Number of BDRs", 0, 50, 2, key=f"{key}_num_bdrs")
    hiring_cadence = st.sidebar.number_input("Hiring cadence (months between hires)", 1, 12, 3, key=f"{key}_cadence")

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
        ae_comp_template=RoleComp(annual_base=cfg["ae_base"], annual_variable_at_100pct=cfg["ae_variable"], annual_quota=cfg["ae_quota"]),
        bdr_comp_template=RoleComp(annual_base=cfg["bdr_base"], annual_variable_at_100pct=cfg["bdr_variable"],
                                    annual_quota=cfg["bdr_monthly_sql_quota"] * 12) if cfg["num_bdrs"] > 0 else None,
        marketing=MarketingFunnel(monthly_leads=cfg["monthly_leads"], lead_to_mql_rate=cfg["lead_to_mql"], mql_to_sql_rate=cfg["mql_to_sql"]),
        avg_deal_size=cfg["avg_deal_size"], win_rate_marketing_sourced=cfg["win_marketing"],
        win_rate_bdr_sourced=cfg["win_bdr"], win_rate_ae_self_sourced=cfg["win_self"],
        ae_self_sourced_sqls_per_month=cfg["ae_self_sourced"], execution_efficiency=cfg["execution_efficiency"],
        hiring_cadence_months=int(cfg["hiring_cadence"]), contract_term_months=int(cfg["contract_term"]),
        implementation_lag_months=int(cfg["implementation_lag"]), professional_services_fee_pct_of_arr=cfg["ps_fee_pct"],
        seasonality_pattern=cfg["seasonality_pattern"],
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
    try:
        result = run_full_model(cfg, num_months)
    except Exception as e:
        st.error(f"Model error: {e}")
        st.stop()

    phase1_df, phase2_df, renewals_df = result["phase1_df"], result["phase2_df"], result["renewals_df"]

    tab1, tab2, tab3, tab4 = st.tabs(["📈 Pipeline & Capacity", "💰 Revenue Recognition", "🔄 Renewals & NRR", "📋 Raw Data"])

    with tab1:
        st.subheader("Bookings: Capacity vs. Demand Constraint")
        st.line_chart(phase1_df.set_index("month")[["capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings"]])
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Bookings", f"${phase1_df['actual_bookings'].sum():,.0f}")
        col2.metric("Total Cost of Capacity", f"${phase1_df['total_cost_of_capacity'].sum():,.0f}")
        months_capacity_bound = (phase1_df["binding_constraint"] == "CAPACITY").sum()
        col3.metric("Months Capacity-Bound", f"{months_capacity_bound}/{len(phase1_df)}")

    with tab2:
        st.subheader("Live ARR Trajectory")
        st.line_chart(phase2_df.set_index("month")[["live_arr", "cumulative_arr_booked"]])
        col1, col2, col3 = st.columns(3)
        col1.metric("Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
        col2.metric("Ending Deferred Revenue", f"${phase2_df['deferred_revenue_balance'].iloc[-1]:,.0f}")
        col3.metric("Ending Live Accounts", f"{int(phase2_df['live_accounts'].iloc[-1])}")
        st.subheader("Revenue Streams")
        st.bar_chart(phase2_df.set_index("month")[["subscription_revenue_recognized", "ps_fee_revenue_recognized"]])

    with tab3:
        st.subheader("Renewal Cohort Summary")
        if len(renewals_df) > 0:
            summary = summarize_renewals(renewals_df)
            col1, col2, col3 = st.columns(3)
            col1.metric("Blended NRR", f"{summary['blended_nrr_pct']}%")
            col2.metric("Total Renewal Events", summary['total_renewal_events'])
            col3.metric("Total Expansion ARR", f"${summary['total_expansion_arr']:,.0f}")
            st.info(summary["nrr_benchmark_check"])
            st.dataframe(wide(renewals_df), use_container_width=True)
        else:
            st.info("No renewal events occurred — scenario length may be shorter than the contract term.")

    with tab4:
        st.caption("Tables shown with months as columns (left → right), metrics as rows — matches how financial models are normally read.")
        st.subheader("Phase 1: Pipeline & Capacity")
        st.dataframe(wide(phase1_df), use_container_width=True)
        st.subheader("Phase 2: Revenue Recognition")
        st.dataframe(wide(phase2_df), use_container_width=True)
        st.subheader("Phase 3: Renewal Events")
        st.dataframe(wide(renewals_df), use_container_width=True)

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
        st.dataframe(wide(p2a), use_container_width=True)
        st.subheader("Scenario B — Phase 2 Output")
        st.dataframe(wide(p2b), use_container_width=True)

st.caption("Built on the Bowtie Model (Winning by Design). All math is deterministic — no randomized variables anywhere in this model.")
